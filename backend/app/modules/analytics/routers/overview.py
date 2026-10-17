"""Overview, revenue summary, daily series, and stock health routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import Query

from app.modules.analytics import schemas
from app.modules.analytics import service as analytics_service
from app.modules.analytics.timekit import resolve_timezone


async def _resolve_tenant_currency(session, tenant_id):
    from app.modules.analytics import router as analytics_router
    return await analytics_router.resolve_tenant_currency(session, tenant_id)
from ._deps import (  # noqa: E402
    _SINCE_DOC,
    _UNTIL_DOC,
    MAX_LOW_STOCK_THRESHOLD,
    TenantCtxDep,
    _bind_window,
    _money_json,
    _window,
    _zone_source,
    router,
)


@router.get("/revenue/summary", response_model=schemas.RevenueSummaryOut)
async def revenue_summary(
    ctx: TenantCtxDep,
    since: Annotated[datetime, Query(description=_SINCE_DOC)],
    until: Annotated[datetime | None, Query(description=_UNTIL_DOC)] = None,
    timezone: Annotated[
        str | None,
        Query(description="IANA zone for the day label; defaults to the deployment zone"),
    ] = None,
) -> dict[str, Any]:
    """Gross and net money for one window, each figure named for its family."""
    since, until = _bind_window(since, until)
    resolve_timezone(timezone)
    summary = await analytics_service.revenue_summary(
        ctx.session, ctx.tenant_id, since=since, until=until, timezone=timezone
    )
    return {**_money_json(summary), "since": since.isoformat(), "until": until.isoformat()}


@router.get("/daily-series", response_model=schemas.DailySeriesOut)
async def daily_series(
    ctx: TenantCtxDep,
    since: Annotated[datetime, Query(description=_SINCE_DOC)],
    until: Annotated[datetime | None, Query(description=_UNTIL_DOC)] = None,
    timezone: Annotated[
        str | None,
        Query(
            description=(
                "IANA zone the merchant counts days in. The day LABEL is local to "
                "this zone; since/until remain instants. Omit it and the tenant's "
                "declared zone is used, then the deployment's ANALYTICS_TIMEZONE."
            )
        ),
    ] = None,
) -> dict[str, Any]:
    """The merchant's daily revenue series — bucketed in the merchant's day."""
    since, until = _bind_window(since, until)
    resolve_timezone(timezone)
    zone = await analytics_service.resolve_report_timezone(ctx.session, ctx.tenant_id, timezone)
    rows = await analytics_service.daily_revenue_series(
        ctx.session, ctx.tenant_id, since=since, until=until, timezone=zone
    )
    return {
        "timezone": str(zone),
        "timezone_source": _zone_source(zone),
        "since": since.isoformat(),
        "until": until.isoformat(),
        "currency": await _resolve_tenant_currency(ctx.session, ctx.tenant_id),
        "next_cursor": None,
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


@router.get("/inventory/stock-health", response_model=schemas.StockHealthOut)
async def stock_health(
    ctx: TenantCtxDep,
    low_stock_threshold: Annotated[
        int,
        Query(
            ge=0,
            le=MAX_LOW_STOCK_THRESHOLD,
            description=(
                "Available units at which a variant counts as low. Bound on both "
                "sides because it reaches SQL as `available <= :threshold`."
            ),
        ),
    ] = analytics_service.LOW_STOCK_THRESHOLD,
) -> dict[str, Any]:
    """Replenishment signal with empty shelves split out of 'low stock'."""
    health = await analytics_service.stock_health(
        ctx.session, ctx.tenant_id, low_stock_threshold=low_stock_threshold
    )
    return health


@router.get("/overview", response_model=schemas.AnalyticsOverviewOut)
async def analytics_overview(
    ctx: TenantCtxDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=365,
            description=(
                "Trailing window in days; ignored when `since` is given. Counted "
                "back from `until`, which is an instant, so the window it describes "
                "is the same one on every connection."
            ),
        ),
    ] = 30,
    since: Annotated[
        datetime | None, Query(description=f"{_SINCE_DOC} When given, overrides `days`.")
    ] = None,
    until: Annotated[datetime | None, Query(description=_UNTIL_DOC)] = None,
    timezone: Annotated[
        str | None,
        Query(
            description=(
                "IANA zone the merchant counts days in — the day label is local to "
                "it. Defaults to the deployment's ANALYTICS_TIMEZONE."
            )
        ),
    ] = None,
    low_stock_threshold: Annotated[
        int,
        Query(
            ge=0,
            le=MAX_LOW_STOCK_THRESHOLD,
            description=(
                "Available units at which a variant counts as low. The same bound "
                "the standalone stock-health route carries."
            ),
        ),
    ] = analytics_service.LOW_STOCK_THRESHOLD,
) -> dict[str, Any]:
    """One call for the analytics screen: money, orders, AOV, days, stock."""
    since, until = _bind_window(since, until)
    zone = resolve_timezone(timezone)
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
