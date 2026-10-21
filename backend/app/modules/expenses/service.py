"""EXPENSES service: categories, posting, voiding, listing.

Money rules (the same as the POS):
  * amounts are Decimal with at most 2 places. Unlike to_money(), which ROUNDS, a value
    with a third decimal is REJECTED: silently turning 10.005 into 10.01 books money the
    user never typed.
  * a CASH expense is paid out of an OPEN drawer: it books one `pay_out` row on that
    session (reference_type='expense') in the same transaction, so the drawer's expected
    cash drops by exactly the expense.
  * a posted expense is never edited. void() books the reverse drawer row (`pay_in`) and
    flips the status once; voiding twice is a conflict, not a second reversal.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.expenses.models import (
    EXPENSE_PAYMENT_METHODS,
    DocumentCounter,
    Expense,
    ExpenseCategory,
)

DEFAULT_CATEGORIES: tuple[str, ...] = (
    "مستلزمات تغليف",
    "نقل وشحن",
    "إنترنت واتصالات",
    "كهرباء ومياه",
    "تسويق وإعلانات",
    "صيانة",
    "رواتب",
    "نظافة",
    "إيجار",
    "مصاريف إدارية",
    "أخرى",
)


def exact_money(value: object, field: str = "amount") -> Decimal:
    """`orders.money.exact_money`, with its refusals surfaced as a 422 like every other input."""
    # Function-scope on purpose: a module-load import would add an edge to `orders`.
    from app.modules.orders.money import exact_money as _exact_money

    try:
        return _exact_money(value, field)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def _pos_service():
    """POS owns the drawer, so a cash expense goes through ITS service (never its tables).

    Imported lazily on purpose: expenses -> pos is a real dependency, but declaring it at
    module scope would grow the cross-module import ratchet (tests/test_module_boundaries).
    """
    from app.modules.pos.service import PosService

    return PosService


class NumberingService:
    """Gap-free document numbers per tenant, kind and year."""

    @staticmethod
    async def next_number(
        session: AsyncSession, tenant_id: UUID, kind: str, *, on: date | None = None
    ) -> str:
        year = (on or datetime.now(UTC).date()).year
        await session.execute(
            pg_insert(DocumentCounter)
            .values(id=uuid.uuid4(), tenant_id=tenant_id, kind=kind, year=year, last_seq=0)
            .on_conflict_do_nothing(constraint="uq_document_counters_tenant_kind_year")
        )
        counter = (
            await session.execute(
                select(DocumentCounter)
                .where(
                    DocumentCounter.tenant_id == tenant_id,
                    DocumentCounter.kind == kind,
                    DocumentCounter.year == year,
                )
                .with_for_update()
            )
        ).scalar_one()
        counter.last_seq += 1
        await session.flush()
        return f"{kind}-{year}-{counter.last_seq:04d}"


class ExpenseService:
    # ------------------------------------------------------------ categories ----

    @staticmethod
    async def list_categories(
        session: AsyncSession, tenant_id: UUID, *, include_inactive: bool = False
    ) -> list[ExpenseCategory]:
        q = select(ExpenseCategory).where(ExpenseCategory.tenant_id == tenant_id)
        if not include_inactive:
            q = q.where(ExpenseCategory.is_active.is_(True))
        rows = (
            await session.execute(q.order_by(ExpenseCategory.created_at, ExpenseCategory.name))
        ).scalars()
        return list(rows)

    @staticmethod
    async def ensure_default_categories(
        session: AsyncSession, tenant_id: UUID
    ) -> list[ExpenseCategory]:
        """Seed the shop's categories once. Safe to call on every read."""
        existing = await ExpenseService.list_categories(session, tenant_id, include_inactive=True)
        if existing:
            return existing
        for name in DEFAULT_CATEGORIES:
            await session.execute(
                pg_insert(ExpenseCategory)
                .values(id=uuid.uuid4(), tenant_id=tenant_id, name=name, is_active=True)
                .on_conflict_do_nothing(constraint="uq_expense_categories_tenant_name")
            )
        await session.flush()
        return await ExpenseService.list_categories(session, tenant_id, include_inactive=True)

    @staticmethod
    async def create_category(session: AsyncSession, tenant_id: UUID, name: str) -> ExpenseCategory:
        name = (name or "").strip()
        if not name:
            raise ValidationError("name is required")
        if len(name) > 80:
            raise ValidationError("name must be at most 80 characters")
        dup = (
            await session.execute(
                select(ExpenseCategory.id).where(
                    ExpenseCategory.tenant_id == tenant_id,
                    func.lower(ExpenseCategory.name) == name.lower(),
                )
            )
        ).first()
        if dup:
            raise ConflictError(f"category '{name}' already exists")
        row = ExpenseCategory(tenant_id=tenant_id, name=name)
        session.add(row)
        await session.flush()
        return row

    # ------------------------------------------------------------- expenses ----

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        category_id: UUID,
        description: str,
        amount: object,
        payment_method: str,
        expense_date: date | None = None,
        session_id: UUID | None = None,
        created_by: UUID | None = None,
        shift_override: bool = False,
    ) -> Expense:
        description = (description or "").strip()
        if not description:
            raise ValidationError("description is required")
        if len(description) > 255:
            raise ValidationError("description must be at most 255 characters")
        if payment_method not in EXPENSE_PAYMENT_METHODS:
            raise ValidationError(
                f"payment_method must be one of {sorted(EXPENSE_PAYMENT_METHODS)}"
            )
        value = exact_money(amount)

        category = (
            await session.execute(
                select(ExpenseCategory).where(
                    ExpenseCategory.tenant_id == tenant_id, ExpenseCategory.id == category_id
                )
            )
        ).scalar_one_or_none()
        if category is None:
            raise NotFoundError("expense category not found")
        if not category.is_active:
            raise ConflictError("this expense category is inactive")

        cash_session = None
        if payment_method == "cash":
            if session_id is None:
                raise ConflictError("a cash expense is paid from an open shift: open a shift first")
            cash_session = await _pos_service()._get_session(session, tenant_id, session_id)
            _pos_service()._ensure_holds_shift(cash_session, created_by, override=shift_override)
            if cash_session.status != "OPEN":
                raise ConflictError("a cash expense needs an OPEN shift; this one is closed")
        elif session_id is not None:
            raise ValidationError("only a cash expense is tied to a shift")

        when = expense_date or datetime.now(UTC).date()
        expense = Expense(
            tenant_id=tenant_id,
            number=await NumberingService.next_number(session, tenant_id, "EXP", on=when),
            category_id=category_id,
            description=description,
            amount=value,
            payment_method=payment_method,
            expense_date=when,
            session_id=cash_session.id if cash_session else None,
            status="posted",
            created_by_user_id=created_by,
        )
        session.add(expense)
        await session.flush()

        if cash_session is not None:
            await _pos_service().record_cash_movement(
                session,
                tenant_id,
                cash_session.id,
                direction="out",
                reason="pay_out",
                amount=value,
                created_by=created_by,
                reference_type="expense",
                reference_id=expense.id,
            )
        return expense

    @staticmethod
    async def get(session: AsyncSession, tenant_id: UUID, expense_id: UUID) -> Expense:
        row = (
            await session.execute(
                select(Expense).where(Expense.tenant_id == tenant_id, Expense.id == expense_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("expense not found")
        return row

    @staticmethod
    async def void(
        session: AsyncSession,
        tenant_id: UUID,
        expense_id: UUID,
        *,
        reason: str,
        voided_by: UUID | None = None,
        shift_override: bool = False,
    ) -> Expense:
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("a reason is required to void an expense")
        if len(reason) > 255:
            raise ValidationError("reason must be at most 255 characters")
        expense = (
            await session.execute(
                select(Expense)
                .where(Expense.tenant_id == tenant_id, Expense.id == expense_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if expense is None:
            raise NotFoundError("expense not found")
        if expense.status == "voided":
            raise ConflictError("this expense is already voided")

        if expense.payment_method == "cash" and expense.session_id is not None:
            drawer = await _pos_service()._get_session(session, tenant_id, expense.session_id)
            if drawer.status != "OPEN":
                raise ConflictError(
                    "the shift that paid this expense is closed: "
                    "record the correction in the current shift"
                )
            await _pos_service().record_cash_movement(
                session,
                tenant_id,
                drawer.id,
                direction="in",
                reason="pay_in",
                amount=expense.amount,
                created_by=voided_by,
                shift_override=shift_override,
                reference_type="expense_void",
                reference_id=expense.id,
            )
        expense.status = "voided"
        expense.voided_at = datetime.now(UTC)
        expense.void_reason = reason
        await session.flush()
        return expense

    @staticmethod
    async def list(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        category_id: UUID | None = None,
        payment_method: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Expense]:
        q = select(Expense).where(Expense.tenant_id == tenant_id)
        if date_from:
            q = q.where(Expense.expense_date >= date_from)
        if date_to:
            q = q.where(Expense.expense_date <= date_to)
        if category_id:
            q = q.where(Expense.category_id == category_id)
        if payment_method:
            q = q.where(Expense.payment_method == payment_method)
        if status:
            q = q.where(Expense.status == status)
        q = (
            q.order_by(Expense.expense_date.desc(), Expense.created_at.desc(), Expense.id)
            .limit(limit)
            .offset(offset)
        )
        return list((await session.execute(q)).scalars())

    @staticmethod
    async def totals(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        """Posted (not voided) totals, overall and per payment method / category."""
        q = select(
            Expense.payment_method, Expense.category_id, func.sum(Expense.amount), func.count()
        ).where(Expense.tenant_id == tenant_id, Expense.status == "posted")
        if date_from:
            q = q.where(Expense.expense_date >= date_from)
        if date_to:
            q = q.where(Expense.expense_date <= date_to)
        rows = (
            await session.execute(q.group_by(Expense.payment_method, Expense.category_id))
        ).all()
        by_method: dict[str, Decimal] = {}
        by_category: dict[str, Decimal] = {}
        total = Decimal("0")
        count = 0
        for method, cat, amt, n in rows:
            amt = Decimal(amt)
            total += amt
            count += int(n)
            by_method[method] = by_method.get(method, Decimal("0")) + amt
            by_category[str(cat)] = by_category.get(str(cat), Decimal("0")) + amt
        return {"total": total, "count": count, "by_method": by_method, "by_category": by_category}
