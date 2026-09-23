"""Spec §55-57 — analytics routes: metric queries and definitions.

Read-only: every endpoint returns a number or a list. No writes here.

This module provides the canonical metric computation endpoints (revenue,
orders_count, AOV, etc.) backed by the metric registry (§167). The marketing
module's analytics_router is for campaign-specific analytics (CAC, ROAS);
this module is for the platform-wide canonical numbers.

Money never leaves here unlabelled: gross and net are different keys, and the
currency is read from the tenant (§47). Daily buckets are taken in the merchant's
zone, not at UTC midnight (gap M10).

``GET /overview`` is the screen-shaped aggregate: it composes the same readers
into one payload for the analytics page — no route here owns a query, and no
figure is computed twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.tenancy import resolve_tenant_currency
from app.modules.analytics import service as analytics_service
from app.modules.analytics.timekit import resolve_timezone
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform.metrics import MetricRegistry

router = APIRouter(prefix="/analytics", tags=["analytics"])

SettingsCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

# Metrics whose value is money, so the response must carry the currency the
# amount is denominated in.
_MONEY_METRICS = frozenset({"revenue", "net_revenue", "refunded_amount", "aov"})

# Every key a read model can return whose value is money. Named per family so
# a gross figure cannot be serialised under a net name, and — the reason this is
# one set rather than a set per route — the averages are money too. FastAPI's
# default encoder resolves a bare ``Decimal`` by casting it to ``float``, so
# "leave it as a Decimal and the framework will cope" is how a cent goes
# missing (ADR-001): every one of these becomes a string on the wire.
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


def _as_json(value: Decimal | float | int) -> str | int:
    """Money stays a string on the wire — a float would round-trip a cent away."""
    return value if isinstance(value, int) else str(value)


def _money_json(row: dict) -> dict:
    """Stringify the money fields of one read model, leave the rest alone."""
    return {
        key: (str(value) if key in _MONEY_FIELDS and isinstance(value, Decimal) else value)
        for key, value in row.items()
    }


def _window(
    days: int, since: datetime | None, until: datetime
) -> tuple[datetime, datetime]:
    """The one ``[since, until)`` every figure in a payload shares.

    ``since`` wins when given; otherwise the trailing ``days``. A summary and a
    daily series computed on two different windows cannot be reconciled by
    whoever reads them side by side, so this resolves once and callers reuse it.
    """
    start = until - timedelta(days=days) if since is None else since
    return start, until


@router.get("/metrics/definitions")
async def list_metric_definitions(ctx: TenantCtxDep) -> dict:
    """§167: list every canonical metric definition."""
    return {"items": MetricRegistry.definitions()}


@router.get("/metrics/{metric_name}")
async def compute_metric(
    metric_name: str,
    ctx: TenantCtxDep,
    since: datetime = Query(..., description="ISO 8601 start (inclusive)"),
    until: datetime = Query(
        default_factory=lambda: datetime.now(UTC),
        description="ISO 8601 end (exclusive)",
    ),
) -> dict:
    """Compute a single canonical metric for the tenant's window.

    The response carries the definition the number was computed under
    (``refund_treatment`` says whether refunds were subtracted at all,
    ``timezone_rule`` says how a calendar bucket is taken) so a bare figure can
    never be read as the other family.
    """
    spec = MetricRegistry.get(metric_name)
    value = await analytics_service.compute_metric(
        ctx.session,
        ctx.tenant_id,
        metric_name=metric_name,
        since=since,
        until=until,
    )
    payload: dict = {
        "metric": metric_name,
        "value": _as_json(value),
        "since": since.isoformat(),
        "until": until.isoformat(),
    }
    if spec is not None:
        payload["refund_treatment"] = spec.refund_treatment
        payload["timezone_rule"] = spec.timezone_rule
    if metric_name in _MONEY_METRICS:
        # Money belongs to a tenant and one tenant trades in one currency (§47);
        # the label comes from the tenant row, never from a literal.
        payload["currency"] = await resolve_tenant_currency(ctx.session, ctx.tenant_id)
    return payload


@router.get("/revenue/summary")
async def revenue_summary(
    ctx: TenantCtxDep,
    since: datetime = Query(..., description="ISO 8601 start (inclusive)"),
    until: datetime = Query(
        default_factory=lambda: datetime.now(UTC),
        description="ISO 8601 end (exclusive)",
    ),
    timezone: str | None = Query(
        default=None, description="IANA zone for the day label; defaults to the deployment zone"
    ),
) -> dict:
    """Gross and net money for one window, each figure named for its family.

    ``net_revenue`` is ``gross_revenue - refunded_amount``, floored at zero;
    whatever could not be subtracted in this window is reported as
    ``refund_excess`` instead of disappearing.
    """
    resolve_timezone(timezone)  # reject a bad zone before running four queries
    summary = await analytics_service.revenue_summary(
        ctx.session, ctx.tenant_id, since=since, until=until, timezone=timezone
    )
    return _money_json(summary)


@router.get("/daily-series")
async def daily_series(
    ctx: TenantCtxDep,
    since: datetime = Query(..., description="ISO 8601 start (inclusive)"),
    until: datetime = Query(
        default_factory=lambda: datetime.now(UTC),
        description="ISO 8601 end (exclusive)",
    ),
    timezone: str | None = Query(
        default=None,
        description=(
            "IANA zone the merchant counts days in. The day LABEL is local to "
            "this zone; since/until remain instants. Omit it and the tenant's "
            "declared zone is used, then the deployment's ANALYTICS_TIMEZONE."
        ),
    ),
) -> dict:
    """The merchant's daily revenue series — bucketed in the merchant's day."""
    resolve_timezone(timezone)  # reject a bad zone before the tenant lookup
    # ONE resolution for both the SQL and this label. The router cannot see
    # ``tenants.timezone``, so resolving the chain here and the service
    # resolving it again produced two answers to one question: Cairo buckets
    # under a deployment-zone label.
    zone = await analytics_service.resolve_report_timezone(
        ctx.session, ctx.tenant_id, timezone
    )
    rows = await analytics_service.daily_revenue_series(
        ctx.session, ctx.tenant_id, since=since, until=until, timezone=zone
    )
    return {
        "timezone": str(zone),
        "timezone_source": zone.source,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "currency": await resolve_tenant_currency(ctx.session, ctx.tenant_id),
        "items": [
            {
                "day": row["day"],
                "orders_count": row["orders_count"],
                "gross_revenue": str(row["gross_revenue"]),
                "refunded_amount": str(row["refunded_amount"]),
                "net_revenue": str(row["net_revenue"]),
                "refund_excess": str(row["refund_excess"]),
            }
            for row in rows
        ],
    }


@router.get("/inventory/stock-health")
async def stock_health(
    ctx: TenantCtxDep,
    low_stock_threshold: int = Query(
        default=analytics_service.LOW_STOCK_THRESHOLD,
        ge=0,
        description="Available units at which a variant counts as low",
    ),
) -> dict:
    """Replenishment signal with empty shelves split out of "low stock"."""
    health = await analytics_service.stock_health(
        ctx.session, ctx.tenant_id, low_stock_threshold=low_stock_threshold
    )
    return health


@router.get("/overview")
async def analytics_overview(
    ctx: TenantCtxDep,
    days: int = Query(
        default=30,
        ge=1,
        le=365,
        description="Trailing window in days; ignored when `since` is given",
    ),
    since: datetime | None = Query(
        default=None, description="ISO 8601 start (inclusive). Overrides `days`."
    ),
    until: datetime = Query(
        default_factory=lambda: datetime.now(UTC),
        description="ISO 8601 end (exclusive)",
    ),
    timezone: str | None = Query(
        default=None,
        description=(
            "IANA zone the merchant counts days in — the day label is local to "
            "it. Defaults to the deployment's ANALYTICS_TIMEZONE."
        ),
    ),
    low_stock_threshold: int = Query(
        default=analytics_service.LOW_STOCK_THRESHOLD,
        ge=0,
        description="Available units at which a variant counts as low",
    ),
) -> dict:
    """One call for the analytics screen: money, orders, AOV, days, stock.

    The screen used to fetch a path this server never published, so every visit
    landed on its error state — and ``as any`` on the response kept the type
    checker from noticing. What it returns is a composition, not a computation:
    every figure comes from a reader in ``analytics/service.py``, the module
    that owns metric SQL since Wave-4 M11. This route adds no query of its own.

    Shape honesty, in the words the registry uses (§167/ADR-053):

    * ``gross_revenue`` is collected money, ``net_revenue`` is what survives the
      refunds that LEFT in the same window, and ``refund_excess`` is the part
      that could not be subtracted because net is floored at zero. No key is
      ever named plain ``revenue``.
    * ``gross_aov``/``net_aov`` say which numerator they used.
    * ``daily_series`` buckets on the MERCHANT's day (gap M10) over the same
      window as the summary, so the bars add up to the cards beside them.
    * ``currency`` is the tenant's (§47) and ``timezone`` is the zone the buckets
      were labelled in; money crosses as strings, counts as integers.
    * ``stock`` separates an empty shelf from a nearly-empty one (gap M7).

    There is deliberately no top-products key: no canonical reader computes one,
    and an invented field is how a screen ends up trusting a number that does
    not exist.
    """
    zone = resolve_timezone(timezone)  # fail closed before the first query
    start, end = _window(days, since, until)
    summary = _money_json(
        await analytics_service.revenue_summary(
            ctx.session, ctx.tenant_id, since=start, until=end, timezone=zone
        )
    )
    series = await analytics_service.daily_revenue_series(
        ctx.session, ctx.tenant_id, since=start, until=end, timezone=zone
    )
    stock = await analytics_service.stock_health(
        ctx.session, ctx.tenant_id, low_stock_threshold=low_stock_threshold
    )
    summary.update(
        {
            "since": start.isoformat(),
            "until": end.isoformat(),
            "daily_series": [_money_json(row) for row in series],
            "stock": stock,
        }
    )
    return summary


