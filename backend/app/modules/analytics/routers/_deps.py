"""Shared helpers, constants, and type aliases for analytics routers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.core.errors import ValidationError
from app.modules.analytics import service as analytics_service
from app.modules.analytics.timekit import ResolvedTimezone
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.identity.deps import (
    TenantCtxDep as TenantCtxDep,  # noqa: F401  — re-exported for metrics.py
)
from app.modules.platform.metrics import (
    MetricRegistry as MetricRegistry,  # noqa: F401  — re-exported for metrics.py
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

MAX_WINDOW_DAYS = 365
MAX_LOW_STOCK_THRESHOLD = 10_000

SettingsCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]
AnalyticsReadCtx = Annotated[TenantContext, Depends(require_permission("analytics:read"))]
AnalyticsWriteCtx = Annotated[TenantContext, Depends(require_permission("analytics:write"))]

_WINDOW_POLICY = (
    "An ISO 8601 INSTANT, which means it must carry a UTC offset: "
    "`2026-09-01T00:00:00Z`, or `2026-09-01T00:00:00+03:00` for a window you "
    "mean in Cairo time. A naive value (no offset) is refused with a 422, "
    "because Postgres would read it in the database session's timezone and the "
    "window would silently move with the connection. The `since`/`until` this "
    "response echoes are the exact UTC instants the query bound."
)
_SINCE_DOC = f"ISO 8601 start (inclusive). {_WINDOW_POLICY}"
_UNTIL_DOC = (
    f"ISO 8601 end (exclusive), as an instant. {_WINDOW_POLICY} "
    "Defaults to the moment the request is handled, in UTC."
)

_MONEY_METRICS = frozenset({"revenue", "net_revenue", "refunded_amount", "aov"})
_METRIC_BASIS = {"roas": "planned_budget"}
_MONEY_FIELDS = frozenset(
    {
        "gross_revenue",
        "net_revenue",
        "refunded_amount",
        "refund_excess",
        "gross_aov",
        "net_aov",
    }
)


def _bind_edge(value: Any, name: str, failures: list[dict]) -> datetime:
    """One window edge as a UTC instant, or the 422 failure that says why not."""
    try:
        return analytics_service.bind_instant(value, name)
    except ValidationError as exc:
        failures.append(
            {
                "type": "value_error",
                "loc": ["query", name],
                "msg": f"Value error, {exc.message}",
                "input": value.isoformat() if isinstance(value, datetime) else repr(value),
            }
        )
        return value


def _window_failure(name: str, message: str, value: object) -> dict:
    """One refusal in the shape FastAPI itself uses for a bad query parameter."""
    return {
        "type": "value_error",
        "loc": ["query", name],
        "msg": f"Value error, {message}",
        "input": value.isoformat() if isinstance(value, datetime) else repr(value),
    }


def _bind_window(
    since: datetime | None, until: datetime | None
) -> tuple[datetime | None, datetime]:
    """Bind the window edges to instants, or answer 422 naming the fix."""
    until = datetime.now(UTC) if until is None else until
    failures: list[dict] = []
    bound_since = None if since is None else _bind_edge(since, "since", failures)
    bound_until = _bind_edge(until, "until", failures)
    if failures:
        raise HTTPException(status_code=422, detail=failures)
    if bound_since is not None:
        span = bound_until - bound_since
        if span <= timedelta(0):
            raise HTTPException(
                status_code=422,
                detail=[
                    _window_failure(
                        "since",
                        "the window is empty or reversed: [since, until) selects the "
                        f"instants between them, and {bound_since.isoformat()} to "
                        f"{bound_until.isoformat()} selects none — send a `since` "
                        "strictly before its `until`.",
                        bound_since,
                    )
                ],
            )
        if span > timedelta(days=MAX_WINDOW_DAYS):
            raise HTTPException(
                status_code=422,
                detail=[
                    _window_failure(
                        "since",
                        f"the window is {span.days} days wide, and this route binds "
                        f"at most {MAX_WINDOW_DAYS} — the same ceiling `days` "
                        "carries. Ask for a shorter window, or page it.",
                        bound_since,
                    )
                ],
            )
    return bound_since, bound_until


def _as_json(value: Decimal | float | int | None) -> str | int | float | None:
    """Money leaves as a STRING; counts and RATIOS leave as NUMBERS; None as null."""
    if value is None or isinstance(value, (int, float)):
        return value
    return str(value)


def _money_json(row: dict) -> dict:
    """Stringify the money fields of one read model, leave the rest alone."""
    return {
        key: (str(value) if key in _MONEY_FIELDS and isinstance(value, Decimal) else value)
        for key, value in row.items()
    }


def _zone_source(zone: object) -> str | None:
    """Which layer of the resolution chain answered, or ``None``."""
    return zone.source if isinstance(zone, ResolvedTimezone) else None


def _window(days: int, since: datetime | None, until: datetime) -> tuple[datetime, datetime]:
    """The one ``[since, until)`` every figure in a payload shares."""
    start = until - timedelta(days=days) if since is None else since
    return start, until
