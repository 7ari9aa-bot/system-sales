"""Profit by model, colour and size, from the books the shop already keeps.

Nothing is priced again here. Revenue is the order's own net line (less its share of any
invoice-level discount), cost is the ``cost_value`` the stock ledger booked on the sale movement,
and a return gives back its refund. Three things the books cannot say are said out loud instead of
being folded into a flattering number:

* a sale whose cost the layers could not cover carries no cost, so it is counted in
  ``units_without_cost`` and the totals say the cost is not complete;
* the cost a return gives back is an ESTIMATE (the sale's average cost per unit times the units
  that went back on the shelf), because the ledger books no cost on a return;
* a return that did not go back on the shelf gives back no cost: the piece is gone.

Each source table is summed on its own, by (order, variant), before anything is joined, so a line
that appears twice in an order, or a return of part of it, can never multiply another figure.
It lives in ``app/core`` because it reads orders, stock, returns, expenses and the catalog, and
placing it in any one of those modules would add an edge to each of the others.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from app.modules.catalog.apparel.matrix import color_column, size_column
from app.modules.catalog.models import Product, ProductVariant
from app.modules.errors import ValidationError
from app.modules.expenses.models import Expense
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.inventory.models import InventoryCostLayer, InventoryMovement
from app.modules.orders.models import Order, OrderItem
from app.modules.pos.models import PosReturnLine

_CENT = Decimal("0.01")
_ZERO = Decimal("0")
#: An order in one of these states is not a sale.
_NOT_A_SALE = ("cancelled", "draft")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _s(value: Decimal) -> str:
    return str(_q(value))


def _bounds(start: date | datetime, end: date | datetime) -> tuple[datetime, datetime]:
    """[start, end) as instants. A plain date means that day's midnight UTC."""

    def _at(value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        return datetime.combine(value, time.min, tzinfo=UTC)

    lo, hi = _at(start), _at(end)
    if hi <= lo:
        raise ValidationError("the period must end after it starts")
    return lo, hi


class ProfitReportService:
    """Read-only profit figures. Writes nothing."""

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
        """One row per model, colour and size. ``season``, ``material`` and ``brand_id`` narrow it
        to one season, one fabric or one brand. A season and a material are the owner's own
        labels: case and outer spaces do not matter. Left out, every sale is in, exactly as
        before."""
        lo, hi = _bounds(start, end)

        order_ok = [
            Order.tenant_id == tenant_id,
            Order.status.not_in(_NOT_A_SALE),
            Order.placed_at >= lo,
            Order.placed_at < hi,
        ]
        if channel is not None:
            order_ok.append(Order.channel == channel)

        # 1. Net line revenue and units, per (order, variant).
        lines = (
            select(
                OrderItem.order_id.label("order_id"),
                OrderItem.variant_id.label("variant_id"),
                func.sum(OrderItem.quantity).label("units"),
                func.sum(OrderItem.total).label("net"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.tenant_id == tenant_id, *order_ok)
            .group_by(OrderItem.order_id, OrderItem.variant_id)
            .subquery()
        )
        # 2. The order's net lines and its invoice-level discount, to share the discount out.
        order_net = (
            select(
                lines.c.order_id.label("order_id"),
                func.sum(lines.c.net).label("net_all"),
            )
            .group_by(lines.c.order_id)
            .subquery()
        )
        # 3. Cost booked on the sale movements, per (order, variant); a NULL cost is counted apart.
        costs = (
            select(
                InventoryMovement.reference_id.label("order_id"),
                InventoryMovement.variant_id.label("variant_id"),
                func.coalesce(func.sum(InventoryMovement.cost_value), 0).label("cost"),
                func.sum(
                    case(
                        (InventoryMovement.cost_value.is_(None), InventoryMovement.quantity),
                        else_=0,
                    )
                ).label("units_without_cost"),
            )
            .where(
                InventoryMovement.tenant_id == tenant_id,
                InventoryMovement.reason == "sale",
                InventoryMovement.direction == "out",
                InventoryMovement.reference_type == "order",
            )
            .group_by(InventoryMovement.reference_id, InventoryMovement.variant_id)
            .subquery()
        )
        # 4. What came back: refund and units from the return lines...
        returns = (
            select(
                PosReturnLine.order_id.label("order_id"),
                PosReturnLine.variant_id.label("variant_id"),
                func.sum(PosReturnLine.quantity).label("units_returned"),
                func.sum(PosReturnLine.refund_total).label("refund"),
            )
            .where(PosReturnLine.tenant_id == tenant_id)
            .group_by(PosReturnLine.order_id, PosReturnLine.variant_id)
            .subquery()
        )
        # ...and how many of those units went back on the shelf (a return movement in).
        shelved = (
            select(
                InventoryMovement.reference_id.label("order_id"),
                InventoryMovement.variant_id.label("variant_id"),
                func.sum(InventoryMovement.quantity).label("units_shelved"),
            )
            .where(
                InventoryMovement.tenant_id == tenant_id,
                InventoryMovement.reason == "return",
                InventoryMovement.direction == "in",
                InventoryMovement.reference_type == "order",
            )
            .group_by(InventoryMovement.reference_id, InventoryMovement.variant_id)
            .subquery()
        )

        share = case(
            (
                order_net.c.net_all > 0,
                lines.c.net
                * func.least(Order.discount_total, order_net.c.net_all)
                / order_net.c.net_all,
            ),
            else_=0,
        )
        product_ok = []
        if season is not None:
            # Same rule as the product list: SS26, ss26 and ' SS26' are one season.
            product_ok.append(func.lower(Product.season) == season.strip().lower())
        wanted_material = (material or "").strip()
        if wanted_material:
            # Same rule again: قطن,  قطن and ' COTTON ' are one fabric. A box left empty is no
            # filter at all, not a filter for products with an empty fabric.
            product_ok.append(func.lower(Product.material) == wanted_material.lower())
        if brand_id is not None:
            product_ok.append(Product.brand_id == brand_id)
        # Discount already inside the line nets (a per-line percentage) is not taken off twice:
        # only the invoice-level part, the discount beyond what the line nets already reflect.
        # What came back, split by the STATE the garment came back in, aggregated per variant so
        # it rides along with the rows below instead of costing its own round trip.
        cond_units = (
            select(
                PosReturnLine.variant_id.label("variant_id"),
                func.coalesce(PosReturnLine.condition, "unstated").label("cond"),
                func.sum(PosReturnLine.quantity).label("units"),
            )
            .join(Order, Order.id == PosReturnLine.order_id)
            .where(PosReturnLine.tenant_id == tenant_id, *order_ok)
            .group_by(PosReturnLine.variant_id, PosReturnLine.condition)
            .subquery()
        )
        conds = (
            select(
                cond_units.c.variant_id,
                func.array_agg(cond_units.c.cond).label("conds"),
                func.array_agg(cond_units.c.units).label("cond_units"),
            )
            .group_by(cond_units.c.variant_id)
            .subquery()
        )

        stmt = (
            select(
                ProductVariant.id.label("variant_id"),
                Product.title.label("model"),
                Product.season.label("season"),
                Product.material.label("material"),
                Product.brand_id.label("brand_id"),
                size_column(ProductVariant.option_values).label("size"),
                color_column(ProductVariant.option_values).label("colour"),
                func.sum(lines.c.units).label("units_sold"),
                func.sum(lines.c.net - share).label("sales_net"),
                func.coalesce(func.sum(costs.c.cost), 0).label("cost"),
                func.coalesce(func.sum(costs.c.units_without_cost), 0).label("units_without_cost"),
                func.coalesce(func.sum(returns.c.units_returned), 0).label("units_returned"),
                func.coalesce(func.sum(returns.c.refund), 0).label("refund"),
                func.coalesce(func.sum(shelved.c.units_shelved), 0).label("units_shelved"),
                # What came back, split by the state it came back in, in the SAME statement: the
                # second round trip this used to need was a whole query for data that belongs to
                # these rows.
                conds.c.conds.label("conds"),
                conds.c.cond_units.label("cond_units"),
            )
            .select_from(lines)
            .join(Order, Order.id == lines.c.order_id)
            .join(order_net, order_net.c.order_id == lines.c.order_id)
            .join(ProductVariant, ProductVariant.id == lines.c.variant_id)
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(
                costs,
                and_(
                    costs.c.order_id == lines.c.order_id, costs.c.variant_id == lines.c.variant_id
                ),
            )
            .outerjoin(
                returns,
                and_(
                    returns.c.order_id == lines.c.order_id,
                    returns.c.variant_id == lines.c.variant_id,
                ),
            )
            .outerjoin(
                shelved,
                and_(
                    shelved.c.order_id == lines.c.order_id,
                    shelved.c.variant_id == lines.c.variant_id,
                ),
            )
            .outerjoin(conds, conds.c.variant_id == ProductVariant.id)
            .where(*product_ok)
            .group_by(
                ProductVariant.id,
                Product.title,
                Product.season,
                Product.material,
                Product.brand_id,
                size_column(ProductVariant.option_values),
                color_column(ProductVariant.option_values),
                # One row per variant, so these are constant within the group; Postgres needs them
                # named here to allow the join's columns in the SELECT.
                conds.c.conds,
                conds.c.cond_units,
            )
        )
        result = (await session.execute(stmt)).all()

        # 5. What came back, split by the STATE the garment came back in. The cost a return gives
        # back is an estimate either way, but which estimate is only defensible when the reader can
        # see what came back: a sellable piece returns to the shelf and gives its cost back, a
        # damaged or written-off one is gone, and a piece going back to the supplier is not stock at
        # all. Lumping them into one "returned" number hid that.
        # The rows are per MODEL, COLOUR and SIZE, so the split is keyed the same way: one row
        # aggregates every order that sold that size in the window.
        by_condition: dict[Any, dict[str, int]] = {}
        for r in result:
            # Paired arrays from the joined CTE, in the order they were aggregated.
            for state, units in zip(r.conds or [], r.cond_units or [], strict=False):
                slot = by_condition.setdefault(r.variant_id, {})
                slot[str(state or "unstated")] = int(units or 0)

        rows: list[dict[str, Any]] = []
        for r in result:
            units = int(r.units_sold or 0)
            returned = int(r.units_returned or 0)
            shelved_units = min(int(r.units_shelved or 0), returned)
            sales_net = Decimal(r.sales_net or 0)
            booked_cost = Decimal(r.cost or 0)
            without_cost = int(r.units_without_cost or 0)
            costed_units = units - without_cost
            # The ledger books no cost on a return, so what goes back is estimated from the cost
            # of the units that WERE costed. A shop with nothing costed has nothing to give back.
            unit_cost = booked_cost / costed_units if costed_units > 0 else _ZERO
            cost_back = unit_cost * shelved_units
            conditions = by_condition.get(r.variant_id, {})
            revenue = sales_net - Decimal(r.refund or 0)
            cost = booked_cost - cost_back
            profit = revenue - cost
            rows.append(
                {
                    "variant_id": str(r.variant_id),
                    "model": r.model,
                    "season": r.season,
                    "material": r.material,
                    "brand_id": str(r.brand_id) if r.brand_id else None,
                    "size": r.size,
                    "colour": r.colour,
                    "units_sold": units,
                    "units_returned": returned,
                    "revenue": _s(revenue),
                    "cost": _s(cost),
                    "gross_profit": _s(profit),
                    "margin_pct": _s(profit / revenue * 100) if revenue > 0 else None,
                    "units_without_cost": without_cost,
                    # What came back, by the state it came back in, and how many of those pieces
                    # actually returned to the shelf (the only ones that give cost back).
                    "returned_by_condition": conditions,
                    "units_returned_to_shelf": shelved_units,
                    "cost_returned": _s(cost_back),
                    "cost_returned_is_estimate": bool(returned and shelved_units),
                    "_profit": profit,
                    "_revenue": revenue,
                    "_cost": cost,
                }
            )
        rows.sort(key=lambda row: (-row["_profit"], row["model"] or "", row["size"] or ""))

        tot_rev = sum((r["_revenue"] for r in rows), _ZERO)
        tot_cost = sum((r["_cost"] for r in rows), _ZERO)
        tot_profit = tot_rev - tot_cost
        no_cost = sum(r["units_without_cost"] for r in rows)
        tot_conditions: dict[str, int] = {}
        for r in rows:
            for state, units in r["returned_by_condition"].items():
                tot_conditions[state] = tot_conditions.get(state, 0) + units
        for r in rows:
            for k in ("_profit", "_revenue", "_cost"):
                r.pop(k)
        return {
            "period": {"start": lo.isoformat(), "end": hi.isoformat()},
            "rows": rows,
            "totals": {
                "units_sold": sum(r["units_sold"] for r in rows),
                "revenue": _s(tot_rev),
                "cost": _s(tot_cost),
                "gross_profit": _s(tot_profit),
                "margin_pct": _s(tot_profit / tot_rev * 100) if tot_rev > 0 else None,
                "units_without_cost": no_cost,
                "cost_is_complete": no_cost == 0,
                "units_returned": sum(r["units_returned"] for r in rows),
                "units_returned_to_shelf": sum(r["units_returned_to_shelf"] for r in rows),
                "returned_by_condition": tot_conditions,
                # The rule the numbers follow, spelled once for the screen.
                "cost_returned_basis": (
                    "estimate: the sale's average cost per unit for the pieces that went back on "
                    "the shelf; a damaged, written-off or supplier-bound piece gives back nothing"
                ),
            },
        }

    @staticmethod
    async def summary(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        start: date | datetime,
        end: date | datetime,
        channel: str | None = None,
    ) -> dict[str, Any]:
        """Gross profit, expenses, net profit, and the stock still on the shelf at cost."""
        report = await ProfitReportService.by_variant(
            session, tenant_id, start=start, end=end, channel=channel
        )
        lo, hi = _bounds(start, end)
        expenses = (
            await session.execute(
                select(func.coalesce(func.sum(Expense.amount), 0)).where(
                    Expense.tenant_id == tenant_id,
                    Expense.status == "posted",
                    Expense.expense_date >= lo.date(),
                    Expense.expense_date
                    < hi.date() + (timedelta(days=1) if hi.time() != time.min else timedelta(0)),
                )
            )
        ).scalar_one()
        layers = (
            await session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            InventoryCostLayer.remaining_quantity * InventoryCostLayer.unit_cost
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(InventoryCostLayer.remaining_quantity), 0).cast(Integer),
                ).where(
                    InventoryCostLayer.tenant_id == tenant_id,
                    InventoryCostLayer.remaining_quantity > 0,
                )
            )
        ).one()
        gross = Decimal(report["totals"]["gross_profit"])
        spent = Decimal(expenses)
        return {
            **report["totals"],
            "period": report["period"],
            "expenses": _s(spent),
            "net_profit": _s(gross - spent),
            "stock_value_at_cost": _s(Decimal(layers[0])),
            "stock_units": int(layers[1]),
        }


# ── HTTP ───────────────────────────────────────────────────────────────────────────────────────


router = APIRouter(prefix="/reports/profit", tags=["profit"])
PROFIT_SETTING = "reports.managers_see_profit"


class _ProfitGate:
    """Who may read what the shop paid for its stock and what it earns on it, or reprice a season.

    Never a till operator: without ``pos:override`` the answer is no, whatever the shop set. The
    shop owner (the holder of ``settings:write``) always may. A manager may while the OWNER leaves
    ``reports.managers_see_profit`` on, which is how every shop behaved before the setting existed,
    so it defaults to on. The owner is found by what the role can do, not by the name of the role.
    """

    async def __call__(
        self, ctx: Annotated[TenantContext, Depends(require_permission("pos:override"))]
    ) -> TenantContext:
        if "settings:write" in ctx.permission_codes:
            return ctx
        # Imported here, like dead_stock_report: a module-level import would add one more edge.
        from app.modules.settings.service import SettingsService

        allowed = (await SettingsService(ctx.session, ctx.tenant_id).resolve(PROFIT_SETTING)).value
        if allowed is not True:
            raise PermissionDeniedError("the shop owner keeps the profit reports to themselves")
        return ctx


ProfitCtx = Annotated[TenantContext, Depends(_ProfitGate())]


def _parse(value: str, what: str) -> datetime:
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{what} must be an ISO date or datetime") from None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


@router.get("")
async def profit_summary(
    ctx: ProfitCtx, start: str, end: str, channel: str | None = None
) -> dict[str, Any]:
    """Gross profit, expenses, net profit and stock at cost over [start, end)."""
    return await ProfitReportService.summary(
        ctx.session,
        ctx.tenant_id,
        start=_parse(start, "start"),
        end=_parse(end, "end"),
        channel=channel,
    )


@router.get("/by-variant")
async def profit_by_variant(
    ctx: ProfitCtx,
    start: str,
    end: str,
    channel: str | None = None,
    season: str | None = None,
    material: str | None = None,
    brand_id: UUID | None = None,
) -> dict[str, Any]:
    """One row per model, colour and size, most profitable first; optionally one season, fabric or
    brand."""
    return await ProfitReportService.by_variant(
        ctx.session,
        ctx.tenant_id,
        start=_parse(start, "start"),
        end=_parse(end, "end"),
        channel=channel,
        season=season,
        material=material,
        brand_id=brand_id,
    )
