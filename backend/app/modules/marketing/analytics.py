"""MARKETING analytics — read-only aggregate queries.

Every function returns plain dicts (JSON-ready, Decimal-free) and filters
``tenant_id`` explicitly (RLS protects too, but never rely on it alone).
Attribution figures (revenue by source/campaign, ROAS) come from last-touch
attributions. Order money, daily buckets and stock bands are NOT computed here:
they delegate to ``app/modules/analytics/service.py``, which owns the canonical
read models (§167 — the same number must not be computed twice).

Money maths is done in Decimal inside that service and only cast at the edge.
Ratios (ROAS) are labelled with the denominator that produced them — see
``roas_row``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketing.models import Attribution, Campaign, Conversion, Touchpoint
from app.modules.orders.models import Order

# What the ratio on a ROI row was divided by. §167 (metric definitions) demands a
# metric carry its own source, and in this schema the only source is a plan.
BASIS_PLANNED_BUDGET = "planned_budget"
BASIS_ACTUAL_SPEND = "actual_spend"

# Some seeds store this Arabic placeholder as the campaign name; normalize it.
_UNLINKED_NAME = "unlinked"
_PLACEHOLDER_NAMES = {_UNLINKED_NAME, "غير مرتبط"}


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _normalize_campaign_name(name: str | None) -> str:
    return _UNLINKED_NAME if not name or name in _PLACEHOLDER_NAMES else name


def _money(value: object) -> Decimal:
    """Coerce a driver-returned money value to Decimal without going via float."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value if value is not None else 0))


def _wire(value: Decimal) -> float:
    """Money crosses to JSON as a bare cast — no arithmetic happens in float."""
    return float(value)


def _window(days: int) -> tuple[datetime, datetime]:
    """The trailing ``days`` window as instants; the DAY LABEL is the service's."""
    until = datetime.now(UTC)
    return until - timedelta(days=days), until


async def _canonical():
    """THE marketing -> analytics edge, and the only place marketing asks it.

    Merchant-day buckets, the gross/net refund families and the stock bands are
    decided in ``app/modules/analytics/service.py`` (§167: one number, one
    computation path). Function scope keeps this off the module-scope
    service-import ratchet.
    """
    from app.modules.analytics import service as analytics_service

    return analytics_service


async def revenue_by_source(
    session: AsyncSession, tenant_id: UUID, days: int = 30
) -> list[dict]:
    """[{source, revenue, conversions}] via last-touch attributions.

    Sources with no UTM on the touchpoint fall back to ``"direct"``.
    """
    occurred_at = func.coalesce(Conversion.occurred_at, Conversion.created_at)
    source = func.coalesce(Touchpoint.source, sa.literal("direct")).label("source")
    stmt = (
        select(
            source,
            func.coalesce(func.sum(Attribution.credited_value), 0).label("revenue"),
            func.count(func.distinct(Attribution.conversion_id)).label("conversions"),
        )
        .join(Conversion, Conversion.id == Attribution.conversion_id)
        .join(Touchpoint, Touchpoint.id == Attribution.touchpoint_id)
        .where(
            Attribution.tenant_id == tenant_id,
            Conversion.tenant_id == tenant_id,
            Touchpoint.tenant_id == tenant_id,
            Attribution.model == "last_touch",
            occurred_at >= _cutoff(days),
        )
        .group_by(source)
        .order_by(sa.desc("revenue"))
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "source": row.source,
            "revenue": float(row.revenue),
            "conversions": int(row.conversions),
        }
        for row in rows
    ]


async def _revenue_by_campaign_decimals(
    session: AsyncSession, tenant_id: UUID, days: int
) -> list[tuple[UUID | None, str, Decimal, int]]:
    """(campaign_id, name, revenue, conversions) with revenue as Decimal.

    Money leaves this helper as Decimal and as float only at the JSON edge, so
    ROAS never divides a float.
    """
    occurred_at = func.coalesce(Conversion.occurred_at, Conversion.created_at)
    stmt = (
        select(
            Campaign.id.label("campaign_id"),
            Campaign.name.label("campaign_name"),
            func.coalesce(func.sum(Attribution.credited_value), 0).label("revenue"),
            func.count(func.distinct(Attribution.conversion_id)).label("conversions"),
        )
        .join(Conversion, Conversion.id == Attribution.conversion_id)
        .join(Touchpoint, Touchpoint.id == Attribution.touchpoint_id)
        .outerjoin(
            Campaign,
            sa.and_(Campaign.id == Touchpoint.campaign_id, Campaign.tenant_id == tenant_id),
        )
        .where(
            Attribution.tenant_id == tenant_id,
            Conversion.tenant_id == tenant_id,
            Touchpoint.tenant_id == tenant_id,
            Attribution.model == "last_touch",
            occurred_at >= _cutoff(days),
        )
        .group_by(Campaign.id, Campaign.name)
        .order_by(sa.desc("revenue"))
    )
    rows = (await session.execute(stmt)).all()
    return [
        (
            row.campaign_id,
            _normalize_campaign_name(row.campaign_name),
            _money(row.revenue),
            int(row.conversions),
        )
        for row in rows
    ]


async def revenue_by_campaign(
    session: AsyncSession, tenant_id: UUID, days: int = 30
) -> list[dict]:
    """[{campaign_id, campaign_name, revenue, conversions}] via last-touch.

    Touchpoints without a campaign group under campaign_id=None and the name
    ``"unlinked"``.
    """
    rows = await _revenue_by_campaign_decimals(session, tenant_id, days)
    return [
        {
            "campaign_id": campaign_id,
            "campaign_name": name,
            "revenue": float(revenue),
            "conversions": conversions,
        }
        for campaign_id, name, revenue, conversions in rows
    ]


async def orders_summary(
    session: AsyncSession, tenant_id: UUID, days: int = 30, timezone: str | None = None
) -> dict:
    """Every money figure for the trailing window, each named for its family.

    This used to sum ``orders.grand_total`` and call the result ``revenue``. That
    number was gross of partial refunds yet dropped whole ``refunded`` orders, so
    a merchant comparing this screen with the analytics dashboard saw two
    different "revenues" — gross/net/refunded/excess are separate keys now, and
    the currency label is the tenant's.
    """
    since, until = _window(days)
    summary = await (
        await _canonical()
    ).revenue_summary(session, tenant_id, since=since, until=until, timezone=timezone)
    return {
        "orders_count": summary["orders_count"],
        "gross_revenue": _wire(summary["gross_revenue"]),
        "refunded_amount": _wire(summary["refunded_amount"]),
        "net_revenue": _wire(summary["net_revenue"]),
        "refund_excess": _wire(summary["refund_excess"]),
        "gross_aov": _wire(summary["gross_aov"]),
        "net_aov": _wire(summary["net_aov"]),
        "currency": summary["currency"],
        "timezone": summary["timezone"],
    }


async def daily_orders(
    session: AsyncSession, tenant_id: UUID, days: int = 30, timezone: str | None = None
) -> list[dict]:
    """[{day, orders, gross_revenue, net_revenue, ...}] per MERCHANT day.

    This function used to truncate the day itself with no zone in the expression,
    so the bucket boundary was UTC midnight and every sale before 04:00 local sat
    on the previous day here while the analytics dashboard put it on the right
    one (gap M10). ``timezone`` is forwarded unresolved —
    ``timekit.resolve_timezone`` owns the fallback chain (caller zone ->
    ANALYTICS_TIMEZONE -> UTC) in one place.
    """
    since, until = _window(days)
    rows = await (
        await _canonical()
    ).daily_revenue_series(session, tenant_id, since=since, until=until, timezone=timezone)
    return [
        {
            "day": row["day"],
            "orders": row["orders_count"],
            "gross_revenue": _wire(row["gross_revenue"]),
            "refunded_amount": _wire(row["refunded_amount"]),
            "net_revenue": _wire(row["net_revenue"]),
            "refund_excess": _wire(row["refund_excess"]),
        }
        for row in rows
    ]


def _ratio(numerator: Decimal, denominator: Decimal | None) -> float | None:
    """A ratio computed in Decimal; ``None`` when it cannot exist.

    0.0 is not an acceptable substitute for None here — it reads as "returned
    nothing", when the truth is "there is no denominator to divide by".
    """
    if denominator is None or denominator <= 0:
        return None
    return float((numerator / denominator).quantize(Decimal("0.0001")))


def roas_row(
    *,
    campaign_id: UUID | None,
    name: str,
    revenue: Decimal,
    planned_budget: Decimal | None,
    actual_spend: Decimal | None = None,
) -> dict:
    """One ROI row, named for the denominator its ratio actually used.

    §167: a metric carries its own source. ``campaigns.budget`` is what was
    PLANNED, and this schema records no burned spend, so the honest figure is
    ``budget_roas`` and ``basis`` says so. ``spend_roas`` stays None until
    :func:`campaign_actual_spend` can produce a number.
    """
    basis = BASIS_ACTUAL_SPEND if actual_spend is not None else BASIS_PLANNED_BUDGET
    return {
        "campaign_id": campaign_id,
        "name": name,
        "revenue": float(revenue),
        "planned_budget": None if planned_budget is None else float(planned_budget),
        "actual_spend": None if actual_spend is None else float(actual_spend),
        "basis": basis,
        "budget_roas": _ratio(revenue, planned_budget),
        "spend_roas": _ratio(revenue, actual_spend),
    }


async def campaign_actual_spend(
    session: AsyncSession, tenant_id: UUID, campaign_ids: list[UUID]
) -> dict[UUID, Decimal]:
    """THE SPEND SEAM: money actually burned per campaign.

    Nothing in this schema burns money — ``campaigns``/``ad_sets`` hold a planned
    budget, and no channel delivery-metrics sync exists to write spend. This
    returns {} deliberately rather than passing budget through: the only correct
    answer today is that there is none. A Meta Marketing API ``adsinsights`` sync
    replaces THIS function and nothing else.
    """
    return {}


async def campaign_budget_roas(
    session: AsyncSession, tenant_id: UUID, days: int = 30
) -> list[dict]:
    """[{campaign_id, name, revenue, planned_budget, budget_roas, basis}].

    Plan-based return, NOT return on ad spend — see :func:`roas_row`. Revenue is
    the last-touch credited figure; unlinked revenue (no campaign) is skipped
    because it has no plan to divide by.
    """
    rows = await _revenue_by_campaign_decimals(session, tenant_id, days)
    campaign_ids = [row[0] for row in rows if row[0] is not None]
    if not campaign_ids:
        return []

    budget_rows = (
        await session.execute(
            select(Campaign.id, Campaign.budget).where(
                Campaign.tenant_id == tenant_id, Campaign.id.in_(campaign_ids)
            )
        )
    ).all()
    budgets = {row.id: (None if row.budget is None else _money(row.budget)) for row in budget_rows}
    spend = await campaign_actual_spend(session, tenant_id, list(campaign_ids))

    return [
        roas_row(
            campaign_id=campaign_id,
            name=name,
            revenue=revenue,
            planned_budget=budgets.get(campaign_id),
            actual_spend=spend.get(campaign_id),
        )
        for campaign_id, name, revenue, _conversions in rows
        if campaign_id is not None
    ]


async def dashboard_summary(session: AsyncSession, tenant_id: UUID) -> dict:
    """One-call aggregate for the dashboard home screen."""

    from app.modules.catalog.models import Product
    from app.modules.conversations.models import Conversation
    from app.modules.customers.models import Customer

    orders = await orders_summary(session, tenant_id, days=30)

    conv_open = (
        await session.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.tenant_id == tenant_id, Conversation.status == "open")
        )
    ).scalar_one()
    conv_unread = (
        await session.execute(
            select(func.coalesce(func.sum(Conversation.unread_count), 0)).where(
                Conversation.tenant_id == tenant_id
            )
        )
    ).scalar_one()
    customers_count = (
        await session.execute(
            select(func.count()).select_from(Customer).where(Customer.tenant_id == tenant_id)
        )
    ).scalar_one()
    products_active = (
        await session.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.tenant_id == tenant_id, Product.status == "active")
        )
    ).scalar_one()
    ai_orders = (
        await session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.tenant_id == tenant_id,
                Order.channel == "ai",
                Order.created_at >= _cutoff(30),
            ),
        )
    ).scalar_one()
    health = await (await _canonical()).stock_health(session, tenant_id)

    return {
        "orders": orders,
        "ai_orders_30d": ai_orders,
        "conversations": {"open": conv_open, "unread": int(conv_unread)},
        "customers": customers_count,
        "products_active": products_active,
        # Two bands, named: a sold-out shelf used to be counted as "low stock",
        # which made the alert mostly noise and hid what needed reordering.
        "low_stock_count": health["low_stock_count"],
        "out_of_stock_count": health["out_of_stock_count"],
        "low_stock_threshold": health["low_stock_threshold"],
    }
