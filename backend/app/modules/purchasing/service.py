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
  * A payment is a record only: it never touches a drawer or a shift.
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
    GOODS_RECEIPT_CONDITIONS,
    PAYMENT_METHODS,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierPayment,
    SupplierReturn,
    VariantCost,
    VariantCostHistory,
)
from app.modules.settings.service import SettingsService


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
        partial_received = (
            await session.execute(
                select(
                    func.coalesce(
                        func.sum(PurchaseOrderLine.quantity_received * PurchaseOrderLine.unit_cost),
                        0,
                    ),
                    func.count(func.distinct(PurchaseOrder.id)),
                    func.max(PurchaseOrder.order_date),
                )
                .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
                .where(
                    PurchaseOrder.tenant_id == tenant_id,
                    PurchaseOrder.supplier_id == supplier_id,
                    PurchaseOrder.status == "partially_received",
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
                    PurchaseOrder.status.in_(["received", "partially_received"]),
                )
            )
        ).scalar_one()
        dates = [d for d in (received[2], partial_received[2]) if d is not None]
        last_date = max(dates) if dates else None
        total = (Decimal(received[0]) + Decimal(partial_received[0])).quantize(_CENT)
        orders_cnt = int(received[1]) + int(partial_received[1])
        paid = paid.quantize(_CENT)
        credit = Decimal(credit).quantize(_CENT)
        return {
            "total_supplied": total,
            "orders_count": orders_cnt,
            "last_order_date": last_date,
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

        # Wire purchasing settings: when approval is not required (and the total
        # is below the threshold if one is set), auto-approve the PO so it is ready
        # to send. Otherwise it stays in "draft" for a manager to approve.
        approval_required = await SettingsService(session, tenant_id).value(
            "purchasing.approval_required"
        )
        threshold = await SettingsService(session, tenant_id).value("purchasing.approval_threshold")
        centralized = await SettingsService(session, tenant_id).value("purchasing.centralized")
        if centralized:
            # Centralized purchasing: branches do not create their own POs.
            # The PO is marked as centrally managed via the note field.
            order.note = (order.note or "") + " [centralized]"
            await session.flush()
            # §settings: branch.allow_independent_purchasing — even under
            # centralized purchasing, a branch with this override may create
            # its own POs. Without it, the PO stays centralized.
            allow_independent = await SettingsService(session, tenant_id).value(
                "branch.allow_independent_purchasing"
            )
            if not allow_independent:
                order.note = (order.note or "").replace(
                    " [centralized]", ""
                ) + " [requires HQ approval]"
        if not approval_required and (threshold == 0 or order.total < threshold):
            order.status = "approved"
            order.approved_at = datetime.now(UTC)
            order.approved_by_user_id = created_by
            await session.flush()

        if receive_now:
            await PurchaseService.receive(session, tenant_id, order.id, created_by)
        return order

    @staticmethod
    async def create_from_reorder_suggestion(
        session: AsyncSession,
        tenant_id: UUID,
        suggestion_id: UUID,
        *,
        user_id: UUID | None = None,
        unit_cost: str | None = None,
    ) -> PurchaseOrder:
        """Approve an open reorder suggestion and create its draft PurchaseOrder (D9)."""
        replenish = _inventory().ReplenishmentService
        sugg = await replenish.approve_suggestion(
            session, tenant_id, suggestion_id, user_id=user_id
        )
        policy = await replenish.get_policy(
            session, tenant_id, variant_id=sugg.variant_id, warehouse_id=sugg.warehouse_id
        )
        if not policy or not policy.preferred_supplier_id:
            raise ValidationError(
                "cannot create purchase order: policy has no preferred_supplier_id"
            )

        cost_str = unit_cost or "0.00"
        return await PurchaseService.create(
            session,
            tenant_id,
            supplier_id=policy.preferred_supplier_id,
            warehouse_id=sugg.warehouse_id,
            lines=[
                {
                    "variant_id": str(sugg.variant_id),
                    "quantity": sugg.suggested_quantity,
                    "unit_cost": cost_str,
                }
            ],
            note=f"Replenishment from suggestion {sugg.id}",
            created_by=user_id,
        )

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
        # When quality check on receipt is enabled, a goods receipt must be
        # posted through the quality inspection flow, not applied directly here.
        quality_required = await SettingsService(session, tenant_id).value(
            "inventory.quality_check_on_receipt"
        )
        if quality_required:
            raise ValidationError(
                "quality check on receipt is enabled; receive through a goods receipt "
                "with a quality inspection instead"
            )
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
            # A receipt without its FIFO layer would later sell at the wrong cost, so a failure
            # here must fail the whole receipt, not be swallowed.
            await _inventory().ValuationService.create_cost_layer(
                session,
                tenant_id,
                variant_id=line.variant_id,
                warehouse_id=order.warehouse_id,
                quantity=line.quantity,
                unit_cost=Decimal(line.unit_cost),
                source_type="purchase_order",
                source_id=order.id,
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

        # Paying a supplier in cash out of the till must leave the drawer ledger in the SAME
        # transaction, or the close reports a shortage equal to the payment and nobody can explain
        # it. Only cash touches the drawer: a card or bank transfer names no shift.
        drawer_session = None
        if session_id is not None:
            if method != "cash":
                raise ValidationError(
                    "only a cash payment comes out of a cash drawer: "
                    f"record this {method} payment without a shift"
                )
            drawer_session = await _open_drawer(session, tenant_id, session_id)

        payment = SupplierPayment(
            tenant_id=tenant_id,
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
            amount=value,
            method=method,
            paid_on=paid_on or datetime.now(UTC).date(),
            session_id=drawer_session.id if drawer_session is not None else None,
            note=note,
            created_by_user_id=created_by,
        )
        session.add(payment)
        await session.flush()
        if drawer_session is not None:
            await _drawer_row(
                session,
                tenant_id,
                drawer_session.id,
                direction="out",
                amount=value,
                reference_type="supplier_payment",
                reference_id=payment.id,
                notes=(note or "supplier payment")[:255],
                actor_user_id=created_by,
            )
            await session.flush()
        return payment


class SupplierReturnService:
    """Goods going back to a supplier.

    Two moments, on purpose: REGISTERING takes the goods off the shelf (they physically left) and
    parks the return in `review`; the supplier's ACCEPTANCE records its value on the supplier
    statement (credit, cash or replacement) without touching a drawer. A rejection brings the
    goods back to the shelf.
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
        # A supplier who hands the money back over the counter puts it IN the drawer, so the
        # ledger gets an `in` row in the same transaction. 'credit' and 'replace' move no money:
        # the supplier statement carries the value, and a replacement arrives as a purchase order.
        drawer_session = None
        if session_id is not None:
            if str(ret.settlement) != "cash":
                raise ValidationError(
                    "only a cash settlement of a supplier return goes into a cash drawer: "
                    f"this return settles by {ret.settlement}"
                )
            drawer_session = await _open_drawer(session, tenant_id, session_id)
        ret.status = "accepted"
        ret.decided_at = datetime.now(UTC)
        await session.flush()
        if drawer_session is not None:
            await _drawer_row(
                session,
                tenant_id,
                drawer_session.id,
                direction="in",
                amount=exact_money(ret.total),
                reference_type="supplier_return",
                reference_id=ret.id,
                notes="cash refund from supplier"[:255],
                actor_user_id=decided_by,
            )
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


def _clean_batch(raw: dict[str, Any], idx: int) -> tuple[str | None, datetime | None]:
    """The batch a receipt line names, validated. No code means no batch: nothing else changes."""
    code = str(raw.get("lot_code") or "").strip()[:64] or None
    expires = raw.get("lot_expires_at")
    if expires in (None, ""):
        return code, None
    if code is None:
        raise ValidationError(f"line {idx}: lot_expires_at needs a lot_code")
    try:
        when = expires if isinstance(expires, datetime) else datetime.fromisoformat(str(expires))
    except ValueError as exc:
        raise ValidationError(f"line {idx}: lot_expires_at is not a valid date") from exc
    return code, when if when.tzinfo else when.replace(tzinfo=UTC)


async def _batch_for(
    session: AsyncSession, tenant_id: UUID, gr_line: GoodsReceiptLine
) -> UUID | None:
    """The batch this line names (found or made by inventory), or None when it names none."""
    if not gr_line.lot_code:
        return None
    return await _inventory().find_or_create_lot(
        session,
        tenant_id,
        variant_id=gr_line.variant_id,
        lot_code=gr_line.lot_code,
        expires_at=gr_line.lot_expires_at,
    )


class GoodsReceiptService:
    """Create, post, and cancel goods receipts (partial receiving for POs, D5).

    A purchase order says what was ORDERED. A goods receipt says what ARRIVED.
    Only a posted receipt writes stock (`in` / `purchase` movements).

    Receipt lines carry a `condition` (good | quarantine | reject):
      * good        → `in` movement → sellable stock
      * quarantine  → `in` movement + `quarantined` counter bump → not sellable
      * reject      → NO movement → never entered inventory
    """

    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        purchase_order_id: UUID,
        lines: list[dict[str, Any]],
        note: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> GoodsReceipt:
        order = (
            await session.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == purchase_order_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if order is None:
            raise NotFoundError("purchase order not found")
        if order.status in ("cancelled",):
            raise ConflictError("cannot receive against a cancelled purchase order")
        if order.status == "received":
            raise ConflictError("this purchase order is already fully received")

        if not lines:
            raise ValidationError("a goods receipt needs at least one line")
        if len(lines) > 200:
            raise ValidationError("a goods receipt is limited to 200 lines")

        po_lines = list(
            (
                await session.execute(
                    select(PurchaseOrderLine).where(
                        PurchaseOrderLine.tenant_id == tenant_id,
                        PurchaseOrderLine.purchase_order_id == purchase_order_id,
                    )
                )
            ).scalars()
        )
        po_line_map: dict[UUID, PurchaseOrderLine] = {pl.id: pl for pl in po_lines}

        over_receipt_allowed = bool(
            await SettingsService(session, tenant_id).value("purchasing.allow_over_receipt")
        )
        partial_allowed = bool(
            await SettingsService(session, tenant_id).value("purchasing.allow_partial_receipt")
        )

        clean: list[dict] = []
        seen_pol: set[UUID] = set()
        for idx, raw in enumerate(lines, start=1):
            try:
                pol_id = UUID(str(raw.get("purchase_order_line_id")))
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValidationError(f"line {idx}: purchase_order_line_id is not valid") from exc

            if pol_id in seen_pol:
                raise ValidationError(
                    f"line {idx}: duplicate purchase_order_line_id; "
                    "merge the quantities into one line"
                )
            seen_pol.add(pol_id)

            if pol_id not in po_line_map:
                raise NotFoundError(
                    f"line {idx}: purchase_order_line_id {pol_id} "
                    "does not belong to this purchase order"
                )
            po_line = po_line_map[pol_id]

            try:
                variant_id = UUID(str(raw.get("variant_id")))
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValidationError(f"line {idx}: variant_id is not valid") from exc

            if variant_id != po_line.variant_id:
                raise ValidationError(
                    f"line {idx}: variant_id does not match the purchase order line"
                )

            qty = positive_int(raw.get("quantity"), f"line {idx} quantity")
            unit_cost = money(raw.get("unit_cost"), f"line {idx} unit_cost", allow_zero=True)
            condition = str(raw.get("condition", "good")).lower()
            if condition not in GOODS_RECEIPT_CONDITIONS:
                raise ValidationError(
                    f"line {idx}: condition must be one of {sorted(GOODS_RECEIPT_CONDITIONS)}"
                )

            lot_code, lot_expires_at = _clean_batch(raw, idx)

            already = po_line.quantity_received or 0
            remaining = po_line.quantity - already
            if qty > remaining and not over_receipt_allowed:
                raise ValidationError(
                    f"line {idx}: receiving {qty} but only {remaining} remain on the PO line "
                    f"(ordered {po_line.quantity}, already received {already})"
                )

            if qty < remaining and not partial_allowed:
                raise ValidationError(
                    f"line {idx}: receiving {qty} of the {remaining} still due, but "
                    "purchasing.allow_partial_receipt is off: receive the full remaining quantity"
                )

            line_total = (unit_cost * qty).quantize(Decimal("0.0001"))
            clean.append(
                {
                    "purchase_order_line_id": pol_id,
                    "variant_id": variant_id,
                    "quantity": qty,
                    "unit_cost": unit_cost,
                    "line_total": line_total,
                    "condition": condition,
                    "lot_code": lot_code,
                    "lot_expires_at": lot_expires_at,
                }
            )

        note_clean = (note or "").strip()[:255] or None
        receipt = GoodsReceipt(
            tenant_id=tenant_id,
            number=await _numbering().next_number(
                session, tenant_id, "GR", on=datetime.now(UTC).date()
            ),
            purchase_order_id=purchase_order_id,
            warehouse_id=order.warehouse_id,
            status="draft",
            note=note_clean,
        )
        session.add(receipt)
        await session.flush()

        for position, cl in enumerate(clean, start=1):
            session.add(
                GoodsReceiptLine(
                    tenant_id=tenant_id,
                    goods_receipt_id=receipt.id,
                    purchase_order_line_id=cl["purchase_order_line_id"],
                    variant_id=cl["variant_id"],
                    quantity=cl["quantity"],
                    unit_cost=cl["unit_cost"],
                    line_total=cl["line_total"],
                    position=position,
                    condition=cl["condition"],
                    lot_code=cl["lot_code"],
                    lot_expires_at=cl["lot_expires_at"],
                )
            )
        await session.flush()
        return receipt

    @staticmethod
    async def post(
        session: AsyncSession,
        tenant_id: UUID,
        receipt_id: UUID,
        *,
        actor_user_id: UUID | None = None,
    ) -> GoodsReceipt:
        receipt = (
            await session.execute(
                select(GoodsReceipt)
                .where(GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.id == receipt_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError("goods receipt not found")
        if receipt.status == "posted":
            raise ConflictError("this goods receipt is already posted")
        if receipt.status in ("rejected", "cancelled"):
            raise ConflictError(f"cannot post a {receipt.status} goods receipt")

        order = (
            await session.execute(
                select(PurchaseOrder)
                .where(
                    PurchaseOrder.tenant_id == tenant_id,
                    PurchaseOrder.id == receipt.purchase_order_id,
                )
                .with_for_update()
            )
        ).scalar_one()

        gr_lines = list(
            (
                await session.execute(
                    select(GoodsReceiptLine)
                    .where(
                        GoodsReceiptLine.tenant_id == tenant_id,
                        GoodsReceiptLine.goods_receipt_id == receipt_id,
                    )
                    .order_by(GoodsReceiptLine.position)
                )
            ).scalars()
        )

        for gr_line in sorted(gr_lines, key=lambda x: str(x.variant_id)):
            if gr_line.condition == "reject":
                po_line = (
                    await session.execute(
                        select(PurchaseOrderLine)
                        .where(
                            PurchaseOrderLine.tenant_id == tenant_id,
                            PurchaseOrderLine.id == gr_line.purchase_order_line_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one()
                po_line.quantity_received = (po_line.quantity_received or 0) + gr_line.quantity
                continue

            await CostService._locked(session, tenant_id, gr_line.variant_id)
            before = await CostService.total_on_hand(session, tenant_id, gr_line.variant_id)

            await _inventory().move(
                session,
                tenant_id,
                gr_line.variant_id,
                receipt.warehouse_id,
                direction="in",
                quantity=gr_line.quantity,
                reason="purchase",
                reference_type="goods_receipt",
                reference_id=receipt.id,
                actor_user_id=actor_user_id,
            )

            if gr_line.condition == "quarantine":
                bal = await _inventory()._locked_balance(
                    session, tenant_id, gr_line.variant_id, receipt.warehouse_id
                )
                bal.quarantined = (bal.quarantined or 0) + gr_line.quantity

            await CostService.apply_receipt(
                session,
                tenant_id,
                gr_line.variant_id,
                qty=gr_line.quantity,
                unit_cost=Decimal(gr_line.unit_cost),
                purchase_order_id=order.id,
                on_hand_before=before,
            )

            await _inventory().ValuationService.create_cost_layer(
                session,
                tenant_id,
                variant_id=gr_line.variant_id,
                warehouse_id=receipt.warehouse_id,
                quantity=gr_line.quantity,
                unit_cost=Decimal(gr_line.unit_cost),
                source_type="goods_receipt",
                source_id=receipt.id,
                lot_id=await _batch_for(session, tenant_id, gr_line),
            )

            po_line = (
                await session.execute(
                    select(PurchaseOrderLine)
                    .where(
                        PurchaseOrderLine.tenant_id == tenant_id,
                        PurchaseOrderLine.id == gr_line.purchase_order_line_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            po_line.quantity_received = (po_line.quantity_received or 0) + gr_line.quantity

        all_po_lines = list(
            (
                await session.execute(
                    select(PurchaseOrderLine).where(
                        PurchaseOrderLine.tenant_id == tenant_id,
                        PurchaseOrderLine.purchase_order_id == order.id,
                    )
                )
            ).scalars()
        )
        total_ordered = sum(pl.quantity for pl in all_po_lines)
        total_received = sum(pl.quantity_received or 0 for pl in all_po_lines)

        if total_received >= total_ordered:
            order.status = "received"
            order.received_at = datetime.now(UTC)
        elif total_received > 0:
            order.status = "partially_received"
            order.received_at = None

        receipt.status = "posted"
        receipt.received_at = datetime.now(UTC)
        receipt.received_by_user_id = actor_user_id

        await session.flush()
        return receipt

    @staticmethod
    async def cancel(
        session: AsyncSession,
        tenant_id: UUID,
        receipt_id: UUID,
    ) -> GoodsReceipt:
        receipt = (
            await session.execute(
                select(GoodsReceipt)
                .where(GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.id == receipt_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError("goods receipt not found")
        if receipt.status == "posted":
            raise ConflictError("a posted goods receipt cannot be cancelled")
        if receipt.status == "cancelled":
            raise ConflictError("this goods receipt is already cancelled")
        receipt.status = "cancelled"
        await session.flush()
        return receipt

    @staticmethod
    async def get(session: AsyncSession, tenant_id: UUID, receipt_id: UUID) -> GoodsReceipt:
        receipt = (
            await session.execute(
                select(GoodsReceipt).where(
                    GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.id == receipt_id
                )
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise NotFoundError("goods receipt not found")
        return receipt

    @staticmethod
    async def lines_of(
        session: AsyncSession, tenant_id: UUID, receipt_id: UUID
    ) -> list[GoodsReceiptLine]:
        return list(
            (
                await session.execute(
                    select(GoodsReceiptLine)
                    .where(
                        GoodsReceiptLine.tenant_id == tenant_id,
                        GoodsReceiptLine.goods_receipt_id == receipt_id,
                    )
                    .order_by(GoodsReceiptLine.position)
                )
            ).scalars()
        )

    @staticmethod
    async def list_for_po(
        session: AsyncSession, tenant_id: UUID, po_id: UUID
    ) -> list[GoodsReceipt]:
        return list(
            (
                await session.execute(
                    select(GoodsReceipt)
                    .where(
                        GoodsReceipt.tenant_id == tenant_id,
                        GoodsReceipt.purchase_order_id == po_id,
                    )
                    .order_by(GoodsReceipt.created_at.desc())
                )
            ).scalars()
        )


async def _open_drawer(session: AsyncSession, tenant_id: UUID, session_id: UUID):
    """The OPEN till money is about to move through, or a refusal.

    Locked, because two payments out of one drawer must not both read the same expected cash.
    """
    from app.modules.pos.models import PosSession

    pos_session = (
        await session.execute(
            select(PosSession)
            .where(PosSession.tenant_id == tenant_id, PosSession.id == session_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if pos_session is None:
        raise NotFoundError("pos session not found")
    if pos_session.status != "OPEN":
        raise ConflictError("this shift is closed; money cannot move through it")
    return pos_session


async def _drawer_row(
    session: AsyncSession,
    tenant_id: UUID,
    session_id: UUID,
    *,
    direction: str,
    amount: object,
    reference_type: str,
    reference_id: UUID,
    notes: str,
    actor_user_id: UUID | None,
) -> None:
    """One row on the drawer ledger, naming the document it belongs to.

    A row is never edited or deleted: a mistake is corrected by its own reversing row, so the
    drawer's history explains itself.
    """
    from app.modules.pos.models import PosCashMovement

    session.add(
        PosCashMovement(
            tenant_id=tenant_id,
            session_id=session_id,
            direction=direction,
            reason="pay_out" if direction == "out" else "pay_in",
            amount=exact_money(amount),
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            created_by_user_id=actor_user_id,
        )
    )
