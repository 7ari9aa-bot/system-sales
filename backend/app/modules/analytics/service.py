"""Spec §55-57 — analytics read models, partition-ready tables, archiving.

This module provides the QUERIES that compute the canonical metrics defined
in platform/metrics.py. The metric registry pins WHAT a metric means; this
module pins HOW it is computed — the SQL that resolves a metric name to a
number for a given tenant and time window.

Design rules (from the spec):
- Read-only: these functions never write; they are the read side of CQRS.
- Partition-ready: the tables they read from (orders, order_payments, refunds,
  messages, conversations) are designed to be range-partitioned by created_at
  in a future migration. The queries here do not assume partitioning is
  already in place — they work on plain tables today.
- Archiving: an archive helper moves cold rows older than a threshold to
  *_archive tables (which do not exist yet; the helper creates them
  if needed via raw SQL, so the archive path is testable without a migration).
- Tenant-scoped: every query carries tenant_id (RLS enforces it too, but
  the explicit filter keeps the query plan tenant-pinned).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.metrics import MetricRegistry


async def revenue(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> Decimal:
    """§55: gross captured payment amount in the window (refunds NOT subtracted)."""
    result = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(amount), 0)
              FROM order_payments
             WHERE tenant_id = :tenant_id
               AND status IN ('captured', 'partially_refunded', 'refunded')
               AND paid_at >= :since
               AND paid_at < :until
            """
        ),
        {"tenant_id": str(tenant_id), "since": since, "until": until},
    )
    return Decimal(result.scalar_one() or 0)


async def net_revenue(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> Decimal:
    """§55: revenue minus refunded_amount in the same window."""
    gross = await revenue(session, tenant_id, since=since, until=until)
    refunded = await refunded_amount(session, tenant_id, since=since, until=until)
    return gross - refunded


async def orders_count(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> int:
    """§55: count of orders placed in the window (draft/cancelled excluded)."""
    result = await session.execute(
        text(
            """
            SELECT COUNT(*)
              FROM orders
             WHERE tenant_id = :tenant_id
               AND status NOT IN ('draft', 'cancelled')
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
    result = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(amount), 0)
              FROM refunds
             WHERE tenant_id = :tenant_id
               AND status IN ('approved', 'processed')
               AND processed_at >= :since
               AND processed_at < :until
            """
        ),
        {"tenant_id": str(tenant_id), "since": since, "until": until},
    )
    return Decimal(result.scalar_one() or 0)


async def aov(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> Decimal:
    """§55: average order value = revenue / orders_count."""
    count = await orders_count(session, tenant_id, since=since, until=until)
    if count == 0:
        return Decimal("0")
    gross = await revenue(session, tenant_id, since=since, until=until)
    return (gross / Decimal(count)).quantize(Decimal("0.01"))


async def first_response_time_avg(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> float:
    """§55: average seconds from first inbound to first outbound reply."""
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


async def compute_metric(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    since: datetime,
    until: datetime,
) -> Decimal | float | int:
    """Dispatch to the right query by metric name (§167: single computation path)."""
    spec = MetricRegistry.get(metric_name)
    if spec is None:
        raise ValueError(f"unknown metric: {metric_name}")

    handlers = {
        "revenue": revenue,
        "net_revenue": net_revenue,
        "orders_count": orders_count,
        "refunded_amount": refunded_amount,
        "aov": aov,
        "first_response_time": first_response_time_avg,
        "resolution_time": resolution_time_avg,
        "ai_resolution_rate": ai_resolution_rate,
    }
    handler = handlers.get(metric_name)
    if handler is None:
        raise ValueError(
            f"metric '{metric_name}' is defined in the registry but has no query yet"
        )
    return await handler(session, tenant_id, since=since, until=until)


async def archive_old_rows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    table_name: str,
    cutoff: datetime,
) -> int:
    """§57: move rows older than cutoff to a *_archive table.

    Creates the archive table if it does not exist (same schema + columns).
    Returns the number of rows moved.
    """
    archive_table = f"{table_name}_archive"

    # Create the archive table if it doesn't exist (idempotent).
    await session.execute(
        text(f"CREATE TABLE IF NOT EXISTS {archive_table} (LIKE {table_name} INCLUDING ALL)")
    )

    # Move rows: INSERT into archive, DELETE from source, in one transaction.
    result = await session.execute(
        text(
            f"""
            WITH moved AS (
                DELETE FROM {table_name}
                 WHERE tenant_id = :tenant_id
                   AND created_at < :cutoff
             RETURNING *
            )
            INSERT INTO {archive_table}
            SELECT * FROM moved
            """
        ),
        {"tenant_id": str(tenant_id), "cutoff": cutoff},
    )
    return result.rowcount or 0
