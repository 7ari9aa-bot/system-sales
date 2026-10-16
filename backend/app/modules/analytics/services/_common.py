"""Common helpers, validators, and constants for analytics services."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.analytics.timekit import ResolvedTimezone, resolve_timezone
from app.modules.platform.metrics import MetricRegistry

# The shape a status word is allowed to have.
_STATUS_WORD = re.compile(r"^[a-z][a-z_]*$")


def bind_instant(value: object, name: str) -> datetime:
    """One window edge, proven to be an instant and rendered in UTC."""
    if not isinstance(value, datetime):
        raise ValidationError(
            f"{name} must be an ISO 8601 instant, not {type(value).__name__}: "
            f"{value!r}. A route parameter that never became a value is refused "
            f"here rather than at the driver.",
            details={name: repr(value), "required": "datetime carrying a UTC offset"},
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValidationError(
            f"{name} must be an ISO 8601 instant carrying a UTC offset. A naive "
            f"value like '2026-09-01T00:00:00' names a wall clock, and Postgres "
            f"would read it in the connection's own timezone, not yours. Send "
            f"'2026-09-01T00:00:00Z' for UTC or '2026-09-01T00:00:00+03:00' for "
            f"an offset you mean.",
            details={name: value.isoformat(), "required": "UTC offset"},
        )
    return value.astimezone(UTC)


def bind_window(since: datetime, until: datetime) -> tuple[datetime, datetime]:
    """The ``[since, until)`` every reader binds with, or the refusal it owes."""
    return bind_instant(since, "since"), bind_instant(until, "until")


def bind_count(value: object, name: str) -> int:
    """One integer bind, proven to be an integer before it reaches the wire."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(
            f"{name} must be an integer, not {type(value).__name__}: {value!r}. A "
            f"route parameter that never became a value (a FastAPI Query "
            f"declaration, a string, a Decimal) is refused here rather than at "
            f"the driver.",
            details={name: repr(value), "required": "int"},
        )
    return int(value)


def _status_sql(values: Sequence[str]) -> str:
    """Render a status list as the SQL ``IN``/``NOT IN`` fragment it is."""
    if not values:
        raise ValueError("an empty status list is not a filter, it is a syntax error")
    for value in values:
        if not _STATUS_WORD.fullmatch(value or ""):
            raise ValueError(f"not a status word: {value!r}")
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


_GROSS_PAYMENT_STATUSES = _status_sql(MetricRegistry.get("revenue").filters["status"])
_REFUND_STATUSES = _status_sql(MetricRegistry.get("refunded_amount").filters["status"])
_UNPLACED_ORDER_STATUSES = _status_sql(
    MetricRegistry.get("orders_count").filters["status_excluded"]
)

MONEY_SCALE = Decimal("0.01")
ZERO = Decimal("0.00")
LOW_STOCK_THRESHOLD = 2


def _money(value: object) -> Decimal:
    """Coerce a NUMERIC(14,2) aggregate to Decimal at money scale."""
    return Decimal(str(value or 0)).quantize(MONEY_SCALE)


def net_of(gross: object, refunded: object) -> tuple[Decimal, Decimal]:
    """``(net_revenue, refund_excess)`` for one window."""
    collected, returned = _money(gross), _money(refunded)
    net = collected - returned
    if net < ZERO:
        return ZERO, -net
    return net, ZERO


def _aov(money: Decimal, count: int) -> Decimal:
    """Average order value for one money family."""
    if count == 0:
        return ZERO
    return (money / Decimal(count)).quantize(MONEY_SCALE)


async def tenant_timezone(session: AsyncSession, tenant_id: uuid.UUID) -> str | None:
    """``tenants.timezone`` — the zone this merchant counts its days in, or None."""
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
    """The zone THIS read model buckets in: caller -> tenant -> deployment -> UTC."""
    return resolve_timezone(
        caller_timezone, tenant_timezone=await tenant_timezone(session, tenant_id)
    )


async def _sum_by_bucket(session: AsyncSession, sql: str, params: dict) -> dict[date, Decimal]:
    rows = (await session.execute(text(sql), params)).all()
    return {row.day.date(): _money(row.value) for row in rows}


async def _count_by_bucket(session: AsyncSession, sql: str, params: dict) -> dict[date, int]:
    rows = (await session.execute(text(sql), params)).all()
    return {row.day.date(): int(row.value or 0) for row in rows}
