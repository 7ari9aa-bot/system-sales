"""Dead stock: sizes with stock on the shelf that have not sold for a while.

The owner sets how long "a while" is (``inventory.dead_stock_days``, 7 to 730, default 60) and this
lists what is worth marking down, with the money tied up in it at cost.

* A variant is dead when it can be sold now (on hand less what is held for inspection) and its
  last sale is MORE than N days ago. A last sale exactly N days ago is not dead yet; N + 1 is.
* A sale is an order that is not cancelled or a draft, the same rule as the profit report. A
  return is not a sale and does not restart the clock: a shirt that came back did not sell.
* A variant that never sold is dead only once it has been on the shelf longer than N days, counted
  from its FIRST stock-in movement (the oldest ``in`` row in the ledger), or from the day the
  variant was created when it has no movement. Stock that arrived yesterday is not dead.
* Cost comes from ``variant_costs.avg_cost``. A variant whose cost is not known is flagged
  (``cost_known`` false, ``stock_value_at_cost`` null) and counted in ``variants_without_cost``;
  it is never priced at zero, and the total says it is incomplete.

Everything is summed in SQL, one grouped query per source, before it is put side by side. Read-only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import column, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.profit_report import _NOT_A_SALE, ProfitCtx
from app.modules.catalog.apparel.matrix import color_column, size_column
from app.modules.catalog.models import Product, ProductVariant
from app.modules.inventory.models import InventoryMovement
from app.modules.orders.models import Order, OrderItem

# Declared light, like the stock view: this report reads two columns of each.
_InventoryBalance = table(
    "inventory_balances",
    column("tenant_id"),
    column("variant_id"),
    column("on_hand"),
    column("quarantined"),
)
_VariantCost = table(
    "variant_costs",
    column("tenant_id"),
    column("variant_id"),
    column("avg_cost"),
)

MIN_DAYS = 7
MAX_DAYS = 730
_CENT = Decimal("0.01")
_ZERO = Decimal("0")


def _money(value: Decimal) -> str:
    return str(value.quantize(_CENT, rounding=ROUND_HALF_UP))


class DeadStockReportService:
    """Read-only. Writes nothing."""

    @staticmethod
    async def report(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        days: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """``days`` overrides the shop's own setting for this one look; ``now`` is for tests."""
        # Imported here, like expiry_report: a module-level import would add one more edge.
        from app.modules.settings.service import SettingsService

        if days is None:
            days = int(
                (
                    await SettingsService(session, tenant_id).resolve("inventory.dead_stock_days")
                ).value
            )
        days = max(MIN_DAYS, min(MAX_DAYS, int(days)))
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=days)

        held = (
            select(
                _InventoryBalance.c.variant_id.label("variant_id"),
                func.sum(_InventoryBalance.c.on_hand - _InventoryBalance.c.quarantined).label(
                    "sellable"
                ),
            )
            .where(_InventoryBalance.c.tenant_id == tenant_id)
            .group_by(_InventoryBalance.c.variant_id)
            .subquery()
        )
        last_sale = (
            select(
                OrderItem.variant_id.label("variant_id"),
                func.max(Order.placed_at).label("last_sold_at"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                OrderItem.tenant_id == tenant_id,
                Order.tenant_id == tenant_id,
                Order.status.not_in(_NOT_A_SALE),
            )
            .group_by(OrderItem.variant_id)
            .subquery()
        )
        first_in = (
            select(
                InventoryMovement.variant_id.label("variant_id"),
                func.min(InventoryMovement.created_at).label("first_in_at"),
            )
            .where(
                InventoryMovement.tenant_id == tenant_id,
                InventoryMovement.direction == "in",
            )
            .group_by(InventoryMovement.variant_id)
            .subquery()
        )
        sellable = func.greatest(0, func.coalesce(held.c.sellable, 0))
        # When the stock first arrived: its oldest "in" movement, else the variant's own birth.
        on_shelf_since = func.coalesce(first_in.c.first_in_at, ProductVariant.created_at)
        stmt = (
            select(
                ProductVariant.id.label("variant_id"),
                Product.title.label("model"),
                Product.season.label("season"),
                Product.material.label("material"),
                Product.brand_id.label("brand_id"),
                size_column(ProductVariant.option_values).label("size"),
                color_column(ProductVariant.option_values).label("colour"),
                sellable.label("on_hand"),
                last_sale.c.last_sold_at.label("last_sold_at"),
                _VariantCost.c.avg_cost.label("avg_cost"),
            )
            .select_from(ProductVariant)
            .join(Product, Product.id == ProductVariant.product_id)
            .join(held, held.c.variant_id == ProductVariant.id)
            .outerjoin(last_sale, last_sale.c.variant_id == ProductVariant.id)
            .outerjoin(first_in, first_in.c.variant_id == ProductVariant.id)
            .outerjoin(
                _VariantCost,
                (_VariantCost.c.variant_id == ProductVariant.id)
                & (_VariantCost.c.tenant_id == tenant_id),
            )
            .where(
                ProductVariant.tenant_id == tenant_id,
                ProductVariant.is_active.is_(True),
                sellable > 0,
                # Never sold: dead only if the stock has sat longer than N days. Sold: dead only
                # if the last sale is older than N days. A date exactly N days back is not dead.
                (last_sale.c.last_sold_at < cutoff)
                | ((last_sale.c.last_sold_at.is_(None)) & (on_shelf_since < cutoff)),
            )
        )
        found = (await session.execute(stmt)).all()

        rows: list[dict[str, Any]] = []
        for r in found:
            units = int(r.on_hand)
            cost = None if r.avg_cost is None else Decimal(r.avg_cost)
            value = None if cost is None else cost * units
            sold_at = r.last_sold_at
            rows.append(
                {
                    "variant_id": str(r.variant_id),
                    "model": r.model,
                    "season": r.season,
                    "material": r.material,
                    "brand_id": str(r.brand_id) if r.brand_id else None,
                    "size": r.size,
                    "colour": r.colour,
                    "units_on_hand": units,
                    "last_sold_at": sold_at.isoformat() if sold_at else None,
                    "days_since_last_sale": (now - sold_at).days if sold_at else None,
                    "cost_known": cost is not None,
                    "unit_cost": None if cost is None else _money(cost),
                    "stock_value_at_cost": None if value is None else _money(value),
                    "_value": value,
                }
            )
        # Most money tied up first; unknown cost after the known; then the longest unsold (a
        # never-sold size counts as the oldest), then a stable name order.
        rows.sort(
            key=lambda x: (
                x["_value"] is None,
                -(x["_value"] or _ZERO),
                x["days_since_last_sale"] is not None,
                -(x["days_since_last_sale"] or 0),
                x["model"] or "",
                x["colour"] or "",
                x["size"] or "",
            )
        )
        known = [x["_value"] for x in rows if x["_value"] is not None]
        without_cost = sum(1 for x in rows if x["_value"] is None)
        for x in rows:
            x.pop("_value")
        return {
            "days": days,
            "as_of": now.isoformat(),
            "rows": rows,
            "totals": {
                "variants": len(rows),
                "units_on_hand": sum(x["units_on_hand"] for x in rows),
                "stock_value_at_cost": _money(sum(known, _ZERO)),
                "variants_without_cost": without_cost,
                "cost_is_complete": without_cost == 0,
            },
        }


router = APIRouter(prefix="/reports/dead-stock", tags=["dead-stock"])


@router.get("")
async def dead_stock(
    ctx: ProfitCtx,
    days: Annotated[int | None, Query(ge=MIN_DAYS, le=MAX_DAYS)] = None,
) -> dict[str, Any]:
    """Sizes with stock and no sale for the shop's own number of days, with their value at cost."""
    return await DeadStockReportService.report(ctx.session, ctx.tenant_id, days=days)
