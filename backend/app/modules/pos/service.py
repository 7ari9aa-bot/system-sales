"""POS domain service — the sell flow and the cash-drawer truth (§189).

The POS says "make me a sale"; it never says "decrement stock". Every sell is
CreateOrder → capture payment → the §140 reservation machinery settles the
stock, exactly as a WhatsApp order would. This module owns registers,
sessions and cash rows only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.orders.money import to_money
from app.modules.pos.models import (
    PosCashMovement,
    PosReceipt,
    PosRegister,
    PosSession,
)

_MANUAL_CASH_REASONS = {"pay_in", "pay_out", "cash_drop", "float_adjust"}
# Written only by the sell flow — a hand-written cash_sale would book money
# no order claims, the same lie a hand-written inventory `hold` would tell.
_SALE_ONLY_CASH_REASONS = {"cash_sale", "cash_refund"}
_CASH_DIRECTIONS = {"in", "out"}
_SALE_METHODS = {"cash", "card", "wallet", "bank_transfer"}
_NUMBER_ATTEMPTS = 3


def _positive_amount(value: object, field: str) -> Decimal:
    amount = to_money(value, field)
    if amount <= 0:
        raise ValidationError(f"{field} must be greater than zero")
    return amount


class PosService:
    """All POS rules; static methods taking (session, tenant_id), flush-only."""

    # --------------------------------------------------------- registers ----

    @staticmethod
    async def create_register(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        name: str,
        code: str,
        warehouse_id: UUID,
    ) -> PosRegister:
        from app.modules.inventory.service import InventoryService

        cleaned_code = str(code).strip()
        if not cleaned_code or len(cleaned_code) > 31:
            raise ValidationError("register code must be 1-31 characters")
        await InventoryService.get_warehouse(session, tenant_id, warehouse_id)
        register = PosRegister(
            tenant_id=tenant_id,
            name=str(name).strip() or cleaned_code,
            code=cleaned_code,
            warehouse_id=warehouse_id,
        )
        session.add(register)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            raise ConflictError(f"register code '{cleaned_code}' already exists") from None
        return register

    @staticmethod
    async def list_registers(
        session: AsyncSession, tenant_id: UUID
    ) -> list[PosRegister]:
        rows = (
            await session.execute(
                select(PosRegister)
                .where(PosRegister.tenant_id == tenant_id)
                .order_by(PosRegister.created_at.asc(), PosRegister.id.asc())
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def _get_register(
        session: AsyncSession, tenant_id: UUID, register_id: UUID
    ) -> PosRegister:
        register = (
            await session.execute(
                select(PosRegister).where(
                    PosRegister.tenant_id == tenant_id,
                    PosRegister.id == register_id,
                )
            )
        ).scalar_one_or_none()
        if register is None:
            raise NotFoundError(f"register {register_id} not found")
        return register

    # ----------------------------------------------------------- sessions ----

    @staticmethod
    async def open_session(
        session: AsyncSession,
        tenant_id: UUID,
        register_id: UUID,
        *,
        opening_float: object = "0.00",
        opened_by: UUID | None = None,
    ) -> PosSession:
        """OPEN the drawer. One OPEN session per register is enforced by a
        partial unique index; this pre-check exists to fail with a sentence."""
        register = await PosService._get_register(session, tenant_id, register_id)
        if not register.is_active:
            raise ConflictError(f"register {register.code} is not active")
        open_now = (
            await session.execute(
                select(PosSession.id).where(
                    PosSession.tenant_id == tenant_id,
                    PosSession.register_id == register_id,
                    PosSession.status == "OPEN",
                )
            )
        ).scalar_one_or_none()
        if open_now is not None:
            raise ConflictError(
                f"register {register.code} already has an open session"
            )
        pos_session = PosSession(
            tenant_id=tenant_id,
            register_id=register_id,
            opened_by_user_id=opened_by,
            opening_float=to_money(opening_float, "opening_float"),
        )
        session.add(pos_session)
        await session.flush()
        return pos_session

    @staticmethod
    async def _get_session(
        session: AsyncSession, tenant_id: UUID, session_id: UUID
    ) -> PosSession:
        pos_session = (
            await session.execute(
                select(PosSession).where(
                    PosSession.tenant_id == tenant_id,
                    PosSession.id == session_id,
                )
            )
        ).scalar_one_or_none()
        if pos_session is None:
            raise NotFoundError(f"pos session {session_id} not found")
        return pos_session

    @staticmethod
    async def get_session(
        session: AsyncSession, tenant_id: UUID, session_id: UUID
    ) -> dict:
        """The session plus its live cash position — what the closing screen shows."""
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        inflow, outflow = await PosService._cash_totals(
            session, tenant_id, pos_session.id
        )
        expected_now = Decimal(pos_session.opening_float) + inflow - outflow
        return {
            "session": pos_session,
            "inflow": inflow,
            "outflow": outflow,
            "expected_now": expected_now,
        }

    # -------------------------------------------------------------- cash ----

    @staticmethod
    async def _cash_totals(
        session: AsyncSession, tenant_id: UUID, session_id: UUID
    ) -> tuple[Decimal, Decimal]:
        rows = (
            await session.execute(
                select(
                    PosCashMovement.direction,
                    func.coalesce(func.sum(PosCashMovement.amount), Decimal("0")),
                )
                .where(
                    PosCashMovement.tenant_id == tenant_id,
                    PosCashMovement.session_id == session_id,
                )
                .group_by(PosCashMovement.direction)
            )
        ).all()
        inflow = next((Decimal(a) for d, a in rows if d == "in"), Decimal("0"))
        outflow = next((Decimal(a) for d, a in rows if d == "out"), Decimal("0"))
        return inflow, outflow

    @staticmethod
    async def record_cash_movement(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        direction: str,
        reason: str,
        amount: object,
        created_by: UUID | None = None,
        reference_type: str | None = None,
        reference_id: UUID | None = None,
    ) -> PosCashMovement:
        """Book a manual cash event on an OPEN session.

        cash_sale/cash_refund are the sell flow's rows: writing one by hand
        would claim money the order ledger does not show (§189).
        """
        if direction not in _CASH_DIRECTIONS:
            raise ValidationError(f"direction must be one of {sorted(_CASH_DIRECTIONS)}")
        if reason not in _MANUAL_CASH_REASONS:
            if reason in _SALE_ONLY_CASH_REASONS:
                raise ValidationError(
                    f"reason '{reason}' is written by the sell flow only"
                )
            raise ValidationError(
                f"reason must be one of {sorted(_MANUAL_CASH_REASONS)}"
            )
        pos_session = await PosService._get_session(session, tenant_id, session_id)
        if pos_session.status != "OPEN":
            raise ConflictError("cash rows are booked on the open session only")
        row = PosCashMovement(
            tenant_id=tenant_id,
            session_id=session_id,
            direction=direction,
            reason=reason,
            amount=_positive_amount(amount, "amount"),
            reference_type=reference_type,
            reference_id=reference_id,
            created_by_user_id=created_by,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def _append_sale_cash(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        reason: str,
        amount: Decimal,
        created_by: UUID | None,
        reference_id: UUID,
    ) -> PosCashMovement:
        row = PosCashMovement(
            tenant_id=tenant_id,
            session_id=session_id,
            direction="in" if reason == "cash_sale" else "out",
            reason=reason,
            amount=amount,
            reference_type="order",
            reference_id=reference_id,
            created_by_user_id=created_by,
        )
        session.add(row)
        await session.flush()
        return row

    # --------------------------------------------------------------- sell ----

    @staticmethod
    async def sell(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        customer_id: UUID,
        items: list[dict],
        method: str = "cash",
        amount: object | None = None,
        actor_user_id: UUID | None = None,
    ) -> dict:
        """One POS sale = one commerce command chain (§189).

        CreateOrder (channel="pos", register's warehouse) → capture payment →
        the §140 reservation machinery settles the stock. The drawer's cash
        row is written here, in the same transaction, because the money is
        in the drawer now.
        """
        from app.modules.orders.service import OrderService

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        if pos_session.status != "OPEN":
            raise ConflictError("this session is closed; open a new one to sell")
        if not items:
            raise ValidationError("a sale must contain at least one item")
        if method not in _SALE_METHODS:
            raise ValidationError(
                f"method must be one of {sorted(_SALE_METHODS)}, got {method!r}"
            )
        register = await PosService._get_register(
            session, tenant_id, pos_session.register_id
        )

        order = await OrderService.create_order(
            session,
            tenant_id,
            customer_id,
            items,
            channel="pos",
            warehouse_id=register.warehouse_id,
        )
        payment = await OrderService.add_payment(
            session,
            tenant_id,
            order.id,
            method=method,
            amount=amount if amount is not None else order.grand_total,
        )
        if method == "cash":
            await PosService._append_sale_cash(
                session,
                tenant_id,
                pos_session.id,
                reason="cash_sale",
                amount=Decimal(payment.amount),
                created_by=actor_user_id,
                reference_id=order.id,
            )
        receipt = await PosService._issue_receipt(session, tenant_id, pos_session, order)
        return {
            "order_id": order.id,
            "order_number": order.number,
            "payment_id": payment.id,
            "receipt_id": receipt.id,
            "receipt_number": receipt.number,
        }

    @staticmethod
    async def _issue_receipt(
        session: AsyncSession, tenant_id: UUID, pos_session: PosSession, order
    ) -> PosReceipt:
        last_exc: IntegrityError | None = None
        for _attempt in range(_NUMBER_ATTEMPTS):
            number = f"POS-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
            receipt = PosReceipt(
                tenant_id=tenant_id,
                order_id=order.id,
                session_id=pos_session.id,
                number=number,
            )
            try:
                async with session.begin_nested():
                    session.add(receipt)
                    await session.flush()
                return receipt
            except IntegrityError as exc:
                last_exc = exc
        raise ConflictError("could not allocate a receipt number") from last_exc

    # -------------------------------------------------------------- close ----

    @staticmethod
    async def close_session(
        session: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        *,
        counted_cash: object,
        closed_by: UUID | None = None,
    ) -> PosSession:
        """OPEN → CLOSED; the POS cash reconciliation (§188) happens here.

        expected = opening float + cash in − cash out, computed from the rows.
        The variance is stored, never applied to anything — the merchant
        decides what a short drawer means.
        """
        from app.core.events.writer import add_outbox_event

        pos_session = await PosService._get_session(session, tenant_id, session_id)
        if pos_session.status != "OPEN":
            raise ConflictError(f"pos session is already {pos_session.status}")
        counted = to_money(counted_cash, "counted_cash")
        if counted < 0:
            raise ValidationError("counted_cash must not be negative")
        inflow, outflow = await PosService._cash_totals(
            session, tenant_id, pos_session.id
        )
        expected = Decimal(pos_session.opening_float) + inflow - outflow
        variance = counted - expected

        pos_session.status = "CLOSED"
        pos_session.counted_cash = counted
        pos_session.expected_cash = expected
        pos_session.variance = variance
        pos_session.closed_by_user_id = closed_by
        pos_session.closed_at = datetime.now(UTC)
        await session.flush()

        # The close is a business event: analytics reconciles cash from the
        # rows, never by querying this session's columns mid-transaction (§190).
        await add_outbox_event(
            session,
            aggregate_type="pos_session",
            aggregate_id=pos_session.id,
            event_type="pos.session.closed",
            tenant_id=tenant_id,
            payload={
                "pos.session.closed": True,
                "session_id": str(pos_session.id),
                "register_id": str(pos_session.register_id),
                "expected": str(expected),
                "counted": str(counted),
                "variance": str(variance),
            },
            producer="pos",
        )
        return pos_session
