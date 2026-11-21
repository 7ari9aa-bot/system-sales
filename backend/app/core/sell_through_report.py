"""Sell-through by model, colour and size: what sold, what is left, and how much of it is gone.

For a clothing shop the useful question is not "how much did the shirt sell" but "which SIZE ran
out and which one sits". This reads the same profit report the owner already trusts and puts the
shelf next to it, so the two can never disagree about how many units sold.

* ``units_sold`` is the profit report's own figure with the units that came back taken off. It is
  not summed a second time from the orders.
* ``units_on_hand`` is what the shop can sell now: the stock on its shelves less what is held for
  inspection, never below zero. The count is as of now, not as of the end of the period.
* ``sold_share`` is sold / (sold + on hand) as a percentage with one decimal. It is ``None`` when
  both are zero: nothing sold and nothing left says nothing, and a made-up 0 would hide that.

A variant with stock and no sales is listed (sold 0, share 0.0) because that is exactly the size
that sits; a variant that sold and has nothing left is listed with share 100.0. Rows come back
with what is selling out first. Read-only.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import column, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.profit_report import ProfitCtx, ProfitReportService, _parse
from app.modules.catalog.apparel.matrix import COLOR_AXIS, SIZE_AXIS
from app.modules.catalog.models import Product, ProductVariant

# inventory's balance table, declared light like the stock view does: this report only reads three
# columns, and importing inventory.models here would be one more core -> inventory edge.
_InventoryBalance = table(
    "inventory_balances",
    column("tenant_id"),
    column("variant_id"),
    column("on_hand"),
    column("quarantined"),
)

_TENTH = Decimal("0.1")
_HUNDRED = Decimal("100")


def share_of(sold: int, on_hand: int) -> str | None:
    """Percent sold, one decimal, or None when there was nothing to sell and nothing sold."""
    total = sold + on_hand
    if total <= 0:
        return None
    return str((Decimal(sold) * _HUNDRED / Decimal(total)).quantize(_TENTH, ROUND_HALF_UP))


class SellThroughReportService:
    """Read-only. Writes nothing."""

    @staticmethod
    async def by_variant(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        start: date | datetime,
        end: date | datetime,
        channel: str | None = None,
        season: str | None = None,
        material: str | None = None,
        brand_id: UUID | None = None,
    ) -> dict[str, Any]:
        profit = await ProfitReportService.by_variant(
            session,
            tenant_id,
            start=start,
            end=end,
            channel=channel,
            season=season,
            material=material,
            brand_id=brand_id,
        )
        sold: dict[str, int] = {
            r["variant_id"]: max(0, r["units_sold"] - r["units_returned"]) for r in profit["rows"]
        }

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
        wanted = [ProductVariant.tenant_id == tenant_id, ProductVariant.is_active.is_(True)]
        wanted_season = (season or "").strip()
        if wanted_season:
            wanted.append(func.lower(Product.season) == wanted_season.lower())
        wanted_material = (material or "").strip()
        if wanted_material:
            wanted.append(func.lower(Product.material) == wanted_material.lower())
        if brand_id is not None:
            wanted.append(Product.brand_id == brand_id)
        # Every variant the shop has (with its stock) or has sold in the window: a size that sold
        # out and was since deactivated must still show, so sold variants are never dropped.
        stmt = (
            select(
                ProductVariant.id.label("variant_id"),
                Product.title.label("model"),
                Product.season.label("season"),
                Product.material.label("material"),
                Product.brand_id.label("brand_id"),
                ProductVariant.option_values[SIZE_AXIS].astext.label("size"),
                ProductVariant.option_values[COLOR_AXIS].astext.label("colour"),
                func.greatest(0, func.coalesce(held.c.sellable, 0)).label("on_hand"),
            )
            .select_from(ProductVariant)
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(held, held.c.variant_id == ProductVariant.id)
            .where(*wanted)
        )
        shelf = (await session.execute(stmt)).all()

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for r in shelf:
            key = str(r.variant_id)
            seen.add(key)
            units = sold.get(key, 0)
            on_hand = int(r.on_hand or 0)
            rows.append(
                _row(
                    key, r.model, r.season, r.material, r.brand_id, r.size, r.colour, units, on_hand
                )
            )
        # Sold in the window but no longer an active variant: keep its sales, no stock to show.
        for p in profit["rows"]:
            if p["variant_id"] in seen:
                continue
            units = sold.get(p["variant_id"], 0)
            rows.append(
                _row(
                    p["variant_id"],
                    p["model"],
                    p["season"],
                    p["material"],
                    UUID(p["brand_id"]) if p["brand_id"] else None,
                    p["size"],
                    p["colour"],
                    units,
                    0,
                )
            )
        # Nothing sold and nothing on the shelf is not a row worth a line.
        rows = [r for r in rows if r["units_sold"] or r["units_on_hand"]]
        rows.sort(
            key=lambda r: (
                -(Decimal(r["sold_share"]) if r["sold_share"] is not None else Decimal(-1)),
                -r["units_sold"],
                r["model"] or "",
                r["colour"] or "",
                r["size"] or "",
            )
        )
        total_sold = sum(r["units_sold"] for r in rows)
        total_left = sum(r["units_on_hand"] for r in rows)
        return {
            "period": profit["period"],
            "rows": rows,
            "totals": {
                "units_sold": total_sold,
                "units_on_hand": total_left,
                "sold_share": share_of(total_sold, total_left),
            },
        }


def _row(
    variant_id: str,
    model: str | None,
    season: str | None,
    material: str | None,
    brand_id: UUID | None,
    size: str | None,
    colour: str | None,
    units_sold: int,
    units_on_hand: int,
) -> dict[str, Any]:
    return {
        "variant_id": variant_id,
        "model": model,
        "season": season,
        "material": material,
        "brand_id": str(brand_id) if brand_id else None,
        "size": size,
        "colour": colour,
        "units_sold": units_sold,
        "units_on_hand": units_on_hand,
        "sold_share": share_of(units_sold, units_on_hand),
    }


router = APIRouter(prefix="/reports/sell-through", tags=["sell-through"])


@router.get("")
async def sell_through(
    ctx: ProfitCtx,
    start: str,
    end: str,
    channel: str | None = None,
    season: str | None = None,
    material: str | None = None,
    brand_id: UUID | None = None,
) -> dict[str, Any]:
    """One row per model, colour and size: sold, left on the shelf, and the share sold."""
    return await SellThroughReportService.by_variant(
        ctx.session,
        ctx.tenant_id,
        start=_parse(start, "start"),
        end=_parse(end, "end"),
        channel=channel,
        season=season,
        material=material,
        brand_id=brand_id,
    )
