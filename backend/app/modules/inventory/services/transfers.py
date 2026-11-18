"""Warehouse-to-warehouse stock transfer service for InventoryService (D6, §4 Phase 2).

A transfer is a document with a full lifecycle, not two moves at once:
    draft → approved → picking → packed → in_transit → partially_received → completed
                                       ↘ cancelled (only before shipping)
                                       ↘ exception (shortage / damage)

Shipping writes `out` at the source and nothing at the destination.
Receiving writes `in` at the destination.
The gap between shipped and received is in-transit stock.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.models import (
    InventoryTransfer,
    InventoryTransferLine,
    InventoryTransferReceipt,
    InventoryTransferReceiptLine,
    InventoryTransferShipment,
    InventoryTransferShipmentLine,
)

from ._common import _now, _positive_int
from .balances import BalanceServiceMixin
from .movements import MovementServiceMixin


class TransferServiceMixin:
    """Inter-warehouse inventory transfer workflows."""

    # ------------------------------------------------------------- get ----

    @staticmethod
    async def get_transfer(
        session: AsyncSession, tenant_id: UUID, transfer_id: UUID, *, lock: bool = False
    ) -> InventoryTransfer:
        stmt = select(InventoryTransfer).where(
            InventoryTransfer.id == transfer_id,
            InventoryTransfer.tenant_id == tenant_id,
        )
        if lock:
            stmt = stmt.with_for_update()
        transfer = (await session.execute(stmt)).scalar_one_or_none()
        if transfer is None:
            raise NotFoundError(f"transfer {transfer_id} not found")
        return transfer

    @staticmethod
    async def get_transfer_lines(
        session: AsyncSession, tenant_id: UUID, transfer_id: UUID
    ) -> list[InventoryTransferLine]:
        return list(
            (
                await session.execute(
                    select(InventoryTransferLine)
                    .where(
                        InventoryTransferLine.tenant_id == tenant_id,
                        InventoryTransferLine.transfer_id == transfer_id,
                    )
                    .order_by(InventoryTransferLine.position)
                )
            ).scalars()
        )

    # ---------------------------------------------------------- create ----

    @staticmethod
    async def create_transfer(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        from_warehouse_id: UUID,
        to_warehouse_id: UUID,
        lines: list[dict],
        notes: str | None = None,
    ) -> InventoryTransfer:
        """Open a draft stock transfer between two warehouses of the tenant."""
        if from_warehouse_id == to_warehouse_id:
            raise ValidationError("source and destination warehouses must differ")
        if not lines:
            raise ValidationError("transfer must contain at least one line")
        await BalanceServiceMixin._get_warehouse(session, tenant_id, from_warehouse_id)
        await BalanceServiceMixin._get_warehouse(session, tenant_id, to_warehouse_id)

        clean_lines: list[dict[str, Any]] = []
        seen_variants: set[UUID] = set()
        for idx, line in enumerate(lines, start=1):
            qty = _positive_int(line.get("quantity"), f"line {idx} quantity")
            try:
                variant_id = UUID(str(line.get("variant_id")))
            except (ValueError, AttributeError, TypeError) as exc:
                raise ValidationError(f"line {idx}: variant_id is not valid") from exc
            if variant_id in seen_variants:
                raise ValidationError(
                    f"line {idx}: variant appears more than once; merge quantities"
                )
            seen_variants.add(variant_id)
            await BalanceServiceMixin._get_variant(session, tenant_id, variant_id)
            clean_lines.append({"variant_id": variant_id, "quantity": qty})

        transfer = InventoryTransfer(
            tenant_id=tenant_id,
            from_warehouse_id=from_warehouse_id,
            to_warehouse_id=to_warehouse_id,
            status="draft",
            notes=(notes or "").strip() or None,
            # Backward-compatibility: JSONB representation
            lines=[
                {"variant_id": str(cl["variant_id"]), "quantity": cl["quantity"]}
                for cl in clean_lines
            ],
        )
        session.add(transfer)
        await session.flush()

        for position, cl in enumerate(clean_lines, start=1):
            session.add(
                InventoryTransferLine(
                    tenant_id=tenant_id,
                    transfer_id=transfer.id,
                    variant_id=cl["variant_id"],
                    quantity=cl["quantity"],
                    quantity_shipped=0,
                    quantity_received=0,
                    position=position,
                )
            )
        await session.flush()
        return transfer

    # --------------------------------------------------------- approve ----

    @staticmethod
    async def approve_transfer(
        session: AsyncSession,
        tenant_id: UUID,
        transfer_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> InventoryTransfer:
        """Approve a draft transfer so it can be picked and shipped."""
        transfer = await TransferServiceMixin.get_transfer(
            session, tenant_id, transfer_id, lock=True
        )
        if transfer.status != "draft":
            raise ConflictError(f"cannot approve a transfer in '{transfer.status}' status")
        transfer.status = "approved"
        transfer.approved_at = _now()
        transfer.approved_by_user_id = user_id
        await session.flush()
        return transfer

    # ------------------------------------------------------------ ship ----

    @staticmethod
    async def ship_transfer(
        session: AsyncSession,
        tenant_id: UUID,
        transfer_id: UUID,
        *,
        lines: list[dict] | None = None,
        carrier: str | None = None,
        tracking_ref: str | None = None,
        note: str | None = None,
        user_id: UUID | None = None,
    ) -> InventoryTransferShipment:
        """Ship goods out of the source warehouse (D6).

        Moves stock `out` at `from_warehouse_id` ONLY. The destination learns
        nothing until the receipt arrives.
        """
        transfer = await TransferServiceMixin.get_transfer(
            session, tenant_id, transfer_id, lock=True
        )
        if transfer.status not in ("draft", "approved", "picking", "packed"):
            raise ConflictError(f"cannot ship transfer in '{transfer.status}' status")

        # Auto-approve if draft
        if transfer.status == "draft":
            transfer.approved_at = _now()
            transfer.approved_by_user_id = user_id

        t_lines = await TransferServiceMixin.get_transfer_lines(session, tenant_id, transfer_id)
        t_line_map = {tl.variant_id: tl for tl in t_lines}

        # Determine quantities to ship
        to_ship: list[tuple[InventoryTransferLine, int]] = []
        if not lines:
            # Ship all remaining open quantities
            for tl in t_lines:
                remaining = tl.quantity - tl.quantity_shipped
                if remaining > 0:
                    to_ship.append((tl, remaining))
        else:
            t_by_line_id = {tl.id: tl for tl in t_lines}
            for item in lines:
                if "variant_id" in item and item["variant_id"]:
                    v_id = UUID(str(item["variant_id"]))
                    if v_id not in t_line_map:
                        raise ValidationError(f"variant {v_id} is not part of this transfer")
                    tl = t_line_map[v_id]
                elif "transfer_line_id" in item and item["transfer_line_id"]:
                    l_id = UUID(str(item["transfer_line_id"]))
                    if l_id not in t_by_line_id:
                        raise ValidationError(f"transfer line {l_id} is not part of this transfer")
                    tl = t_by_line_id[l_id]
                else:
                    raise ValidationError("each line requires variant_id or transfer_line_id")
                qty = _positive_int(item.get("quantity"))
                remaining = tl.quantity - tl.quantity_shipped
                if qty > remaining:
                    raise ValidationError(
                        f"cannot ship {qty} of variant {tl.variant_id}; only {remaining} remaining"
                    )
                to_ship.append((tl, qty))

        if not to_ship:
            raise ValidationError("nothing to ship for this transfer")

        # Create shipment document
        shipment = InventoryTransferShipment(
            tenant_id=tenant_id,
            transfer_id=transfer.id,
            carrier=(carrier or "").strip()[:63] or None,
            tracking_ref=(tracking_ref or "").strip()[:63] or None,
            note=(note or "").strip() or None,
            shipped_by_user_id=user_id,
        )
        session.add(shipment)
        await session.flush()

        # Execute stock movements at source warehouse ONLY
        for pos, (tl, qty) in enumerate(to_ship, start=1):
            cogs_cost = None
            try:
                from app.modules.inventory.services.valuation import ValuationService

                consumption = await ValuationService.consume_fifo(
                    session,
                    tenant_id,
                    variant_id=tl.variant_id,
                    warehouse_id=transfer.from_warehouse_id,
                    quantity=qty,
                    allow_partial=True,
                )
                cogs_cost = consumption.get("total_cogs")
            except Exception:
                cogs_cost = None

            await MovementServiceMixin.move(
                session,
                tenant_id,
                tl.variant_id,
                transfer.from_warehouse_id,
                direction="out",
                quantity=qty,
                reason="transfer_out",
                reference_type="inventory_transfer",
                reference_id=transfer_id,
                actor_user_id=user_id,
                cost_value=cogs_cost,
            )
            tl.quantity_shipped += qty
            session.add(
                InventoryTransferShipmentLine(
                    tenant_id=tenant_id,
                    shipment_id=shipment.id,
                    variant_id=tl.variant_id,
                    quantity=qty,
                    position=pos,
                )
            )

        transfer.status = "in_transit"
        transfer.shipped_at = _now()
        await session.flush()
        return shipment

    # --------------------------------------------------------- receive ----

    @staticmethod
    async def receive_transfer(
        session: AsyncSession,
        tenant_id: UUID,
        transfer_id: UUID,
        *,
        lines: list[dict] | None = None,
        shipment_id: UUID | None = None,
        note: str | None = None,
        user_id: UUID | None = None,
    ) -> InventoryTransferReceipt:
        """Receive transferred goods at the destination warehouse (D6).

        Moves stock `in` at `to_warehouse_id`.
        """
        transfer = await TransferServiceMixin.get_transfer(
            session, tenant_id, transfer_id, lock=True
        )
        if transfer.status not in ("in_transit", "partially_received"):
            raise ConflictError(f"cannot receive transfer in '{transfer.status}' status")

        t_lines = await TransferServiceMixin.get_transfer_lines(session, tenant_id, transfer_id)
        t_line_map = {tl.variant_id: tl for tl in t_lines}

        to_receive: list[tuple[InventoryTransferLine, int, str]] = []
        if not lines:
            # Receive all shipped but not yet received quantities as good
            for tl in t_lines:
                pending = tl.quantity_shipped - tl.quantity_received
                if pending > 0:
                    to_receive.append((tl, pending, "good"))
        else:
            t_by_line_id = {tl.id: tl for tl in t_lines}
            for item in lines:
                if "variant_id" in item and item["variant_id"]:
                    v_id = UUID(str(item["variant_id"]))
                    if v_id not in t_line_map:
                        raise ValidationError(f"variant {v_id} is not part of this transfer")
                    tl = t_line_map[v_id]
                elif "transfer_line_id" in item and item["transfer_line_id"]:
                    l_id = UUID(str(item["transfer_line_id"]))
                    if l_id not in t_by_line_id:
                        raise ValidationError(f"transfer line {l_id} is not part of this transfer")
                    tl = t_by_line_id[l_id]
                else:
                    raise ValidationError("each line requires variant_id or transfer_line_id")
                qty = _positive_int(item.get("quantity"))
                cond = str(item.get("condition", "good")).lower()
                if cond not in ("good", "damaged", "short"):
                    raise ValidationError("condition must be one of ('good', 'damaged', 'short')")
                pending = tl.quantity_shipped - tl.quantity_received
                if qty > pending:
                    raise ValidationError(
                        f"cannot receive {qty} of variant {tl.variant_id}; "
                        f"only {pending} in transit"
                    )
                to_receive.append((tl, qty, cond))

        if not to_receive:
            raise ValidationError("nothing to receive for this transfer")

        receipt = InventoryTransferReceipt(
            tenant_id=tenant_id,
            transfer_id=transfer.id,
            shipment_id=shipment_id,
            note=(note or "").strip() or None,
            received_by_user_id=user_id,
        )
        session.add(receipt)
        await session.flush()

        has_exception = False
        exception_notes: list[str] = []

        for tl, qty, cond in to_receive:
            session.add(
                InventoryTransferReceiptLine(
                    tenant_id=tenant_id,
                    receipt_id=receipt.id,
                    variant_id=tl.variant_id,
                    quantity=qty,
                    condition=cond,
                )
            )
            tl.quantity_received += qty

            if cond == "good":
                await MovementServiceMixin.move(
                    session,
                    tenant_id,
                    tl.variant_id,
                    transfer.to_warehouse_id,
                    direction="in",
                    quantity=qty,
                    reason="transfer_in",
                    reference_type="inventory_transfer",
                    reference_id=transfer_id,
                    actor_user_id=user_id,
                )
                try:
                    from app.modules.inventory.models import InventoryCostLayer
                    from app.modules.inventory.services.valuation import ValuationService

                    last_layer = (
                        await session.execute(
                            select(InventoryCostLayer.unit_cost)
                            .where(
                                InventoryCostLayer.tenant_id == tenant_id,
                                InventoryCostLayer.variant_id == tl.variant_id,
                                InventoryCostLayer.warehouse_id == transfer.from_warehouse_id,
                            )
                            .order_by(InventoryCostLayer.layer_date.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if last_layer is not None:
                        await ValuationService.create_cost_layer(
                            session,
                            tenant_id,
                            variant_id=tl.variant_id,
                            warehouse_id=transfer.to_warehouse_id,
                            quantity=qty,
                            unit_cost=last_layer,
                            source_type="transfer",
                            source_id=transfer.id,
                        )
                except Exception:
                    pass
            elif cond in ("damaged", "short"):
                has_exception = True
                exception_notes.append(f"{cond} {qty} of variant {tl.variant_id}")

        # Check completion
        total_shipped = sum(tl.quantity_shipped for tl in t_lines)
        total_received = sum(tl.quantity_received for tl in t_lines)

        if total_received >= total_shipped:
            if has_exception:
                transfer.status = "exception"
                transfer.exception_reason = "; ".join(exception_notes)[:255]
            else:
                transfer.status = "completed"
            transfer.completed_at = _now()
        else:
            transfer.status = "partially_received"

        await session.flush()
        return receipt

    # ---------------------------------------------------------- cancel ----

    @staticmethod
    async def cancel_transfer(
        session: AsyncSession,
        tenant_id: UUID,
        transfer_id: UUID,
        *,
        user_id: UUID | None = None,
        reason: str | None = None,
    ) -> InventoryTransfer:
        """Cancel a transfer before it is shipped."""
        transfer = await TransferServiceMixin.get_transfer(
            session, tenant_id, transfer_id, lock=True
        )
        if transfer.status not in ("draft", "approved", "picking", "packed"):
            raise ConflictError(
                f"transfer {transfer_id} is '{transfer.status}' and cannot be cancelled"
            )
        transfer.status = "cancelled"
        transfer.cancelled_at = _now()
        if reason:
            transfer.notes = (
                f"{transfer.notes}\nCancelled: {reason}".strip()
                if transfer.notes
                else f"Cancelled: {reason}"
            )
        await session.flush()
        return transfer

    # ------------------------------------------------- in_transit query ---

    @staticmethod
    async def in_transit_quantity(
        session: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        *,
        from_warehouse_id: UUID | None = None,
        to_warehouse_id: UUID | None = None,
    ) -> int:
        """Calculate quantity currently in transit between warehouses."""
        stmt = (
            select(
                func.coalesce(
                    func.sum(
                        InventoryTransferLine.quantity_shipped
                        - InventoryTransferLine.quantity_received
                    ),
                    0,
                )
            )
            .join(
                InventoryTransfer,
                InventoryTransfer.id == InventoryTransferLine.transfer_id,
            )
            .where(
                InventoryTransferLine.tenant_id == tenant_id,
                InventoryTransferLine.variant_id == variant_id,
                InventoryTransfer.status.in_(("in_transit", "partially_received")),
            )
        )
        if from_warehouse_id:
            stmt = stmt.where(InventoryTransfer.from_warehouse_id == from_warehouse_id)
        if to_warehouse_id:
            stmt = stmt.where(InventoryTransfer.to_warehouse_id == to_warehouse_id)
        return int((await session.execute(stmt)).scalar_one())

    # --------------------------------------------- complete (compat) ------

    @staticmethod
    async def complete_transfer(
        session: AsyncSession, tenant_id: UUID, transfer_id: UUID
    ) -> InventoryTransfer:
        """Ship and receive in one step (backward-compatible convenience)."""
        transfer = await TransferServiceMixin.get_transfer(session, tenant_id, transfer_id)
        if transfer.status == "draft":
            await TransferServiceMixin.ship_transfer(session, tenant_id, transfer_id)
            await TransferServiceMixin.receive_transfer(session, tenant_id, transfer_id)
        elif transfer.status in ("in_transit", "partially_received"):
            await TransferServiceMixin.receive_transfer(session, tenant_id, transfer_id)
        else:
            raise ConflictError(
                f"transfer {transfer_id} cannot be completed from status '{transfer.status}'"
            )
        return await TransferServiceMixin.get_transfer(session, tenant_id, transfer_id)
