"""Stock health and canonical metric computation dispatchers."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from ._common import (
    LOW_STOCK_THRESHOLD,
    ZERO,
    _money,
    bind_count,
    bind_window,
)
from .revenue import (
    aov,
    net_revenue,
    orders_count,
    refunded_amount,
    revenue,
)


async def stock_health(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    low_stock_threshold: int = LOW_STOCK_THRESHOLD,
) -> dict:
    """Replenishment signal, split so an empty shelf is not "low stock" noise."""
    threshold = bind_count(low_stock_threshold, "low_stock_threshold")
    result = await session.execute(
        text(
            """
            SELECT COUNT(*) FILTER (WHERE available <= 0)               AS out_of_stock,
                   COUNT(*) FILTER (WHERE available > 0
                                      AND available <= :threshold)      AS low_stock,
                   COUNT(*)                                             AS tracked
              FROM (
                SELECT on_hand - reserved AS available
                  FROM inventory_balances
                 WHERE tenant_id = :tenant_id
              ) balances
            """
        ),
        {"tenant_id": str(tenant_id), "threshold": threshold},
    )
    row = result.one()
    out_of_stock = int(row[0] or 0)
    low = int(row[1] or 0)
    tracked = int(row[2] or 0)
    return {
        "low_stock_threshold": threshold,
        "low_stock_count": low,
        "out_of_stock_count": out_of_stock,
        "healthy_count": tracked - low - out_of_stock,
    }


async def first_response_time_avg(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> float:
    """§55: average seconds from first inbound to first outbound reply."""
    since, until = bind_window(since, until)
    result = await session.execute(
        text(
            """
            WITH pairs AS (
              SELECT c.id AS conversation_id,
                     MIN(CASE WHEN m.direction = 'inbound' THEN m.created_at END) AS first_in,
                     MIN(CASE WHEN m.direction = 'outbound' THEN m.created_at END) AS first_out
                FROM conversations c
                JOIN messages m ON m.conversation_id = c.id
               WHERE c.tenant_id = :tenant_id
                 AND m.created_at >= :since
                 AND m.created_at < :until
               GROUP BY c.id
            )
            SELECT AVG(EXTRACT(EPOCH FROM (first_out - first_in)))
              FROM pairs
             WHERE first_in IS NOT NULL AND first_out IS NOT NULL
            """
        ),
        {"tenant_id": str(tenant_id), "since": since, "until": until},
    )
    return float(result.scalar_one() or 0)


async def resolution_time_avg(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> float:
    """§55: average seconds from first inbound to conversation closed."""
    since, until = bind_window(since, until)
    result = await session.execute(
        text(
            """
            WITH pairs AS (
              SELECT c.id AS conversation_id,
                     MIN(CASE WHEN m.direction = 'inbound' THEN m.created_at END) AS first_in,
                     MAX(c.updated_at) AS closed_at
                FROM conversations c
                JOIN messages m ON m.conversation_id = c.id
               WHERE c.tenant_id = :tenant_id
                 AND c.status = 'closed'
                 AND m.created_at >= :since
                 AND m.created_at < :until
               GROUP BY c.id
            )
            SELECT AVG(EXTRACT(EPOCH FROM (closed_at - first_in)))
              FROM pairs
             WHERE first_in IS NOT NULL
            """
        ),
        {"tenant_id": str(tenant_id), "since": since, "until": until},
    )
    return float(result.scalar_one() or 0)


async def ai_resolution_rate(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> float:
    """§55: share of closed conversations resolved by AI (no human agent message)."""
    since, until = bind_window(since, until)
    result = await session.execute(
        text(
            """
            WITH closed AS (
              SELECT c.id
                FROM conversations c
               WHERE c.tenant_id = :tenant_id
                 AND c.status = 'closed'
                 AND c.created_at >= :since
                 AND c.created_at < :until
            ),
            with_human AS (
              SELECT DISTINCT m.conversation_id
                FROM messages m
                JOIN closed c ON c.id = m.conversation_id
               WHERE m.sender_type = 'agent'
            )
            SELECT
              (SELECT COUNT(*) FROM closed) AS total,
              (SELECT COUNT(*) FROM with_human) AS human_count
            """
        ),
        {"tenant_id": str(tenant_id), "since": since, "until": until},
    )
    row = result.one()
    total = int(row[0] or 0)
    if total == 0:
        return 0.0
    human = int(row[1] or 0)
    return round((total - human) / total, 4)


async def conversion_rate(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> float:
    """§55/§167: purchase conversions divided by touchpoints in the window."""
    since, until = bind_window(since, until)
    row = (
        await session.execute(
            text(
                """
                WITH purchases AS (
                  SELECT COUNT(*) AS n
                    FROM conversions
                   WHERE tenant_id = :tenant_id
                     AND type = 'purchase'
                     AND COALESCE(occurred_at, created_at) >= :since
                     AND COALESCE(occurred_at, created_at) < :until
                ),
                touched AS (
                  SELECT COUNT(*) AS n
                    FROM touchpoints
                   WHERE tenant_id = :tenant_id
                     AND created_at >= :since
                     AND created_at < :until
                )
                SELECT purchases.n, touched.n FROM purchases, touched
                """
            ),
            {"tenant_id": str(tenant_id), "since": since, "until": until},
        )
    ).one()
    conversions_n = int(row[0] or 0)
    touchpoints_n = int(row[1] or 0)
    if touchpoints_n == 0:
        return 0.0
    return round(conversions_n / touchpoints_n, 4)


async def roas(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> float | None:
    """§55/§167: return on the PLAN — last-touch credit / planned budget."""
    since, until = bind_window(since, until)
    row = (
        await session.execute(
            text(
                """
                WITH attributed AS (
                  SELECT a.touchpoint_id, a.credited_value
                    FROM attributions a
                    JOIN conversions c
                      ON c.id = a.conversion_id AND c.tenant_id = a.tenant_id
                   WHERE a.tenant_id = :tenant_id
                     AND a.model = 'last_touch'
                     AND COALESCE(c.occurred_at, c.created_at) >= :since
                     AND COALESCE(c.occurred_at, c.created_at) < :until
                ),
                linked AS (
                  SELECT DISTINCT t.campaign_id
                    FROM attributed a
                    JOIN touchpoints t
                      ON t.id = a.touchpoint_id AND t.tenant_id = :tenant_id
                   WHERE t.campaign_id IS NOT NULL
                )
                SELECT COALESCE(SUM(a.credited_value), 0) AS credited,
                       (SELECT COALESCE(SUM(cp.budget), 0)
                          FROM campaigns cp
                          JOIN linked l ON l.campaign_id = cp.id
                         WHERE cp.tenant_id = :tenant_id) AS planned_budget
                  FROM attributed a
                """
            ),
            {"tenant_id": str(tenant_id), "since": since, "until": until},
        )
    ).one()
    credited = _money(row[0])
    planned = _money(row[1])
    if planned <= ZERO:
        return None
    return float((credited / planned).quantize(Decimal("0.0001")))


async def compute_metric(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    since: datetime,
    until: datetime,
) -> Decimal | float | int | None:
    """Dispatch to the right query by metric name (§167: single computation path)."""
    from app.modules.analytics import service as analytics_service
    handler = analytics_service.METRIC_HANDLERS.get(metric_name)
    if handler is None:
        raise NotFoundError(
            f"unknown metric: {metric_name!r}. The canonical metrics (§167) are "
            f"{', '.join(sorted(analytics_service.METRIC_HANDLERS))}.",
            details={"metric": metric_name, "known": sorted(analytics_service.METRIC_HANDLERS)},
        )
    actual_handler = getattr(analytics_service, getattr(handler, "__name__", ""), handler)
    return await actual_handler(session, tenant_id, since=since, until=until)


METRIC_HANDLERS: Mapping[str, Callable[..., Awaitable[Decimal | float | int | None]]] = {
    "revenue": revenue,
    "net_revenue": net_revenue,
    "orders_count": orders_count,
    "refunded_amount": refunded_amount,
    "aov": aov,
    "first_response_time": first_response_time_avg,
    "resolution_time": resolution_time_avg,
    "ai_resolution_rate": ai_resolution_rate,
    "conversion_rate": conversion_rate,
    "roas": roas,
}
