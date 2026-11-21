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

from app.modules.catalog.apparel.matrix import COLOR_AXIS, SIZE_AXIS
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
    ) -> dict[str, Any]:
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
        # Discount already inside the line nets (a per-line percentage) is not taken off twice:
        # only the invoice-level part, the discount beyond what the line nets already reflect.
        stmt = (
            select(
                ProductVariant.id.label("variant_id"),
                Product.title.label("model"),
                ProductVariant.option_values[SIZE_AXIS].astext.label("size"),
                ProductVariant.option_values[COLOR_AXIS].astext.label("colour"),
                func.sum(lines.c.units).label("units_sold"),
                func.sum(lines.c.net - share).label("sales_net"),
                func.coalesce(func.sum(costs.c.cost), 0).label("cost"),
                func.coalesce(func.sum(costs.c.units_without_cost), 0).label("units_without_cost"),
                func.coalesce(func.sum(returns.c.units_returned), 0).label("units_returned"),
                func.coalesce(func.sum(returns.c.refund), 0).label("refund"),
                func.coalesce(func.sum(shelved.c.units_shelved), 0).label("units_shelved"),
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
            .group_by(
                ProductVariant.id,
                Product.title,
                ProductVariant.option_values[SIZE_AXIS].astext,
                ProductVariant.option_values[COLOR_AXIS].astext,
            )
        )
        result = (await session.execute(stmt)).all()

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
            revenue = sales_net - Decimal(r.refund or 0)
            cost = booked_cost - cost_back
            profit = revenue - cost
            rows.append(
                {
                    "variant_id": str(r.variant_id),
                    "model": r.model,
                    "size": r.size,
                    "colour": r.colour,
                    "units_sold": units,
                    "units_returned": returned,
                    "revenue": _s(revenue),
                    "cost": _s(cost),
                    "gross_profit": _s(profit),
                    "margin_pct": _s(profit / revenue * 100) if revenue > 0 else None,
                    "units_without_cost": without_cost,
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
#: What the shop paid for its stock and what it earns on it is not for a till operator: the same
#: manager gate as the cashier custody report, which also names people and money.
ProfitCtx = Annotated[TenantContext, Depends(require_permission("pos:override"))]


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
    ctx: ProfitCtx, start: str, end: str, channel: str | None = None
) -> dict[str, Any]:
    """One row per model, colour and size, most profitable first."""
    return await ProfitReportService.by_variant(
        ctx.session,
        ctx.tenant_id,
        start=_parse(start, "start"),
        end=_parse(end, "end"),
        channel=channel,
    )
