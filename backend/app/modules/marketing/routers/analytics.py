"""Analytics and attribution endpoints for marketing."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Query

from app.modules.marketing import analytics
from app.modules.marketing.attribution_service import AttributionService
from app.modules.marketing.schemas import (
    CampaignAttributionOut,
    ConversionAttributionOut,
    DailyOrderListOut,
    DashboardOut,
    MarketingSummaryOut,
)
from ._deps import (
    MAX_WINDOW_DAYS,
    TenantCtxDep,
    _missing_query_params,
    _wire_money,
    analytics_router,
    router,
)


@analytics_router.get("/summary", response_model=MarketingSummaryOut)
async def analytics_summary(
    ctx: TenantCtxDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_WINDOW_DAYS,
            description=(
                "Trailing window in days, 1..365. A wider ask is not a wider "
                "report, it is an unbounded aggregate scan behind a screen the "
                "dashboard re-polls (gap P7)."
            ),
        ),
    ] = 30,
):
    return {
        # Money for the window comes from the canonical read model: gross and net
        # are separate keys here, never one figure called "revenue".
        "orders_summary": await analytics.orders_summary(ctx.session, ctx.tenant_id, days=days),
        "revenue_by_source": await analytics.revenue_by_source(
            ctx.session, ctx.tenant_id, days=days
        ),
        "revenue_by_campaign": await analytics.revenue_by_campaign(
            ctx.session, ctx.tenant_id, days=days
        ),
        # Named for its denominator: campaigns.budget is a PLAN, and this schema
        # records no burned spend, so there is no return-on-spend figure to give.
        "campaign_budget_roas": await analytics.campaign_budget_roas(
            ctx.session, ctx.tenant_id, days=days
        ),
    }


@analytics_router.get("/daily-orders", response_model=DailyOrderListOut)
async def analytics_daily_orders(
    ctx: TenantCtxDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_WINDOW_DAYS,
            description="Trailing window in days, 1..365 (gap P7).",
        ),
    ] = 30,
    timezone: Annotated[
        str | None,
        Query(
            description=(
                "IANA zone the merchant counts days in — the day label is local to "
                "it. Defaults to the deployment's ANALYTICS_TIMEZONE (UTC)."
            )
        ),
    ] = None,
):
    """Daily buckets on the MERCHANT's day, with gross/net money named apart."""
    rows = await analytics.daily_orders(ctx.session, ctx.tenant_id, days=days, timezone=timezone)
    # A bounded trailing series, so ``next_cursor`` is null and still present:
    # one list reader serves every list in these two modules (gap P8).
    return {"items": rows, "next_cursor": None}


@analytics_router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    ctx: TenantCtxDep,
    days: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_WINDOW_DAYS,
            description="Trailing window for the daily series, 1..365 days (gap P7).",
        ),
    ] = 14,
    timezone: str | None = None,
):
    """One-call aggregate powering the dashboard home screen."""
    summary = await analytics.dashboard_summary(ctx.session, ctx.tenant_id)
    summary["daily_orders"] = await analytics.daily_orders(
        ctx.session, ctx.tenant_id, days=days, timezone=timezone
    )
    summary["revenue_by_source"] = await analytics.revenue_by_source(ctx.session, ctx.tenant_id)
    return summary


@router.get(
    "/marketing/attribution",
    response_model=ConversionAttributionOut | CampaignAttributionOut,
)
async def get_attribution(
    ctx: TenantCtxDep,
    campaign_id: uuid.UUID | None = None,
    conversion_id: uuid.UUID | None = None,
    days: Annotated[int, Query(ge=1, le=MAX_WINDOW_DAYS)] = 30,
):
    """§82: Attribution report for a campaign or conversion.

    Two payloads on one path, and the published ``response_model`` names BOTH —
    the conversion view lists the touchpoints that credited one conversion, the
    campaign view rolls the models up over a window. Asking for neither is a
    malformed question and gets the 422 every other refusal here uses, not the
    200-and-a-prose-error this route used to answer.
    """
    if conversion_id:
        records = await AttributionService.compute_for_conversion(
            ctx.session, ctx.tenant_id, conversion_id
        )
        return {
            "conversion_id": str(conversion_id),
            # Two models crediting one conversion are two readings of the same
            # money — a consumer must pick one, never add these up.
            "views_are_alternative": True,
            "touchpoints": [
                {
                    "touchpoint_id": str(r.touchpoint_id),
                    "model": r.model,
                    # A share of the whole, not money: stays a number.
                    "weight": r.weight,
                    # The credit itself is an amount, so it is a Decimal string —
                    # two views of one conversion stay 200.00 of money, not a
                    # float64 a consumer re-adds and calls revenue.
                    "credited_value": _wire_money(r.credited_value),
                }
                for r in records
            ],
        }
    if campaign_id:
        report = await AttributionService.get_campaign_attribution(
            ctx.session, ctx.tenant_id, campaign_id, days=days
        )
        return report
    _missing_query_params("campaign_id", "conversion_id")
