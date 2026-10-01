"""Query compiler (spec §7) — metric + period → parameter-bound SQL.

THE TENANT BOUNDARY IS ASSERTED, NOT ASSUMED: every compiled statement
carries ``tenant_id = :tenant_id`` from the run context, ``_assert_scoped``
refuses to run anything that does not, and the tests try to bypass it.
No LLM ever writes or edits this SQL; the registry decides what a metric
means and this module decides how it is computed.

v1 dimensions: ``channel`` (orders.channel — the only dimension column that
exists on the compiled tables today). Any other filter or dimension raises
Unsupported — the honest answer, never a silent substitution (§4.3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.contracts import (
    AnalysisPeriod,
    MaturityStatus,
    MetricDefinition,
    MetricFact,
    Relationship,
)
from app.modules.analytics.maturity import maturity_status
from app.modules.analytics.semantic import metric


class UnsupportedFilter(Exception):
    """The requested filter/dimension has no compiled path — answer with
    UNSUPPORTED, never with a substitute metric."""


def _assert_scoped(sql: str) -> None:
    if "tenant_id = :tenant_id" not in sql:
        raise RuntimeError("compiled SQL is not tenant-scoped — refusing to run")


# name → (statement, alias carrying the channel column or None)
_STATEMENTS: dict[str, tuple[str, str | None]] = {
    # orders_placed: COALESCE(placed_at, created_at) is the declared
    # attribution timestamp (placed_at is NULLABLE in the real schema).
    "orders_placed": (
        "SELECT COUNT(*) AS value, 0 AS money_value "
        "FROM orders o "
        "WHERE o.tenant_id = :tenant_id AND o.deleted_at IS NULL "
        "AND COALESCE(o.placed_at, o.created_at) >= :start "
        "AND COALESCE(o.placed_at, o.created_at) < :end",
        "o",
    ),
    "delivered_revenue": (
        "SELECT COUNT(DISTINCT o.id) AS value, "
        "COALESCE(SUM(o.grand_total), 0) AS money_value "
        "FROM shipments s JOIN orders o ON o.id = s.order_id "
        "WHERE o.tenant_id = :tenant_id AND o.deleted_at IS NULL "
        "AND s.tenant_id = :tenant_id AND s.status = 'delivered' "
        "AND s.delivered_at >= :start AND s.delivered_at < :end",
        "o",
    ),
    "shipped_orders": (
        "SELECT COUNT(*) AS value, 0 AS money_value "
        "FROM shipments s "
        "WHERE s.tenant_id = :tenant_id AND s.shipped_at IS NOT NULL "
        "AND s.status IN ('picked_up', 'in_transit', 'delivered') "
        "AND s.shipped_at >= :start AND s.shipped_at < :end",
        None,
    ),
    "collected_revenue": (
        "SELECT COUNT(*) AS value, COALESCE(SUM(p.amount), 0) AS money_value "
        "FROM order_payments p "
        "WHERE p.tenant_id = :tenant_id AND p.paid_at IS NOT NULL "
        "AND p.paid_at >= :start AND p.paid_at < :end",
        None,
    ),
    "refund_amount": (
        "SELECT COUNT(*) AS value, COALESCE(SUM(r.amount), 0) AS money_value "
        "FROM refunds r "
        "WHERE r.tenant_id = :tenant_id AND r.processed_at IS NOT NULL "
        "AND r.processed_at >= :start AND r.processed_at < :end",
        None,
    ),
}


def compile_metric(
    name: str,
    tenant_id: uuid.UUID,
    period: AnalysisPeriod,
    *,
    channel: str | None = None,
) -> tuple[str, dict]:
    """Compile one metric's statement; tenant-scoped or it does not compile."""
    definition: MetricDefinition = metric(name)
    if definition.source == "composite":
        raise UnsupportedFilter(f"{name} is composite — compute from its components")
    if name not in _STATEMENTS:
        raise UnsupportedFilter(f"metric {name} has no compiled path")
    sql, channel_alias = _STATEMENTS[name]
    if channel is not None:
        if "channel" not in definition.dimensions_allowed or channel_alias is None:
            raise UnsupportedFilter(f"metric {name} cannot filter by channel")
        sql += f" AND {channel_alias}.channel = :channel"
    _assert_scoped(sql)
    params: dict = {
        "tenant_id": str(tenant_id),
        "start": period.start,
        "end": period.end,
    }
    if channel is not None:
        params["channel"] = channel
    return sql, params


def _maturity_for(definition: MetricDefinition) -> MaturityStatus:
    if definition.maturity_policy.kind == "immediate":
        return MaturityStatus.MATURE
    # Resolution curves (§6.6) need accumulated status history; until the
    # curves exist the honest status for a settling metric is PARTIAL.
    return maturity_status(None)


async def compute_fact(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    name: str,
    period: AnalysisPeriod,
    *,
    channel: str | None = None,
    fact_id: str,
) -> MetricFact:
    """Run the compiled statement and return the fact with its provenance."""
    definition = metric(name)
    sql, params = compile_metric(name, tenant_id, period, channel=channel)
    row = (await session.execute(text(sql), params)).one()
    is_money = definition.semantic_type == "money"
    value = Decimal(str(row.money_value if is_money else row.value))
    now = datetime.now(UTC)
    return MetricFact(
        id=fact_id,
        metric=name,
        value=value,
        unit="money" if is_money else "count",
        period=period,
        filters={"channel": channel} if channel else {},
        source=definition.source,
        computed_at=now,
        data_as_of=now,
        maturity_status=_maturity_for(definition),
        metric_version=definition.version,
        relationship=Relationship.OBSERVED,
    )
