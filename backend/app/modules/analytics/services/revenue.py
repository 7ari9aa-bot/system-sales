"""Revenue, order counts, refunds, and daily series analytics readers."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _resolve_tenant_currency(session, tenant_id):
    from app.modules.analytics import service as analytics_service
    return await analytics_service.resolve_tenant_currency(session, tenant_id)
from ._common import (
    _GROSS_PAYMENT_STATUSES,
    _REFUND_STATUSES,
    _UNPLACED_ORDER_STATUSES,
    ZERO,
    _aov,
    _count_by_bucket,
    _money,
    _sum_by_bucket,
    bind_window,
    net_of,
    resolve_report_timezone,
)


async def revenue(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> Decimal:
    """§55: gross captured payment amount in the window (refunds NOT subtracted)."""
    since, until = bind_window(since, until)
    result = await session.execute(
        text(
            f"""
            SELECT COALESCE(SUM(amount), 0)
              FROM order_payments
             WHERE tenant_id = :tenant_id
               AND status IN {_GROSS_PAYMENT_STATUSES}
               AND paid_at >= :since
               AND paid_at < :until
            """
        ),
        {"tenant_id": str(tenant_id), "since": since, "until": until},
    )
    return _money(result.scalar_one() or 0)


async def net_revenue(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> Decimal:
    """§55: revenue minus refunded_amount in the same window, floored at zero."""
    from app.modules.analytics import service as analytics_service
    gross = await analytics_service.revenue(session, tenant_id, since=since, until=until)
    refunded = await analytics_service.refunded_amount(session, tenant_id, since=since, until=until)
    net, _excess = net_of(gross, refunded)
    return net


async def orders_count(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> int:
    """§55: count of orders placed in the window (draft/cancelled excluded)."""
    since, until = bind_window(since, until)
    result = await session.execute(
        text(
            f"""
            SELECT COUNT(*)
              FROM orders
             WHERE tenant_id = :tenant_id
               AND status NOT IN {_UNPLACED_ORDER_STATUSES}
               AND placed_at >= :since
               AND placed_at < :until
            """
        ),
        {"tenant_id": str(tenant_id), "since": since, "until": until},
    )
    return int(result.scalar_one() or 0)


async def refunded_amount(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> Decimal:
    """§55: total refunded money in the window."""
    since, until = bind_window(since, until)
    result = await session.execute(
        text(
            f"""
            SELECT COALESCE(SUM(amount), 0)
              FROM refunds
             WHERE tenant_id = :tenant_id
               AND status IN {_REFUND_STATUSES}
               AND COALESCE(processed_at, created_at) >= :since
               AND COALESCE(processed_at, created_at) < :until
            """
        ),
        {"tenant_id": str(tenant_id), "since": since, "until": until},
    )
    return _money(result.scalar_one())


async def aov(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> Decimal:
    """§55: AVERAGE ORDER VALUE = GROSS revenue / orders_count."""
    from app.modules.analytics import service as analytics_service
    count = await analytics_service.orders_count(session, tenant_id, since=since, until=until)
    gross = await analytics_service.revenue(session, tenant_id, since=since, until=until)
    return _aov(gross, count)


async def revenue_summary(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
    timezone: str | None = None,
) -> dict:
    """Every money figure for one window, each labelled with its own family."""
    from app.modules.analytics import service as analytics_service
    since, until = bind_window(since, until)
    gross = await analytics_service.revenue(session, tenant_id, since=since, until=until)
    refunded = await analytics_service.refunded_amount(session, tenant_id, since=since, until=until)
    net, excess = net_of(gross, refunded)
    count = await analytics_service.orders_count(session, tenant_id, since=since, until=until)
    zone = await analytics_service.resolve_report_timezone(session, tenant_id, timezone)
    return {
        "currency": await analytics_service.resolve_tenant_currency(session, tenant_id),
        "timezone": str(zone),
        "timezone_source": zone.source,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "gross_revenue": gross,
        "refunded_amount": refunded,
        "net_revenue": net,
        "refund_excess": excess,
        "orders_count": count,
        "gross_aov": _aov(gross, count),
        "net_aov": _aov(net, count),
    }


async def daily_revenue_series(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
    timezone: str | None = None,
) -> list[dict]:
    """Gross/net revenue, refunds and order counts per MERCHANT day (gap M10)."""
    from app.modules.analytics import service as analytics_service
    since, until = bind_window(since, until)
    zone = str(await analytics_service.resolve_report_timezone(session, tenant_id, timezone))
    common = {"tenant_id": str(tenant_id), "since": since, "until": until, "tz": zone}

    gross = await _sum_by_bucket(
        session,
        f"""
        SELECT date_trunc('day', paid_at AT TIME ZONE CAST(:tz AS text)) AS day,
               COALESCE(SUM(amount), 0) AS value
          FROM order_payments
         WHERE tenant_id = :tenant_id
           AND status IN {_GROSS_PAYMENT_STATUSES}
           AND paid_at >= :since
           AND paid_at < :until
         GROUP BY 1
        """,
        common,
    )
    refunded = await _sum_by_bucket(
        session,
        f"""
        SELECT date_trunc('day',
                          COALESCE(processed_at, created_at) AT TIME ZONE CAST(:tz AS text)
                 ) AS day,
               COALESCE(SUM(amount), 0) AS value
          FROM refunds
         WHERE tenant_id = :tenant_id
           AND status IN {_REFUND_STATUSES}
           AND COALESCE(processed_at, created_at) >= :since
           AND COALESCE(processed_at, created_at) < :until
         GROUP BY 1
        """,
        common,
    )
    counts = await _count_by_bucket(
        session,
        f"""
        SELECT date_trunc('day', placed_at AT TIME ZONE CAST(:tz AS text)) AS day,
               COUNT(*) AS value
          FROM orders
         WHERE tenant_id = :tenant_id
           AND status NOT IN {_UNPLACED_ORDER_STATUSES}
           AND placed_at >= :since
           AND placed_at < :until
         GROUP BY 1
        """,
        common,
    )

    series: list[dict] = []
    for day in sorted(set(gross) | set(refunded) | set(counts)):
        day_gross = gross.get(day, ZERO)
        day_refunded = refunded.get(day, ZERO)
        day_count = counts.get(day, 0)
        net, excess = net_of(day_gross, day_refunded)
        series.append(
            {
                "day": day.isoformat(),
                "gross_revenue": day_gross,
                "refunded_amount": day_refunded,
                "net_revenue": net,
                "refund_excess": excess,
                "orders_count": day_count,
            }
        )
    return series
