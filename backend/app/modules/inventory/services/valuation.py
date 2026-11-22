"""Inventory Valuation Service: FIFO Cost Layers and Landed Cost (D10, §4 Phase 5).

Provides deterministic stock valuation alongside moving average:
- FIFO Cost Layers: records arrival layers and consumes them in FIFO order on stock out.
- COGS on sales: books cost of goods sold on sales movements.
- Landed Cost: allocates freight, customs, and duties across received stock and adjusts layers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InsufficientStockError
from app.modules.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.modules.inventory.models import (
    InventoryCostLayer,
    InventoryLandedCost,
    InventoryLandedCostLine,
    InventoryLot,
    Warehouse,
)


class ValuationService:
    """Valuation, FIFO cost layer tracking, and landed cost allocation."""

    # --------------------------------------------------- FIFO Cost Layers --

    @staticmethod
    async def create_cost_layer(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
        quantity: int,
        unit_cost: Decimal | str | float,
        source_type: str | None = None,
        source_id: UUID | None = None,
        layer_date: datetime | None = None,
        lot_id: UUID | None = None,
    ) -> InventoryCostLayer:
        """Create a new FIFO cost layer when stock arrives (goods receipt, transfer, etc.)."""
        if quantity <= 0:
            raise ValidationError("received_quantity must be positive")
        cost = Decimal(str(unit_cost)).quantize(Decimal("0.0001"))
        if cost < 0:
            raise ValidationError("unit_cost cannot be negative")

        layer = InventoryCostLayer(
            tenant_id=tenant_id,
            variant_id=variant_id,
            warehouse_id=warehouse_id,
            received_quantity=quantity,
            remaining_quantity=quantity,
            unit_cost=cost,
            layer_date=layer_date or datetime.now(UTC),
            source_type=source_type,
            source_id=source_id,
            lot_id=lot_id,
        )
        session.add(layer)
        await session.flush()
        return layer

    @staticmethod
    async def get_active_layers(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
    ) -> list[InventoryCostLayer]:
        """Fetch active FIFO layers for a variant in a warehouse (layer_date ASC, id ASC)."""
        return list(
            (
                await session.execute(
                    select(InventoryCostLayer)
                    .where(
                        InventoryCostLayer.tenant_id == tenant_id,
                        InventoryCostLayer.variant_id == variant_id,
                        InventoryCostLayer.warehouse_id == warehouse_id,
                        InventoryCostLayer.remaining_quantity > 0,
                    )
                    .order_by(InventoryCostLayer.layer_date.asc(), InventoryCostLayer.id.asc())
                )
            ).scalars()
        )

    @staticmethod
    async def consume_fifo(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
        quantity: int,
        allow_partial: bool = False,
        order: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Deplete cost layers: oldest received first (``fifo``) or soonest expiring (``fefo``).

        ``fifo`` is what every shop has always had. ``fefo`` is for a shop that tracks expiry: the
        layer whose batch expires first goes first, a batch that has expired is never sold, and
        stock with no batch or no expiry date goes after the dated batches.

        ``order=None`` (the default) asks the shop: its ``fefo_picking`` capability decides, so a
        sale, a transfer and a direct sale all follow the same rule without each remembering it.
        Pass ``"fifo"`` or ``"fefo"`` to force one.

        Returns:
            {
                "consumed_quantity": int,
                "total_cogs": Decimal,
                "consumed_layers": list[dict],
            }
        """
        if quantity <= 0:
            raise ValidationError("quantity to consume must be positive")

        if order is None:
            # Lazy import: expiry already reads settings, and valuation must not import it at load.
            from app.modules.inventory.services.expiry import consumption_order

            order = await consumption_order(session, tenant_id)
        if order not in ("fifo", "fefo"):
            raise ValueError(f"unknown consumption order {order!r}; expected 'fifo' or 'fefo'")

        stmt = select(InventoryCostLayer).where(
            InventoryCostLayer.tenant_id == tenant_id,
            InventoryCostLayer.variant_id == variant_id,
            InventoryCostLayer.warehouse_id == warehouse_id,
            InventoryCostLayer.remaining_quantity > 0,
        )
        if order == "fefo":
            at = now or datetime.now(UTC)
            # Outer join: a layer with no batch is still stock. Only a batch that has expired
            # is excluded; one that expires this instant counts as expired.
            stmt = stmt.outerjoin(
                InventoryLot,
                (InventoryLot.id == InventoryCostLayer.lot_id)
                & (InventoryLot.tenant_id == InventoryCostLayer.tenant_id),
            ).where(or_(InventoryLot.expires_at.is_(None), InventoryLot.expires_at > at))
            stmt = stmt.order_by(
                InventoryLot.expires_at.asc().nulls_last(),
                InventoryCostLayer.layer_date.asc(),
                InventoryCostLayer.id.asc(),
            )
        else:
            stmt = stmt.order_by(InventoryCostLayer.layer_date.asc(), InventoryCostLayer.id.asc())
        layers = list(
            (await session.execute(stmt.with_for_update(of=InventoryCostLayer))).scalars()
        )

        total_available = sum(lyr.remaining_quantity for lyr in layers)
        if not allow_partial and total_available < quantity:
            raise InsufficientStockError(
                f"insufficient cost layers for variant {variant_id}: "
                f"requested {quantity}, available {total_available}"
            )

        remaining_need = min(quantity, total_available) if allow_partial else quantity
        total_cogs = Decimal("0.0000")
        consumed_layers = []

        for layer in layers:
            if remaining_need <= 0:
                break
            taken = min(layer.remaining_quantity, remaining_need)
            layer_cost = (taken * layer.unit_cost).quantize(Decimal("0.0001"))
            layer.remaining_quantity -= taken
            remaining_need -= taken
            total_cogs += layer_cost
            consumed_layers.append(
                {
                    "layer_id": str(layer.id),
                    "lot_id": str(layer.lot_id) if layer.lot_id else None,
                    "quantity": taken,
                    "unit_cost": layer.unit_cost,
                    "cost": layer_cost,
                }
            )

        await session.flush()
        return {
            "consumed_quantity": quantity,
            # What the layers really covered. With allow_partial this can be less than the
            # quantity asked for; a caller that books a cost must not treat the rest as free.
            "covered_quantity": sum(c["quantity"] for c in consumed_layers),
            "total_cogs": total_cogs.quantize(Decimal("0.0001")),
            "consumed_layers": consumed_layers,
        }

    @staticmethod
    async def record_sale(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        variant_id: UUID,
        warehouse_id: UUID,
        quantity: int,
        reference_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Book a sale movement with exact FIFO COGS cost tracking.

        Consumes active layers, calculates COGS, and records an 'out' / 'sale'
        movement with `cost_value=total_cogs`.
        """
        from app.modules.inventory.service import InventoryService

        consumption = await ValuationService.consume_fifo(
            session,
            tenant_id,
            variant_id=variant_id,
            warehouse_id=warehouse_id,
            quantity=quantity,
        )
        total_cogs = consumption["total_cogs"]

        movement = await InventoryService.move(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            direction="out",
            quantity=quantity,
            reason="sale",
            reference_type="sale",
            reference_id=reference_id,
            actor_user_id=actor_user_id,
            cost_value=total_cogs,
        )

        return {
            "movement": movement,
            "total_cogs": total_cogs,
            "consumed_layers": consumption["consumed_layers"],
        }

    # --------------------------------------------------- Stock Valuation ---

    @staticmethod
    async def calculate_valuation(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID | None = None,
        variant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Deterministic FIFO stock valuation report."""
        q = select(InventoryCostLayer).where(
            InventoryCostLayer.tenant_id == tenant_id,
            InventoryCostLayer.remaining_quantity > 0,
        )
        if warehouse_id:
            q = q.where(InventoryCostLayer.warehouse_id == warehouse_id)
        if variant_id:
            q = q.where(InventoryCostLayer.variant_id == variant_id)

        layers = list((await session.execute(q)).scalars())
        total_units = sum(lyr.remaining_quantity for lyr in layers)
        total_val = sum((lyr.remaining_quantity * lyr.unit_cost) for lyr in layers)
        avg_cost = (
            (total_val / Decimal(total_units)).quantize(Decimal("0.0001"))
            if total_units > 0
            else Decimal("0.0000")
        )

        return {
            "total_quantity": total_units,
            "total_valuation": Decimal(total_val).quantize(Decimal("0.0001")),
            "average_unit_cost": avg_cost,
            "layer_count": len(layers),
        }

    # --------------------------------------------------- Landed Cost -------

    @staticmethod
    async def create_landed_cost(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        warehouse_id: UUID,
        total: Decimal | str | float,
        purchase_order_id: UUID | None = None,
        note: str | None = None,
        user_id: UUID | None = None,
    ) -> InventoryLandedCost:
        """Create a draft landed cost document."""
        amount = Decimal(str(total)).quantize(Decimal("0.01"))
        if amount < 0:
            raise ValidationError("landed cost total must be non-negative")

        wh = (
            await session.execute(
                select(Warehouse).where(
                    Warehouse.tenant_id == tenant_id, Warehouse.id == warehouse_id
                )
            )
        ).scalar_one_or_none()
        if wh is None:
            raise NotFoundError("warehouse not found")

        doc = InventoryLandedCost(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            purchase_order_id=purchase_order_id,
            total=amount,
            status="draft",
            note=(note or "").strip()[:500] or None,
            created_by_user_id=user_id,
        )
        session.add(doc)
        await session.flush()
        return doc

    @staticmethod
    async def allocate_landed_cost(
        session: AsyncSession,
        tenant_id: UUID,
        landed_cost_id: UUID,
        *,
        method: str = "quantity",
        items: list[dict[str, Any]] | None = None,
    ) -> list[InventoryLandedCostLine]:
        """Allocate the landed cost total across items.

        `method`: 'quantity' (by item units) or 'value' (by units * unit_cost).
        `items`: list of dicts with: `variant_id`, `quantity`, `unit_cost`.
        If items is omitted and landed cost is linked to a purchase order, items
        are automatically loaded from the purchase order lines.
        """
        doc = (
            await session.execute(
                select(InventoryLandedCost)
                .where(
                    InventoryLandedCost.tenant_id == tenant_id,
                    InventoryLandedCost.id == landed_cost_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if doc is None:
            raise NotFoundError("landed cost not found")
        if doc.status != "draft":
            raise ConflictError(f"cannot allocate a {doc.status} landed cost")

        if items is None:
            if doc.purchase_order_id:
                po_rows = (
                    (
                        await session.execute(
                            text(
                                "SELECT variant_id, quantity, unit_cost FROM purchase_order_lines "
                                "WHERE tenant_id = :tenant_id AND purchase_order_id = :po_id"
                            ),
                            {"tenant_id": tenant_id, "po_id": doc.purchase_order_id},
                        )
                    )
                    .mappings()
                    .all()
                )
                if not po_rows:
                    raise ValidationError(
                        f"purchase order {doc.purchase_order_id} has no lines to allocate"
                    )
                items = [
                    {
                        "variant_id": row["variant_id"],
                        "quantity": row["quantity"],
                        "unit_cost": row["unit_cost"],
                    }
                    for row in po_rows
                ]
            else:
                raise ValidationError("must provide items to allocate landed cost")

        if not items:
            raise ValidationError("must provide at least one item to allocate landed cost")

        # Delete existing lines if re-allocating draft
        existing_lines = list(
            (
                await session.execute(
                    select(InventoryLandedCostLine).where(
                        InventoryLandedCostLine.tenant_id == tenant_id,
                        InventoryLandedCostLine.landed_cost_id == landed_cost_id,
                    )
                )
            ).scalars()
        )
        for el in existing_lines:
            await session.delete(el)

        total_amount = doc.total
        lines = []

        if method == "quantity":
            total_qty = sum(int(item["quantity"]) for item in items)
            if total_qty <= 0:
                raise ValidationError("total quantity must be positive")

            allocated_so_far = Decimal("0.00")
            for i, item in enumerate(items):
                qty = int(item["quantity"])
                if i == len(items) - 1:
                    # Last item absorbs rounding difference to ensure sum == total
                    line_amt = total_amount - allocated_so_far
                else:
                    ratio = Decimal(qty) / Decimal(total_qty)
                    line_amt = (total_amount * ratio).quantize(Decimal("0.01"))
                    allocated_so_far += line_amt

                line = InventoryLandedCostLine(
                    tenant_id=tenant_id,
                    landed_cost_id=landed_cost_id,
                    variant_id=item["variant_id"],
                    quantity=qty,
                    amount=line_amt,
                )
                session.add(line)
                lines.append(line)

        elif method == "value":
            item_values = []
            for item in items:
                qty = int(item["quantity"])
                unit_cost = Decimal(str(item.get("unit_cost", "0.00")))
                item_values.append(qty * unit_cost)

            total_val = sum(item_values)
            if total_val <= 0:
                raise ValidationError("total value must be positive for value-based allocation")

            allocated_so_far = Decimal("0.00")
            for i, item in enumerate(items):
                qty = int(item["quantity"])
                val = item_values[i]
                if i == len(items) - 1:
                    line_amt = total_amount - allocated_so_far
                else:
                    ratio = val / total_val
                    line_amt = (total_amount * ratio).quantize(Decimal("0.01"))
                    allocated_so_far += line_amt

                line = InventoryLandedCostLine(
                    tenant_id=tenant_id,
                    landed_cost_id=landed_cost_id,
                    variant_id=item["variant_id"],
                    quantity=qty,
                    amount=line_amt,
                )
                session.add(line)
                lines.append(line)
        else:
            raise ValidationError(f"unsupported allocation method: {method!r}")

        await session.flush()
        return lines

    @staticmethod
    async def post_landed_cost(
        session: AsyncSession,
        tenant_id: UUID,
        landed_cost_id: UUID,
        *,
        user_id: UUID | None = None,
    ) -> InventoryLandedCost:
        """Post landed cost: status -> 'posted' and folds extra cost into active layers."""
        doc = (
            await session.execute(
                select(InventoryLandedCost)
                .where(
                    InventoryLandedCost.tenant_id == tenant_id,
                    InventoryLandedCost.id == landed_cost_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if doc is None:
            raise NotFoundError("landed cost not found")
        if doc.status == "posted":
            raise ConflictError("landed cost is already posted")

        lines = list(
            (
                await session.execute(
                    select(InventoryLandedCostLine).where(
                        InventoryLandedCostLine.tenant_id == tenant_id,
                        InventoryLandedCostLine.landed_cost_id == landed_cost_id,
                    )
                )
            ).scalars()
        )
        if not lines:
            raise ValidationError("cannot post landed cost with no allocated lines")

        # Fold allocated landed cost into active layers for each variant in warehouse
        for line in lines:
            layers: list[InventoryCostLayer] = []
            if doc.purchase_order_id:
                # First try targeting layers originating from this PO
                po_q = (
                    select(InventoryCostLayer)
                    .where(
                        InventoryCostLayer.tenant_id == tenant_id,
                        InventoryCostLayer.warehouse_id == doc.warehouse_id,
                        InventoryCostLayer.variant_id == line.variant_id,
                        InventoryCostLayer.remaining_quantity > 0,
                        InventoryCostLayer.source_type == "purchase_order",
                        InventoryCostLayer.source_id == doc.purchase_order_id,
                    )
                    .order_by(InventoryCostLayer.layer_date.asc())
                    .with_for_update()
                )
                layers = list((await session.execute(po_q)).scalars())

            if not layers:
                # Fall back to FIFO order of active layers for this variant
                q = (
                    select(InventoryCostLayer)
                    .where(
                        InventoryCostLayer.tenant_id == tenant_id,
                        InventoryCostLayer.warehouse_id == doc.warehouse_id,
                        InventoryCostLayer.variant_id == line.variant_id,
                        InventoryCostLayer.remaining_quantity > 0,
                    )
                    .order_by(InventoryCostLayer.layer_date.asc())
                    .with_for_update()
                )
                layers = list((await session.execute(q)).scalars())

            # Distribute extra cost to layers up to line.quantity
            remaining_qty = line.quantity
            for layer in layers:
                if remaining_qty <= 0:
                    break
                qty_on_layer = min(layer.remaining_quantity, remaining_qty)
                layer_extra = (
                    line.amount * Decimal(qty_on_layer) / Decimal(line.quantity)
                ).quantize(Decimal("0.0001"))
                extra_per_unit = (layer_extra / Decimal(qty_on_layer)).quantize(Decimal("0.0001"))
                layer.unit_cost = (layer.unit_cost + extra_per_unit).quantize(Decimal("0.0001"))
                remaining_qty -= qty_on_layer

        doc.status = "posted"
        await session.flush()
        return doc
