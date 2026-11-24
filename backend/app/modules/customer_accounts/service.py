"""Customer account service: the only writer of the customer ledger.

Every posting locks the customer's account row first, so two tills selling on credit to the same
customer at the same moment are serialised: the second one sees the first one's debt and the
credit limit holds. The balance comes from the ledger, never from a number somebody edited.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customer_accounts.models import CustomerAccount, CustomerLedgerEntry
from app.modules.customer_accounts.rules import (
    AccountRuleError,
    apply_deposit,
    check_credit_sale,
    money,
    signed_amount,
)
from app.modules.errors import ConflictError, NotFoundError, ValidationError

_ZERO = Decimal("0.00")


class CustomerAccountService:
    @staticmethod
    async def open_account(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        credit_limit: object = None,
        note: str | None = None,
    ) -> CustomerAccount:
        """Opt a customer in to credit. Calling it again edits the terms, it never duplicates."""
        limit = None
        if credit_limit is not None and str(credit_limit).strip() != "":
            try:
                limit = money(credit_limit, "credit_limit")
            except AccountRuleError as exc:
                raise ValidationError(str(exc)) from exc
            if limit < 0:
                raise ValidationError("credit_limit cannot be negative")
        await CustomerAccountService._require_customer(session, tenant_id, customer_id)
        row = await CustomerAccountService._locked(session, tenant_id, customer_id)
        if row is None:
            row = CustomerAccount(
                tenant_id=tenant_id, customer_id=customer_id, credit_limit=limit, note=note
            )
            session.add(row)
        else:
            row.credit_limit = limit
            if note is not None:
                row.note = note
        await session.flush()
        return row

    @staticmethod
    async def get_account(
        session: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
    ) -> CustomerAccount | None:
        return (
            await session.execute(
                select(CustomerAccount).where(
                    CustomerAccount.tenant_id == tenant_id,
                    CustomerAccount.customer_id == customer_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def balance(
        session: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
    ) -> Decimal:
        """What the customer owes (positive) or is owed (negative): the SUM of the ledger."""
        total = (
            await session.execute(
                select(func.coalesce(func.sum(CustomerLedgerEntry.amount), 0)).where(
                    CustomerLedgerEntry.tenant_id == tenant_id,
                    CustomerLedgerEntry.customer_id == customer_id,
                )
            )
        ).scalar_one()
        return Decimal(str(total)).quantize(Decimal("0.01"))

    @staticmethod
    async def statement(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        limit: int = 200,
    ) -> list[CustomerLedgerEntry]:
        rows = (
            await session.execute(
                select(CustomerLedgerEntry)
                .where(
                    CustomerLedgerEntry.tenant_id == tenant_id,
                    CustomerLedgerEntry.customer_id == customer_id,
                )
                .order_by(CustomerLedgerEntry.seq.desc())
                .limit(max(1, min(limit, 1000)))
            )
        ).scalars()
        return list(rows)

    # ---- postings ----

    @staticmethod
    async def charge(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        sale_total: object,
        paid_now: object = "0",
        order_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
        actor_user_id: uuid.UUID | None = None,
        blocked: bool = False,
    ) -> CustomerLedgerEntry | None:
        """Put the unpaid part of a sale on the customer's account, if the limit allows it.

        Returns None when the whole sale was paid now (nothing goes on account).
        """
        replay = await CustomerAccountService._replay(session, tenant_id, idempotency_key)
        if replay is not None:
            return replay
        account = await CustomerAccountService._require_open(session, tenant_id, customer_id)
        try:
            total = money(sale_total, "sale_total")
            paid = money(paid_now, "paid_now")
            current = await CustomerAccountService.balance(session, tenant_id, customer_id)
            decision = check_credit_sale(
                current_balance=current,
                sale_total=total,
                paid_now=paid,
                credit_limit=(
                    None if account.credit_limit is None else Decimal(str(account.credit_limit))
                ),
                blocked=blocked,
            )
        except AccountRuleError as exc:
            raise ValidationError(str(exc)) from exc
        if not decision.allowed:
            raise ConflictError(decision.reason or "credit refused")
        on_account = total - paid
        if on_account == 0:
            return None
        return await CustomerAccountService._post(
            session,
            tenant_id,
            customer_id,
            "charge",
            on_account,
            order_id=order_id,
            idempotency_key=idempotency_key,
            actor_user_id=actor_user_id,
            current=current,
        )

    @staticmethod
    async def receive_payment(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        amount: object,
        idempotency_key: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> CustomerLedgerEntry:
        """The customer pays down what they owe. Paying more than they owe is refused: the
        surplus is a deposit and must be recorded as one, on purpose."""
        replay = await CustomerAccountService._replay(session, tenant_id, idempotency_key)
        if replay is not None:
            return replay
        await CustomerAccountService._require_open(session, tenant_id, customer_id)
        value = CustomerAccountService._positive(amount)
        current = await CustomerAccountService.balance(session, tenant_id, customer_id)
        if current <= 0:
            raise ConflictError("هذا العميل لا عليه مديونية")
        if value > current:
            raise ConflictError(f"المبلغ أكبر من المديونية ({current}). سجّل الزيادة كعربون إن أردت")
        return await CustomerAccountService._post(
            session,
            tenant_id,
            customer_id,
            "payment",
            value,
            idempotency_key=idempotency_key,
            actor_user_id=actor_user_id,
            current=current,
        )

    @staticmethod
    async def take_deposit(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        amount: object,
        idempotency_key: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> CustomerLedgerEntry:
        """Money taken in advance: the shop now holds credit for the customer."""
        replay = await CustomerAccountService._replay(session, tenant_id, idempotency_key)
        if replay is not None:
            return replay
        await CustomerAccountService._require_open(session, tenant_id, customer_id)
        value = CustomerAccountService._positive(amount)
        current = await CustomerAccountService.balance(session, tenant_id, customer_id)
        return await CustomerAccountService._post(
            session,
            tenant_id,
            customer_id,
            "deposit",
            value,
            idempotency_key=idempotency_key,
            actor_user_id=actor_user_id,
            current=current,
        )

    @staticmethod
    async def apply_deposit_to_sale(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        sale_total: object,
        order_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> Decimal:
        """Use up as much of the customer's deposit as the sale can take. Returns the amount used
        (0.00 when they hold none), so the till knows what is left to collect."""
        replay = await CustomerAccountService._replay(session, tenant_id, idempotency_key)
        if replay is not None:
            return Decimal(str(replay.amount))
        await CustomerAccountService._require_open(session, tenant_id, customer_id)
        try:
            total = money(sale_total, "sale_total")
        except AccountRuleError as exc:
            raise ValidationError(str(exc)) from exc
        current = await CustomerAccountService.balance(session, tenant_id, customer_id)
        used = apply_deposit(balance_now=current, sale_total=total)
        if used <= 0:
            return _ZERO
        await CustomerAccountService._post(
            session,
            tenant_id,
            customer_id,
            "deposit_applied",
            used,
            order_id=order_id,
            idempotency_key=idempotency_key,
            actor_user_id=actor_user_id,
            current=current,
        )
        return used

    @staticmethod
    async def adjust(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        amount: object,
        reason: str,
        actor_user_id: uuid.UUID | None = None,
    ) -> CustomerLedgerEntry:
        """A manager's correction. Always carries a reason; + raises debt, - lowers it."""
        if not reason or not reason.strip():
            raise ValidationError("a reason is required for an adjustment")
        await CustomerAccountService._require_open(session, tenant_id, customer_id)
        try:
            signed = signed_amount("adjustment", amount)
        except AccountRuleError as exc:
            raise ValidationError(str(exc)) from exc
        current = await CustomerAccountService.balance(session, tenant_id, customer_id)
        return await CustomerAccountService._post(
            session,
            tenant_id,
            customer_id,
            "adjustment",
            signed,
            reason=reason.strip(),
            actor_user_id=actor_user_id,
            current=current,
            already_signed=True,
        )

    @staticmethod
    async def reverse(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        entry_id: uuid.UUID,
        *,
        reason: str,
        actor_user_id: uuid.UUID | None = None,
    ) -> CustomerLedgerEntry:
        """Undo an entry with an equal and opposite one. History is never edited; an entry can be
        reversed once, and a reversal cannot itself be reversed."""
        if not reason or not reason.strip():
            raise ValidationError("a reason is required to reverse an entry")
        original = (
            await session.execute(
                select(CustomerLedgerEntry).where(
                    CustomerLedgerEntry.tenant_id == tenant_id,
                    CustomerLedgerEntry.id == entry_id,
                )
            )
        ).scalar_one_or_none()
        if original is None:
            raise NotFoundError(f"ledger entry {entry_id} not found")
        if original.entry_type == "reversal":
            raise ConflictError("a reversal cannot be reversed: post the entry again instead")
        await CustomerAccountService._require_open(session, tenant_id, original.customer_id)
        already = (
            await session.execute(
                select(CustomerLedgerEntry.id).where(
                    CustomerLedgerEntry.tenant_id == tenant_id,
                    CustomerLedgerEntry.reverses_entry_id == entry_id,
                )
            )
        ).first()
        if already is not None:
            raise ConflictError("this entry has already been reversed")
        current = await CustomerAccountService.balance(session, tenant_id, original.customer_id)
        return await CustomerAccountService._post(
            session,
            tenant_id,
            original.customer_id,
            "reversal",
            -Decimal(str(original.amount)),
            order_id=original.order_id,
            reverses_entry_id=original.id,
            reason=reason.strip(),
            actor_user_id=actor_user_id,
            current=current,
            already_signed=True,
        )

    # ---- internals ----

    @staticmethod
    async def reverse_unpaid_return(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        amount: object,
        *,
        order_id: uuid.UUID | None = None,
        reason: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> CustomerLedgerEntry | None:
        """Returned goods cancel the unpaid part of the sale, up to what is actually owed.

        Capped at the current balance on purpose: a shop never hands a customer credit for goods
        they already settled, and a stale figure must not push the account below zero.
        """
        current = await CustomerAccountService.balance(session, tenant_id, customer_id)
        if current <= 0:
            return None
        owed = await CustomerAccountService.unpaid_on_order(
            session, tenant_id, customer_id, order_id
        )
        if owed <= 0:
            # The invoice itself is settled: a return must not eat another invoice's debt.
            return None
        value = min(CustomerAccountService._positive(amount), current, owed)
        return await CustomerAccountService._post(
            session,
            tenant_id,
            customer_id,
            "adjustment",
            -value,
            order_id=order_id,
            reason=reason,
            actor_user_id=actor_user_id,
            current=current,
        )

    @staticmethod
    async def unpaid_on_order(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_id: uuid.UUID | None,
    ) -> Decimal:
        """What this one invoice still owes on the customer's account.

        Capping a return by the whole balance let a return on one invoice eat another invoice's
        debt; the ledger is read per order so only the goods coming back cancel their own sale.
        """
        if order_id is None:
            return await CustomerAccountService.balance(session, tenant_id, customer_id)
        total = (
            await session.execute(
                select(func.coalesce(func.sum(CustomerLedgerEntry.amount), 0)).where(
                    CustomerLedgerEntry.tenant_id == tenant_id,
                    CustomerLedgerEntry.customer_id == customer_id,
                    CustomerLedgerEntry.order_id == order_id,
                )
            )
        ).scalar_one()
        return max(money(total), Decimal("0.00"))

    @staticmethod
    def _positive(amount: object) -> Decimal:
        try:
            value = money(amount)
        except AccountRuleError as exc:
            raise ValidationError(str(exc)) from exc
        if value <= 0:
            raise ValidationError("the amount must be more than zero")
        return value

    @staticmethod
    async def _post(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        entry_type: str,
        amount: Decimal,
        *,
        current: Decimal,
        order_id: uuid.UUID | None = None,
        reverses_entry_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
        reason: str | None = None,
        actor_user_id: uuid.UUID | None = None,
        already_signed: bool = False,
    ) -> CustomerLedgerEntry:
        try:
            effect = amount if already_signed else signed_amount(entry_type, amount)
        except AccountRuleError as exc:
            raise ValidationError(str(exc)) from exc
        entry = CustomerLedgerEntry(
            tenant_id=tenant_id,
            customer_id=customer_id,
            entry_type=entry_type,
            amount=effect,
            order_id=order_id,
            reverses_entry_id=reverses_entry_id,
            idempotency_key=idempotency_key,
            reason=reason,
            actor_user_id=actor_user_id,
            balance_after=current + effect,
        )
        try:
            async with session.begin_nested():
                session.add(entry)
                await session.flush()
        except IntegrityError as exc:
            replay = await CustomerAccountService._replay(session, tenant_id, idempotency_key)
            if replay is not None:
                return replay
            raise ConflictError("this ledger entry conflicts with an existing one") from exc
        return entry

    @staticmethod
    async def _replay(
        session: AsyncSession, tenant_id: uuid.UUID, key: str | None
    ) -> CustomerLedgerEntry | None:
        """The entry an earlier identical request already posted: resending changes nothing."""
        if not key:
            return None
        return (
            await session.execute(
                select(CustomerLedgerEntry).where(
                    CustomerLedgerEntry.tenant_id == tenant_id,
                    CustomerLedgerEntry.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _locked(
        session: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
    ) -> CustomerAccount | None:
        return (
            await session.execute(
                select(CustomerAccount)
                .where(
                    CustomerAccount.tenant_id == tenant_id,
                    CustomerAccount.customer_id == customer_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _require_open(
        session: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
    ) -> CustomerAccount:
        """The account row, LOCKED for the rest of the transaction: concurrent postings for one
        customer run one after another."""
        account = await CustomerAccountService._locked(session, tenant_id, customer_id)
        if account is None:
            raise ConflictError("هذا العميل ليس له حساب آجل: افتح له حساباً أولاً")
        return account

    @staticmethod
    async def _require_customer(
        session: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
    ) -> None:
        """The customer must be live: an archived or merged-away customer gets no account.

        Goes through the customers service (not its tables), which already refuses both.
        """
        from app.modules.customers.service import CustomerService

        await CustomerService.get(session, tenant_id, customer_id)
