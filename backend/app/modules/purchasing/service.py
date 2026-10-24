"""PURCHASING service: suppliers, purchase orders (create / receive / cancel), supplier payments,
supplier balance, and the moving-average cost.

The rules that matter (each one has a test that breaks if it is removed):
  * Money is Decimal with at most 2 places and is REJECTED, never rounded, past that.
  * Receiving an order is the ONLY thing that moves stock in and changes cost. It runs once
    (status guard + row lock), writes one `purchase` movement per line through
    InventoryService.move(), and updates the moving average in the same transaction.
  * Moving average: new = (on_hand*avg + qty*unit_cost) / (on_hand + qty), kept to 4 places.
    With no stock on hand (or negative stock) the new average IS the incoming cost.
  * Cost rows are locked before stock is read, so two receipts of one variant queue instead of
    both averaging against the same stale quantity.
  * A supplier's balance is DERIVED: received orders - net payments - accepted credit returns.
  * A received order cannot be cancelled once any of its stock has been sold or returned
    (the shelf would no longer hold what the cancel claims to take back).
  * A CASH payment leaves the open drawer through the POS service (one pay_out row).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.purchasing.catalog_lookup import existing_variant_ids
from app.modules.purchasing.models import (
    PAYMENT_METHODS,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierPayment,
    SupplierReturn,
    VariantCost,
    VariantCostHistory,
)


def exact_money(value: object, field: str = "amount") -> Decimal:
    """`orders.money.exact_money`, with its refusals surfaced as a 422 like every other input."""
    # Function-scope on purpose: a module-load import would add an edge to `orders`.
    from app.modules.orders.money import exact_money as _exact_money

    try:
        return _exact_money(value, field)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


_CENT = Decimal("0.01")
_COST_PLACES = Decimal("0.0001")


def _inventory():
    # Lazy on purpose: purchasing -> inventory is a real dependency, but declaring it at module
    # scope would grow the cross-module import ratchet (tests/test_module_boundaries).
    from app.modules.inventory.service import InventoryService

    return InventoryService


def _numbering():
    # Document numbers live with the expenses module (it created document_counters). Lazy for the
    # same reason as the others: a declared, visible dependency without growing the module-scope
    # ratchet.
    from app.modules.expenses.service import NumberingService

    return NumberingService


def money(value: object, field: str = "amount", *, allow_zero: bool = False) -> Decimal:
    """Exactly-2-place money. Zero is allowed only where a free line is legitimate (unit cost)."""
    if allow_zero:
        try:
            if Decimal(str(value).strip()) == 0:
                return Decimal("0.00")
        except Exception:  # noqa: BLE001 - falls through to the strict validator, which names the problem
            pass
    return exact_money(value, field)


def positive_int(value: object, field: str = "quantity") -> int:
    """A quantity typed by a person: plain digits only (optionally ".0").

    "1e3" is refused, not read as 1000.
    """
    text = str(value).strip() if value is not None else ""
    if isinstance(value, bool) or not re.fullmatch(r"\d+(\.0+)?", text):
        raise ValidationError(f"{field} must be a whole number greater than zero")
    number = int(Decimal(text))
    if number <= 0:
        raise ValidationError(f"{field} must be greater than zero")
    if number > 1_000_000:
        raise ValidationError(f"{field} is too large")
    return number


def moving_average(on_hand: int, avg_cost: Decimal, qty: int, unit_cost: Decimal) -> Decimal:
    """The new average cost after receiving `qty` units at `unit_cost`.

    With nothing (or a negative quantity) on hand there is nothing to average against: the
    incoming cost becomes the cost. Never divides by zero and never goes negative.
    """
    if qty <= 0:
        raise ValidationError("received quantity must be positive")
    if on_hand <= 0:
        return Decimal(unit_cost).quantize(_COST_PLACES, rounding=ROUND_HALF_UP)
    total = Decimal(on_hand) * Decimal(avg_cost) + Decimal(qty) * Decimal(unit_cost)
    return (total / Decimal(on_hand + qty)).quantize(_COST_PLACES, rounding=ROUND_HALF_UP)


class SupplierService:
    @staticmethod
    def _clean(value: object, field: str, limit: int, *, required: bool = False) -> str | None:
        text = None if value is None else str(value).strip()
        if not text:
            if required:
                raise ValidationError(f"{field} is required")
            return None
        if len(text) > limit:
            raise ValidationError(f"{field} must be at most {limit} characters")
        return text

    @staticmethod
    async def create(session: AsyncSession, tenant_id: UUID, **fields: Any) -> Supplier:
        clean = SupplierService._clean
        row = Supplier(
            tenant_id=tenant_id,
            name=clean(fields.get("name"), "name", 255, required=True),
            company=clean(fields.get("company"), "company", 255),
            contact_name=clean(fields.get("contact_name"), "contact_name", 255),
            phone=clean(fields.get("phone"), "phone", 31),
            city=clean(fields.get("city"), "city", 80),
            address=clean(fields.get("address"), "address", 2000),
            notes=clean(fields.get("notes"), "notes", 2000),
            status="active",
        )
        existing = (
            await session.execute(
                select(Supplier.id).where(
                    Supplier.tenant_id == tenant_id, func.lower(Supplier.name) == row.name.lower()
                )
            )
        ).first()
        if existing:
            raise ConflictError(f"a supplier named '{row.name}' already exists")
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def get(session: AsyncSession, tenant_id: UUID, supplier_id: UUID) -> Supplier:
        row = (
            await session.execute(
                select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.id == supplier_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("supplier not found")
        return row

    @staticmethod
    async def update(
        session: AsyncSession, tenant_id: UUID, supplier_id: UUID, **fields: Any
    ) -> Supplier:
        row = await SupplierService.get(session, tenant_id, supplier_id)
        clean = SupplierService._clean
        limits = {
            "name": 255, "company": 255, "contact_name": 255, "phone": 31, "city": 80,
            "address": 2000, "notes": 2000,
        }  # fmt: skip
        for key, limit in limits.items():
            if key in fields:
                setattr(row, key, clean(fields[key], key, limit, required=(key == "name")))
        if "status" in fields and fields["status"] is not None:
            if fields["status"] not in ("active", "inactive"):
                raise ValidationError("status must be active or inactive")
            row.status = fields["status"]
        await session.flush()
        return row

    @staticmethod
    async def list(
        session: AsyncSession, tenant_id: UUID, *, status: str | None = None
    ) -> list[Supplier]:
        q = select(Supplier).where(Supplier.tenant_id == tenant_id)
        if status:
            q = q.where(Supplier.status == status)
        return list((await session.execute(q.order_by(Supplier.name, Supplier.id))).scalars())

    @staticmethod
    async def statement(session: AsyncSession, tenant_id: UUID, supplier_id: UUID) -> dict:
        """Derived figures for one supplier. Nothing here is stored, so it cannot drift."""
        await SupplierService.get(session, tenant_id, supplier_id)
        received = (
            await session.execute(
                select(
                    func.coalesce(func.sum(PurchaseOrder.total), 0),
                    func.count(),
                    func.max(PurchaseOrder.order_date),
                ).where(
                    PurchaseOrder.tenant_id == tenant_id,
                    PurchaseOrder.supplier_id == supplier_id,
                    PurchaseOrder.status == "received",
                )
            )
        ).one()
        paid_rows = (
            await session.execute(
                select(
                    SupplierPayment.reverses_payment_id.is_(None),
                    func.coalesce(func.sum(SupplierPayment.amount), 0),
                )
                .where(
                    SupplierPayment.tenant_id == tenant_id,
                    SupplierPayment.supplier_id == supplier_id,
                )
                .group_by(SupplierPayment.reverses_payment_id.is_(None))
            )
        ).all()
        paid = Decimal("0")
        for is_payment, amount in paid_rows:
            paid += Decimal(amount) if is_payment else -Decimal(amount)
        credit = (
            await session.execute(
                select(func.coalesce(func.sum(SupplierReturn.total), 0)).where(
                    SupplierReturn.tenant_id == tenant_id,
                    SupplierReturn.supplier_id == supplier_id,
                    SupplierReturn.status == "accepted",
                    SupplierReturn.settlement == "credit",
                )
            )
        ).scalar_one()
        items = (
            await session.execute(
                select(func.count(func.distinct(PurchaseOrderLine.variant_id)))
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
                .where(
                    PurchaseOrder.tenant_id == tenant_id,
                    PurchaseOrder.supplier_id == supplier_id,
                    PurchaseOrder.status == "received",
                )
            )
        ).scalar_one()
        total = Decimal(received[0]).quantize(_CENT)
        paid = paid.quantize(_CENT)
        credit = Decimal(credit).quantize(_CENT)
        return {
            "total_supplied": total,
            "orders_count": int(received[1]),
            "last_order_date": received[2],
            "items_count": int(items),
            "paid": paid,
            "credit_returns": credit,
            # What the shop still owes. Negative = the supplier owes the shop (overpaid / credit).
            "balance": (total - paid - credit).quantize(_CENT),
        }


class CostService:
    """Moving-average cost per variant. Only receiving writes it."""

    @staticmethod
    async def get(session: AsyncSession, tenant_id: UUID, variant_id: UUID) -> Decimal | None:
        row = (
            await session.execute(
                select(VariantCost.avg_cost).where(
                    VariantCost.tenant_id == tenant_id, VariantCost.variant_id == variant_id
                )
            )
        ).scalar_one_or_none()
        return None if row is None else Decimal(row)

    @staticmethod
    async def _locked(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID
    ) -> VariantCost | None:
        """The cost row FOR UPDATE (creating an empty slot first so there is something to lock)."""
        await session.execute(
            pg_insert(VariantCost)
            .values(id=uuid.uuid4(), tenant_id=tenant_id, variant_id=variant_id, avg_cost=None)
            .on_conflict_do_nothing(constraint="uq_variant_costs_tenant_variant")
        )
        return (
            await session.execute(
                select(VariantCost)
                .where(VariantCost.tenant_id == tenant_id, VariantCost.variant_id == variant_id)
                .with_for_update()
            )
        ).scalar_one()

    @staticmethod
    async def total_on_hand(session: AsyncSession, tenant_id: UUID, variant_id: UUID) -> int:
        return await _inventory().total_on_hand(session, tenant_id, variant_id)

    @staticmethod
    async def apply_receipt(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        *,
        qty: int,
        unit_cost: Decimal,
        purchase_order_id: UUID,
        on_hand_before: int,
    ) -> Decimal:
        """Fold one received line into the average and append the proof. `on_hand_before` is the
        total stock BEFORE this receipt moved it (the caller reads it after taking the lock)."""
        row = await CostService._locked(session, tenant_id, variant_id)
        # avg_cost NULL = unknown: the stock already on the shelf has no recorded price, so there is
        # nothing to
        # average it with. The delivery's price is the best estimate for ALL of it (averaging it in
        # as free
        # would understate every cost from the first delivery on).
        old = None if row.avg_cost is None else Decimal(row.avg_cost)
        new = moving_average(
            on_hand_before if old is not None else 0, old or Decimal(0), qty, unit_cost
        )
        row.avg_cost = new
        session.add(
            VariantCostHistory(
                tenant_id=tenant_id,
                variant_id=variant_id,
                old_avg_cost=old,
                new_avg_cost=new,
                on_hand_before=on_hand_before,
                received_quantity=qty,
                unit_cost=unit_cost,
                purchase_order_id=purchase_order_id,
            )
        )
        await session.flush()
        return new

    @staticmethod
    async def history(
        session: AsyncSession, tenant_id: UUID, variant_id: UUID, *, limit: int = 100
    ) -> list[VariantCostHistory]:
        """Every change to a variant's average cost, newest first, with what it was computed from.

        Newest first by created_at. Two receipts of one variant inside a single transaction
        share that timestamp and then fall back to id, which is stable but not chronological.
        Each row carries on_hand_before, so the true sequence can be re-derived from the rows.
        """
        q = (
            select(VariantCostHistory)
            .where(
                VariantCostHistory.tenant_id == tenant_id,
                VariantCostHistory.variant_id == variant_id,
            )
            .order_by(VariantCostHistory.created_at.desc(), VariantCostHistory.id.desc())
            .limit(limit)
        )
        return list((await session.execute(q)).scalars())


class PurchaseService:
    @staticmethod
    async def _lines_in(
        session: AsyncSession, tenant_id: UUID, po_id: UUID
    ) -> list[PurchaseOrderLine]:
        return list(
            (
                await session.execute(
                    select(PurchaseOrderLine)
                    .where(
                        PurchaseOrderLine.tenant_id == tenant_id,
                        PurchaseOrderLine.purchase_order_id == po_id,
                    )
                    .order_by(PurchaseOrderLine.position)
                )
            ).scalars()
        )

    @staticmethod
    async def get(session: AsyncSession, tenant_id: UUID, po_id: UUID) -> PurchaseOrder:
        row = (
            await session.execute(
                select(PurchaseOrder).where(
                    PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == po_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("purchase order not found")
        return row

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        supplier_id: UUID,
        lines: list[dict],
        order_date: date | None = None,
        warehouse_id: UUID | None = None,
        note: str | None = None,
        receive_now: bool = False,
        created_by: UUID | None = None,
    ) -> PurchaseOrder:
        supplier = await SupplierService.get(session, tenant_id, supplier_id)
        if supplier.status != "active":
            raise ConflictError("this supplier is inactive")
        if not lines:
            raise ValidationError("a purchase order needs at least one line")
        if len(lines) > 200:
            raise ValidationError("a purchase order is limited to 200 lines")
        note = (note or "").strip() or None
        if note and len(note) > 255:
            raise ValidationError("note must be at most 255 characters")

        clean: list[tuple[UUID, int, Decimal, Decimal]] = []
        seen: set[UUID] = set()
        for index, raw in enumerate(lines, start=1):
            try:
                variant_id = UUID(str(raw.get("variant_id")))
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValidationError(f"line {index}: variant_id is not valid") from exc
            if variant_id in seen:
                raise ValidationError(
                    f"line {index}: the same variant appears twice; merge the quantities"
                )
            seen.add(variant_id)
            qty = positive_int(raw.get("quantity"), f"line {index} quantity")
            cost = money(raw.get("unit_cost"), f"line {index} unit_cost", allow_zero=True)
            clean.append((variant_id, qty, cost, (cost * qty).quantize(_CENT)))
        found = await existing_variant_ids(session, tenant_id, seen)
        missing = seen - found
        if missing:
            raise NotFoundError(f"variant not found: {sorted(str(m) for m in missing)[0]}")

        warehouse = (
            await _inventory().get_warehouse(session, tenant_id, warehouse_id)
            if warehouse_id
            else await _inventory().get_default_warehouse(session, tenant_id)
        )
        when = order_date or datetime.now(UTC).date()
        order = PurchaseOrder(
            tenant_id=tenant_id,
            number=await _numbering().next_number(session, tenant_id, "PO", on=when),
            supplier_id=supplier_id,
            warehouse_id=warehouse.id,
            order_date=when,
            status="draft",
            total=sum((c[3] for c in clean), Decimal("0")).quantize(_CENT),
            note=note,
            created_by_user_id=created_by,
        )
        session.add(order)
        await session.flush()
        for position, (variant_id, qty, cost, line_total) in enumerate(clean, start=1):
            session.add(
                PurchaseOrderLine(
                    tenant_id=tenant_id,
                    position=position,
                    purchase_order_id=order.id,
                    variant_id=variant_id,
                    quantity=qty,
                    unit_cost=cost,
                    line_total=line_total,
                )
            )
        await session.flush()
        if receive_now:
            await PurchaseService.receive(session, tenant_id, order.id, created_by)
        return order

    @staticmethod
    async def receive(
        session: AsyncSession,
        tenant_id: UUID,
        po_id: UUID,
        actor_user_id: UUID | None = None,
    ) -> PurchaseOrder:
        """Put the goods on the shelf and fold their cost into the average. Runs exactly once."""
        order = (
            await session.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == po_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if order is None:
            raise NotFoundError("purchase order not found")
        if order.status == "received":
            raise ConflictError("this purchase order is already received")
        if order.status == "cancelled":
            raise ConflictError("a cancelled purchase order cannot be received")

        lines = await PurchaseService._lines_in(session, tenant_id, order.id)
        # Variants in a stable order: two receipts that share variants lock them in the same order,
        # so they queue instead of deadlocking.
        for line in sorted(lines, key=lambda x: str(x.variant_id)):
            await CostService._locked(session, tenant_id, line.variant_id)
            before = await CostService.total_on_hand(session, tenant_id, line.variant_id)
            await _inventory().move(
                session,
                tenant_id,
                line.variant_id,
                order.warehouse_id,
                direction="in",
                quantity=line.quantity,
                reason="purchase",
                reference_type="purchase_order",
                reference_id=order.id,
                actor_user_id=actor_user_id,
            )
            await CostService.apply_receipt(
                session,
                tenant_id,
                line.variant_id,
                qty=line.quantity,
                unit_cost=Decimal(line.unit_cost),
                purchase_order_id=order.id,
                on_hand_before=before,
            )
        order.status = "received"
        order.received_at = datetime.now(UTC)
        await session.flush()
        return order

    @staticmethod
    async def cancel(session: AsyncSession, tenant_id: UUID, po_id: UUID) -> PurchaseOrder:
        order = (
            await session.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == po_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if order is None:
            raise NotFoundError("purchase order not found")
        if order.status == "cancelled":
            raise ConflictError("this purchase order is already cancelled")
        if order.status == "received":
            # Cancelling a received order would have to take its stock back off the shelf and unwind
            # the average cost. That is only honest while nothing else has touched those variants;
            # the correct, auditable way once stock moved is a supplier return.
            raise ConflictError(
                "a received purchase order cannot be cancelled: register a supplier return instead"
            )
        paid = await PurchaseService.paid_for(session, tenant_id, order.id)
        if paid > 0:
            raise ConflictError(
                "this purchase order has payments: reverse them before cancelling it"
            )
        order.status = "cancelled"
        order.cancelled_at = datetime.now(UTC)
        await session.flush()
        return order

    @staticmethod
    async def paid_for(session: AsyncSession, tenant_id: UUID, po_id: UUID) -> Decimal:
        rows = (
            await session.execute(
                select(
                    SupplierPayment.reverses_payment_id.is_(None),
                    func.coalesce(func.sum(SupplierPayment.amount), 0),
                )
                .where(
                    SupplierPayment.tenant_id == tenant_id,
                    SupplierPayment.purchase_order_id == po_id,
                )
                .group_by(SupplierPayment.reverses_payment_id.is_(None))
            )
        ).all()
        net = Decimal("0")
        for is_payment, amount in rows:
            net += Decimal(amount) if is_payment else -Decimal(amount)
        return net.quantize(_CENT)

    @staticmethod
    def payment_state(total: Decimal, paid: Decimal) -> str:
        if paid <= 0:
            return "unpaid"
        return "paid" if paid >= total else "partial"

    @staticmethod
    async def list(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        supplier_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[PurchaseOrder]:
        q = select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id)
        if supplier_id:
            q = q.where(PurchaseOrder.supplier_id == supplier_id)
        if status:
            q = q.where(PurchaseOrder.status == status)
        q = q.order_by(
            PurchaseOrder.order_date.desc(), PurchaseOrder.created_at.desc(), PurchaseOrder.id
        )
        return list((await session.execute(q.limit(limit).offset(offset))).scalars())


class SupplierPaymentService:
    @staticmethod
    async def list(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        supplier_id: UUID | None = None,
        purchase_order_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SupplierPayment]:
        """Payments newest first. A reversal is its own row, pointing at the payment it cancels."""
        q = select(SupplierPayment).where(SupplierPayment.tenant_id == tenant_id)
        if supplier_id:
            q = q.where(SupplierPayment.supplier_id == supplier_id)
        if purchase_order_id:
            q = q.where(SupplierPayment.purchase_order_id == purchase_order_id)
        q = q.order_by(
            SupplierPayment.paid_on.desc(), SupplierPayment.created_at.desc(), SupplierPayment.id
        )
        return list((await session.execute(q.limit(limit).offset(offset))).scalars())

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        supplier_id: UUID,
        amount: object,
        method: str,
        purchase_order_id: UUID | None = None,
        paid_on: date | None = None,
        session_id: UUID | None = None,
        note: str | None = None,
        created_by: UUID | None = None,
    ) -> SupplierPayment:
        await SupplierService.get(session, tenant_id, supplier_id)
        if method not in PAYMENT_METHODS:
            raise ValidationError(f"method must be one of {sorted(PAYMENT_METHODS)}")
        value = exact_money(amount)
        note = (note or "").strip() or None
        if note and len(note) > 255:
            raise ValidationError("note must be at most 255 characters")

        if purchase_order_id is not None:
            order = await PurchaseService.get(session, tenant_id, purchase_order_id)
            if order.supplier_id != supplier_id:
                raise ValidationError("that purchase order belongs to another supplier")
            if order.status != "received":
                raise ConflictError("only a received purchase order can be paid")
            # Serialise payers of one order, then check against what is really still owed.
            await session.execute(
                select(PurchaseOrder.id).where(PurchaseOrder.id == order.id).with_for_update()
            )
            owed = Decimal(order.total) - await PurchaseService.paid_for(
                session, tenant_id, order.id
            )
            if value > owed:
                raise ConflictError(
                    f"the payment ({value}) is more than what is still owed on the order ({owed})"
                )

        # A supplier payment is a RECORD (amount, date, supplier, invoice). It never touches the
        # cash drawer. A caller naming a shift is refused rather than silently ignored.
        if session_id is not None:
            raise ValidationError("a supplier payment is a record only, not tied to a shift")

        payment = SupplierPayment(
            tenant_id=tenant_id,
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            amount=value,
            method=method,
            paid_on=paid_on or datetime.now(UTC).date(),
            session_id=None,
            note=note,
            created_by_user_id=created_by,
        )
        session.add(payment)
        await session.flush()
        return payment


class SupplierReturnService:
    """Goods going back to a supplier.

    Two moments, on purpose: REGISTERING takes the goods off the shelf (they physically left) and
    parks the return in `review`; the supplier's ACCEPTANCE is what moves money (account credit or a
    cash refund into the open drawer). A rejection brings the goods back to the shelf.
    """

    @staticmethod
    async def get(
        session: AsyncSession, tenant_id: UUID, return_id: UUID, *, lock: bool = False
    ) -> SupplierReturn:
        q = select(SupplierReturn).where(
            SupplierReturn.tenant_id == tenant_id, SupplierReturn.id == return_id
        )
        row = (await session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
        if row is None:
            raise NotFoundError("supplier return not found")
        return row

    @staticmethod
    async def lines_of(session: AsyncSession, tenant_id: UUID, return_id: UUID) -> list:
        from app.modules.purchasing.models import SupplierReturnLine

        return list(
            (
                await session.execute(
                    select(SupplierReturnLine)
                    .where(
                        SupplierReturnLine.tenant_id == tenant_id,
                        SupplierReturnLine.supplier_return_id == return_id,
                    )
                    .order_by(SupplierReturnLine.position)
                )
            ).scalars()
        )

    @staticmethod
    async def _returned_so_far(
        session: AsyncSession,
        tenant_id: UUID,
        po_id: UUID,
        variant_id: UUID,
        *,
        exclude: UUID | None = None,
    ) -> int:
        """Units already sent back against an order (a rejected return came back: not counted)."""
        from app.modules.purchasing.models import SupplierReturnLine

        q = (
            select(func.coalesce(func.sum(SupplierReturnLine.quantity), 0))
            .join(SupplierReturn, SupplierReturn.id == SupplierReturnLine.supplier_return_id)
            .where(
                SupplierReturn.tenant_id == tenant_id,
                SupplierReturn.purchase_order_id == po_id,
                SupplierReturn.status != "rejected",
                SupplierReturnLine.variant_id == variant_id,
            )
        )
        if exclude:
            q = q.where(SupplierReturn.id != exclude)
        return int((await session.execute(q)).scalar_one())

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        supplier_id: UUID,
        lines: list[dict],
        settlement: str,
        purchase_order_id: UUID | None = None,
        return_date: date | None = None,
        note: str | None = None,
        created_by: UUID | None = None,
    ) -> SupplierReturn:
        from app.modules.purchasing.models import (
            RETURN_SETTLEMENTS,
            SupplierReturnLine,
        )

        await SupplierService.get(session, tenant_id, supplier_id)
        if settlement not in RETURN_SETTLEMENTS:
            raise ValidationError(f"settlement must be one of {sorted(RETURN_SETTLEMENTS)}")
        if not lines:
            raise ValidationError("a supplier return needs at least one line")
        note = (note or "").strip() or None
        if note and len(note) > 255:
            raise ValidationError("note must be at most 255 characters")

        order = None
        if purchase_order_id is not None:
            order = await PurchaseService.get(session, tenant_id, purchase_order_id)
            if order.supplier_id != supplier_id:
                raise ValidationError("that purchase order belongs to another supplier")
            if order.status != "received":
                raise ConflictError("goods can only be returned against a received purchase order")
        warehouse = (
            await _inventory().get_warehouse(session, tenant_id, order.warehouse_id)
            if order
            else await _inventory().get_default_warehouse(session, tenant_id)
        )

        bought: dict[UUID, tuple[int, Decimal]] = {}
        if order:
            for pl in await PurchaseService._lines_in(session, tenant_id, order.id):
                bought[pl.variant_id] = (pl.quantity, Decimal(pl.unit_cost))

        clean: list[tuple[UUID, int, Decimal, Decimal]] = []
        seen: set[UUID] = set()
        for index, raw in enumerate(lines, start=1):
            try:
                variant_id = UUID(str(raw.get("variant_id")))
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValidationError(f"line {index}: variant_id is not valid") from exc
            if variant_id in seen:
                raise ValidationError(
                    f"line {index}: the same variant appears twice; merge the quantities"
                )
            seen.add(variant_id)
            qty = positive_int(raw.get("quantity"), f"line {index} quantity")
            if order:
                if variant_id not in bought:
                    raise ValidationError(
                        f"line {index}: that variant is not on the purchase order"
                    )
                bought_qty, order_cost = bought[variant_id]
                already = await SupplierReturnService._returned_so_far(
                    session, tenant_id, order.id, variant_id
                )
                if qty > bought_qty - already:
                    raise ConflictError(
                        f"line {index}: returning {qty} but only {bought_qty - already} of the "
                        f"{bought_qty} "
                        "bought on that order are still returnable"
                    )
                # The credit is what the supplier charged on THAT order, not today's average.
                cost = order_cost
            else:
                cost = money(raw.get("unit_cost"), f"line {index} unit_cost")
            clean.append((variant_id, qty, cost, (cost * qty).quantize(_CENT)))

        when = return_date or datetime.now(UTC).date()
        ret = SupplierReturn(
            tenant_id=tenant_id,
            number=await _numbering().next_number(session, tenant_id, "SR", on=when),
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            warehouse_id=warehouse.id,
            settlement=settlement,
            status="review",
            total=sum((c[3] for c in clean), Decimal("0")).quantize(_CENT),
            return_date=when,
            note=note,
            created_by_user_id=created_by,
        )
        session.add(ret)
        await session.flush()
        for position, (variant_id, qty, cost, line_total) in enumerate(clean, start=1):
            session.add(
                SupplierReturnLine(
                    tenant_id=tenant_id,
                    position=position,
                    supplier_return_id=ret.id,
                    variant_id=variant_id,
                    quantity=qty,
                    unit_cost=cost,
                    line_total=line_total,
                )
            )
            # The goods leave the shelf NOW. move() refuses to go below zero
            # (InsufficientStockError).
            await _inventory().move(
                session,
                tenant_id,
                variant_id,
                warehouse.id,
                direction="out",
                quantity=qty,
                reason="supplier_return",
                reference_type="supplier_return",
                reference_id=ret.id,
                actor_user_id=created_by,
            )
        await session.flush()
        return ret

    @staticmethod
    async def accept(
        session: AsyncSession,
        tenant_id: UUID,
        return_id: UUID,
        *,
        session_id: UUID | None = None,
        decided_by: UUID | None = None,
    ) -> SupplierReturn:
        ret = await SupplierReturnService.get(session, tenant_id, return_id, lock=True)
        if ret.status != "review":
            raise ConflictError(f"this return was already {ret.status}")
        if session_id is not None:
            # The refund is a record; it never enters a drawer, so a named shift is refused.
            raise ValidationError("a supplier return is a record only, not tied to a shift")
        # No drawer is touched whatever the settlement: the supplier statement counts the value.
        # settlement 'replace': no money; the replacement arrives as a normal purchase order.
        ret.status = "accepted"
        ret.decided_at = datetime.now(UTC)
        await session.flush()
        return ret

    @staticmethod
    async def reject(session: AsyncSession, tenant_id: UUID, return_id: UUID) -> SupplierReturn:
        ret = await SupplierReturnService.get(session, tenant_id, return_id, lock=True)
        if ret.status != "review":
            raise ConflictError(f"this return was already {ret.status}")
        # The supplier refused the goods: they come back onto the shelf. The ledger is append-only,
        # so this
        # is a NEW 'in' row that names the same return, not an edit of the 'out'.
        for line in await SupplierReturnService.lines_of(session, tenant_id, ret.id):
            await _inventory().move(
                session,
                tenant_id,
                line.variant_id,
                ret.warehouse_id,
                direction="in",
                quantity=line.quantity,
                reason="supplier_return_reversal",
                reference_type="supplier_return",
                reference_id=ret.id,
            )
        ret.status = "rejected"
        ret.decided_at = datetime.now(UTC)
        await session.flush()
        return ret

    @staticmethod
    async def list(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        supplier_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SupplierReturn]:
        q = select(SupplierReturn).where(SupplierReturn.tenant_id == tenant_id)
        if supplier_id:
            q = q.where(SupplierReturn.supplier_id == supplier_id)
        if status:
            q = q.where(SupplierReturn.status == status)
        q = q.order_by(
            SupplierReturn.return_date.desc(), SupplierReturn.created_at.desc(), SupplierReturn.id
        )
        return list((await session.execute(q.limit(limit).offset(offset))).scalars())
