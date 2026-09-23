"""Spec §55-57 — analytics routes: metric queries and definitions.

Read-only: every endpoint returns a number or a list. No writes here.

This module provides the canonical metric computation endpoints (revenue,
orders_count, AOV, etc.) backed by the metric registry (§167). The marketing
module's analytics_router is for campaign-specific analytics (CAC, ROAS);
this module is for the platform-wide canonical numbers.

Money never leaves here unlabelled: gross and net are different keys, and the
currency is read from the tenant (§47). Daily buckets are taken in the merchant's
zone, not at UTC midnight (gap M10).
"""

from __future__ import annotations

from datetime import UTC, datetime
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


def _as_json(value: Decimal | float | int) -> str | int:
    """Money stays a string on the wire — a float would round-trip a cent away."""
    return value if isinstance(value, int) else str(value)


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
    money = {"gross_revenue", "net_revenue", "refunded_amount", "refund_excess"}
    return {
        key: (str(value) if key in money and isinstance(value, Decimal) else value)
        for key, value in summary.items()
    }


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
            "this zone; since/until remain instants. Defaults to the "
            "deployment's ANALYTICS_TIMEZONE."
        ),
    ),
) -> dict:
    """The merchant's daily revenue series — bucketed in the merchant's day."""
    zone = resolve_timezone(timezone)
    rows = await analytics_service.daily_revenue_series(
        ctx.session, ctx.tenant_id, since=since, until=until, timezone=zone
    )
    return {
        "timezone": zone,
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


