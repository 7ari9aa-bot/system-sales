"""Spec §55-57 — analytics read models, partition-ready tables.

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
- Cold data (§55-57): the read tables here are *partition-ready* only. Actual
  retention/archiving is an OPEN gap pending a DBA-approved range-partition
  migration — there is intentionally no runtime archive helper (see the note at
  the foot of this module).
- Tenant-scoped: every query carries tenant_id (RLS enforces it too, but
  the explicit filter keeps the query plan tenant-pinned).
- Money is labelled: `revenue` is GROSS and `net_revenue` is the refund-adjusted
  figure; anything that reports both (revenue_summary, daily_revenue_series)
  uses the ``gross_``/``net_`` prefixes so a caller cannot read one as the other.
- A calendar bucket is the MERCHANT's day, never UTC midnight — see timekit.py.
  Which day the merchant lives in is now the tenant's own setting
  (``tenants.timezone``, §47/M10 remainder); `resolve_report_timezone` is the
  one place that answers, and every reader that names a zone names its source.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import resolve_tenant_currency
from app.modules.analytics.timekit import ResolvedTimezone, resolve_timezone
from app.modules.platform.metrics import MetricRegistry

# The shape a status word is allowed to have. ``_status_sql`` pastes its tokens
# into a statement, so this is the seam that keeps a filter a filter.
_STATUS_WORD = re.compile(r"^[a-z][a-z_]*$")


def _status_sql(values: Sequence[str]) -> str:
    """Render a status list as the SQL ``IN``/``NOT IN`` fragment it is.

    The fragment is built from source-controlled text rather than typed out
    again, so this module holds no second copy of the registry's answer to
    "which rows COUNT" — but building SQL by string still means the builder is
    the seam that must hold, so every token is checked against the shape a
    status can have before it reaches the statement. A quote, a parenthesis or
    an empty list raises here instead of becoming part of a query.
    """
    if not values:
        raise ValueError("an empty status list is not a filter, it is a syntax error")
    for value in values:
        if not _STATUS_WORD.fullmatch(value or ""):
            raise ValueError(f"not a status word: {value!r}")
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


# The status lists are RENDERED from the metric registry (platform/metrics.py),
# which pins revenue to exactly these: gross and net can then never disagree
# about which payments count, because there is only one answer to copy.
_GROSS_PAYMENT_STATUSES = _status_sql(MetricRegistry.get("revenue").filters["status"])
# 'approved' is counted as money going back even though only 'processed' is
# written by the order path today — see refunded_amount for the bucketing rule.
_REFUND_STATUSES = _status_sql(
    MetricRegistry.get("refunded_amount").filters["status"]
)
_UNPLACED_ORDER_STATUSES = _status_sql(
    MetricRegistry.get("orders_count").filters["status_excluded"]
)

MONEY_SCALE = Decimal("0.01")
ZERO = Decimal("0.00")

# Mirrors the threshold marketing/analytics.py used before this read model
# existed: fewer than this many units on the shelf is worth a merchant's eye.
LOW_STOCK_THRESHOLD = 2


def _money(value: object) -> Decimal:
    """Coerce a NUMERIC(14,2) aggregate to Decimal at money scale.

    Never through float: two screens must not disagree by a cent (ADR-001).
    """
    return Decimal(str(value or 0)).quantize(MONEY_SCALE)


def net_of(gross: object, refunded: object) -> tuple[Decimal, Decimal]:
    """``(net_revenue, refund_excess)`` for one window.

    Net is floored at zero and the un-subtractable remainder is returned
    separately. A window's *revenue* cannot be negative: refunds bucketed by
    when they left, not when the money arrived, so a quiet day can legitimately
    see more go back than came in. Flooring without reporting would hide that
    money, hence the second value.
    """
    collected, returned = _money(gross), _money(refunded)
    net = collected - returned
    if net < ZERO:
        return ZERO, -net
    return net, ZERO


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
    """§55: revenue minus refunded_amount in the same window, floored at zero.

    Refunds are attributed to the window the money LEFT (cash basis), which is
    what the metric registry pins `refunded_amount` to ("bucketed by
    processed_at"). The consequence is that a window can owe more refund than it
    collected, so this returns the floored figure; `revenue_summary` exposes the
    floored-away remainder as ``refund_excess`` rather than dropping it.
    """
    gross = await revenue(session, tenant_id, since=since, until=until)
    refunded = await refunded_amount(session, tenant_id, since=since, until=until)
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
    """§55: total refunded money in the window.

    Bucketed by ``processed_at`` — the window the money LEFT. An ``approved``
    refund with no ``processed_at`` yet is bucketed on ``created_at`` instead, so
    it lands in SOME window rather than vanishing from the ledger entirely.
    """
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


def _aov(money: Decimal, count: int) -> Decimal:
    """Average order value for one money family.

    The numerator family is the caller's problem on purpose: `aov` passes gross
    (the registry pins ``aov`` to refund_treatment=excluded) and
    ``revenue_summary`` calls this twice, so a gross numerator can never be
    divided by a net-derived figure and get called the same metric.
    """
    if count == 0:
        return ZERO
    return (money / Decimal(count)).quantize(MONEY_SCALE)


async def aov(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
) -> Decimal:
    """§55: AVERAGE ORDER VALUE = GROSS revenue / orders_count.

    Gross by definition — the registry's ``aov`` row says refund_treatment
    ``excluded`` and denominator ``orders_count``, so the numerator family is
    gross on both sides of the division. ``revenue_summary`` reports the
    refund-adjusted figure as ``net_aov`` under its own name.
    """
    count = await orders_count(session, tenant_id, since=since, until=until)
    gross = await revenue(session, tenant_id, since=since, until=until)
    return _aov(gross, count)


async def tenant_timezone(session: AsyncSession, tenant_id: uuid.UUID) -> str | None:
    """``tenants.timezone`` — the zone this merchant counts its days in, or None.

    None is the answer an undeclared tenant gives, and it means "no opinion":
    the reader falls to the deployment zone (see `timekit.resolve_timezone`).
    Existing rows were deliberately left NULL by the migration, so shipping
    this column moves nobody's day buckets.

    Read with raw SQL rather than an import of `identity.models` for the same
    reason `core.tenancy.resolve_tenant_currency` reaches for the row behind a
    function-scope import — analytics has no business coupling to another
    module's tables to ask one question (§8), and this module already speaks
    SQL to every other table it reads.
    """
    row = (
        await session.execute(
            text('SELECT "timezone" FROM tenants WHERE id = :tenant_id'),
            {"tenant_id": str(tenant_id)},
        )
    ).first()
    return row[0] if row is not None else None


async def resolve_report_timezone(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    caller_timezone: str | None = None,
) -> ResolvedTimezone:
    """The zone THIS read model buckets in: caller -> tenant -> deployment -> UTC.

    One function on purpose. Every reader that labels a day goes through it, so
    the order cannot drift between endpoints, and the returned value carries the
    layer that answered (`source`) — which is what a response reports beside the
    zone itself. A caller zone forwarded from `resolve_timezone` keeps its own
    provenance, so a deployment default never masks the tenant's column.
    """
    return resolve_timezone(
        caller_timezone, tenant_timezone=await tenant_timezone(session, tenant_id)
    )


async def revenue_summary(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
    timezone: str | None = None,
) -> dict:
    """Every money figure for one window, each labelled with its own family.

    A caller must not be able to ask for "revenue" and get an unspecified
    number: gross/net are separate keys, the refund that could not be subtracted
    is ``refund_excess``, and the currency is the tenant's, never a literal.

    Same honesty applies to the calendar: ``timezone`` is the zone the buckets
    would be labelled in and ``timezone_source`` says whether that is the
    caller's ask, the tenant's own column (§47/M10 remainder), the deployment's
    configuration, or the UTC fallback.
    """
    gross = await revenue(session, tenant_id, since=since, until=until)
    refunded = await refunded_amount(session, tenant_id, since=since, until=until)
    net, excess = net_of(gross, refunded)
    count = await orders_count(session, tenant_id, since=since, until=until)
    zone = await resolve_report_timezone(session, tenant_id, timezone)
    return {
        "currency": await resolve_tenant_currency(session, tenant_id),
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


async def _sum_by_bucket(
    session: AsyncSession, sql: str, params: dict
) -> dict[date, Decimal]:
    rows = (await session.execute(text(sql), params)).all()
    return {row.day.date(): _money(row.value) for row in rows}


async def _count_by_bucket(session: AsyncSession, sql: str, params: dict) -> dict[date, int]:
    rows = (await session.execute(text(sql), params)).all()
    return {row.day.date(): int(row.value or 0) for row in rows}


async def daily_revenue_series(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    since: datetime,
    until: datetime,
    timezone: str | None = None,
) -> list[dict]:
    """Gross/net revenue, refunds and order counts per MERCHANT day (gap M10).

    The window selects instants; the DAY LABEL is merchant-local, via
    ``AT TIME ZONE`` — the same rule `timekit.merchant_day` implements in Python.
    A UTC-midnight bucket silently moves a late-evening sale into the next day,
    which is what made the daily series disagree with the summary.

    "Merchant-local" is resolved per tenant here, not per deployment: the
    caller's zone wins, else ``tenants.timezone`` (§47/M10 remainder), else the
    configured zone. Every bucket below is computed with the ONE zone the
    summary would report, so a series and a card cannot disagree.
    """
    zone = str(await resolve_report_timezone(session, tenant_id, timezone))
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


async def stock_health(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    low_stock_threshold: int = LOW_STOCK_THRESHOLD,
) -> dict:
    """Replenishment signal, split so an empty shelf is not "low stock" noise.

    ``available = on_hand - reserved`` (the same expression the dashboard used),
    but zero-or-below is ``out_of_stock_count`` and only 1..threshold is
    ``low_stock_count``. Folding the two together made the number unactionable:
    most of what it reported was already sold out.
    """
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
        {"tenant_id": str(tenant_id), "threshold": low_stock_threshold},
    )
    row = result.one()
    out_of_stock = int(row[0] or 0)
    low = int(row[1] or 0)
    tracked = int(row[2] or 0)
    return {
        "low_stock_threshold": low_stock_threshold,
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


# §55-57 RETENTION IS OPEN — deliberately, not by omission.
#
# A previous `archive_old_rows()` helper lived at the end of this module. It had
# ZERO callers and ZERO tests: retention was dead code behind a comment, which is
# the exact recurring defect this repo is being swept for. It has been deleted
# rather than wired, because wiring it would have been wrong:
#
#   * it built its target with raw `CREATE TABLE ... (LIKE ... INCLUDING ALL)` and
#     `SELECT *` at RUNTIME, so any column added to a source table would silently
#     mis-file into a stale archive shape;
#   * it interpolated `table_name` straight into DDL/DML (an injection surface the
#     moment a caller ever passes anything user-controlled);
#   * real cold-data handling here is *range partitioning by created_at* (§55-57),
#     which is a DBA-approved migration against the partitioned tables — not a
#     sweep a read-side CQRS module owns.
#
# The honest smaller answer is to delete the dead path and leave §55-57 open
# until an approved partition/archive migration exists. Do not re-add a helper
# until that migration is the one doing the moving.
