"""MARKETING analytics — read-only aggregate queries.

Every function returns plain dicts (JSON-ready, Decimal-free) and filters
``tenant_id`` explicitly (RLS protects too, but never rely on it alone).
Revenue numbers come from last-touch attributions; the orders window excludes
cancelled / draft / refunded orders.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketing.models import Attribution, Campaign, Conversion, Touchpoint
from app.modules.orders.models import Order

# Order statuses that never count as revenue.
_EXCLUDED_ORDER_STATUSES = ("cancelled", "draft", "refunded")

# Some seeds store this Arabic placeholder as the campaign name; normalize it.
_UNLINKED_NAME = "unlinked"
_PLACEHOLDER_NAMES = {_UNLINKED_NAME, "غير مرتبط"}


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _normalize_campaign_name(name: str | None) -> str:
    return _UNLINKED_NAME if not name or name in _PLACEHOLDER_NAMES else name


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


async def revenue_by_campaign(
    session: AsyncSession, tenant_id: UUID, days: int = 30
) -> list[dict]:
    """[{campaign_id, campaign_name, revenue, conversions}] via last-touch.

    Touchpoints without a campaign group under campaign_id=None and the name
    ``"unlinked"``.
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
        {
            "campaign_id": row.campaign_id,
            "campaign_name": _normalize_campaign_name(row.campaign_name),
            "revenue": float(row.revenue),
            "conversions": int(row.conversions),
        }
        for row in rows
    ]


async def orders_summary(session: AsyncSession, tenant_id: UUID, days: int = 30) -> dict:
    """{orders_count, revenue, aov} over non-cancelled orders in the window."""
    stmt = select(
        func.count(Order.id),
        func.coalesce(func.sum(Order.grand_total), 0),
    ).where(
        Order.tenant_id == tenant_id,
        Order.created_at >= _cutoff(days),
        Order.status.not_in(_EXCLUDED_ORDER_STATUSES),
    )
    count, revenue = (await session.execute(stmt)).one()
    orders_count = int(count or 0)
    revenue = float(revenue or 0)
    aov = revenue / orders_count if orders_count else 0.0
    return {"orders_count": orders_count, "revenue": revenue, "aov": aov}


async def daily_orders(session: AsyncSession, tenant_id: UUID, days: int = 30) -> list[dict]:
    """[{day, orders, revenue}] grouped by day (date_trunc, tz-aware)."""
    day = func.date_trunc("day", Order.created_at).label("day")
    stmt = (
        select(
            day,
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.grand_total), 0).label("revenue"),
        )
        .where(
            Order.tenant_id == tenant_id,
            Order.created_at >= _cutoff(days),
            Order.status.not_in(_EXCLUDED_ORDER_STATUSES),
        )
        .group_by(day)
        .order_by(day)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "day": row.day.date().isoformat(),
            "orders": int(row.orders),
            "revenue": float(row.revenue),
        }
        for row in rows
    ]


async def campaign_roas(session: AsyncSession, tenant_id: UUID, days: int = 30) -> list[dict]:
    """[{campaign_id, name, spend, revenue, roas}].

    spend = campaign.budget (nullable -> 0); roas = revenue / spend when
    spend > 0 else None. Unlinked revenue (no campaign) is skipped.
    """
    revenue_rows = await revenue_by_campaign(session, tenant_id, days=days)
    campaign_ids = [row["campaign_id"] for row in revenue_rows if row["campaign_id"]]
    if not campaign_ids:
        return []

    rows = (
        await session.execute(
            select(Campaign.id, Campaign.name, Campaign.budget).where(
                Campaign.tenant_id == tenant_id, Campaign.id.in_(campaign_ids)
            )
        )
    ).all()
    campaigns = {
        row.id: (_normalize_campaign_name(row.name), float(row.budget) if row.budget else 0.0)
        for row in rows
    }

    result: list[dict] = []
    for row in revenue_rows:
        if not row["campaign_id"]:
            continue
        name, spend = campaigns.get(row["campaign_id"], (row["campaign_name"], 0.0))
        roas = row["revenue"] / spend if spend > 0 else None
        result.append(
            {
                "campaign_id": row["campaign_id"],
                "name": name,
                "spend": spend,
                "revenue": row["revenue"],
                "roas": roas,
            }
        )
    return result
