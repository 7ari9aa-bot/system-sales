"""MARKETING & ANALYTICS routes — campaigns, touchpoint capture, leads,
analytics summary.

Re-export aggregator for decomposed marketing routers package.
"""

from __future__ import annotations

from app.modules.marketing.attribution_service import AttributionService
from app.modules.marketing.campaign import CampaignExecutionService
from app.modules.marketing.journey import JourneyExecutionService
from app.modules.marketing.routers import analytics_router, router
from app.modules.marketing.routers._deps import (
    MAX_PAGE_SIZE,
    MAX_WINDOW_DAYS,
    WriteCtx,
    _missing_query_params,
    _wire_money,
)
from app.modules.marketing.routers.analytics import (
    analytics_daily_orders,
    analytics_summary,
    dashboard,
    get_attribution,
)
from app.modules.marketing.routers.campaigns import (
    create_campaign,
    get_campaign_run,
    list_campaign_conversions,
    list_campaigns,
    pause_campaign,
    resume_campaign,
    start_campaign,
)
from app.modules.marketing.routers.engagement import (
    create_lead,
    list_journey_runs,
    record_conversion,
    record_touchpoint,
    start_journey,
    update_lead_status,
)
from app.modules.marketing.schemas import (
    AttributionViewOut,
    CampaignAttributionOut,
    CampaignCreatedOut,
    CampaignListOut,
    CampaignOut,
    CampaignRequest,
    CampaignRunProgressOut,
    CampaignRunStartedOut,
    CampaignRunStateOut,
    CampaignStartRequest,
    ConversionAttributionOut,
    ConversionListOut,
    ConversionOut,
    ConversionRequest,
    DailyOrderListOut,
    DashboardOut,
    JourneyRunListOut,
    JourneyRunStartedOut,
    JourneyStartRequest,
    LeadOut,
    LeadRequest,
    LeadStatusOut,
    LeadStatusRequest,
    MarketingSummaryOut,
    RoasRowOut,
    TouchpointCreatedOut,
    TouchpointRequest,
)
from app.modules.marketing.service import MarketingService


def __getattr__(name: str):
    """PEP 562 lazy re-export: the contracts test monkeypatches
    ``marketing_router.EntitlementService`` — resolved on first access so the
    billing import stays function-scoped (module-scope cross-module service
    imports are boundary-counted) while the attribute remains addressable."""
    if name == "EntitlementService":
        from app.modules.billing.service import EntitlementService

        return EntitlementService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Preserve module qualification for introspection and test sweeps
for _endpoint in (
    list_campaigns,
    create_campaign,
    list_campaign_conversions,
    start_campaign,
    pause_campaign,
    resume_campaign,
    get_campaign_run,
    record_touchpoint,
    create_lead,
    update_lead_status,
    record_conversion,
    start_journey,
    list_journey_runs,
    analytics_summary,
    analytics_daily_orders,
    dashboard,
    get_attribution,
):
    _endpoint.__module__ = "app.modules.marketing.router"

__all__ = [
    "AttributionService",
    "AttributionViewOut",
    "CampaignAttributionOut",
    "CampaignCreatedOut",
    "CampaignExecutionService",
    "CampaignListOut",
    "CampaignOut",
    "CampaignRequest",
    "CampaignRunProgressOut",
    "CampaignRunStartedOut",
    "CampaignRunStateOut",
    "CampaignStartRequest",
    "ConversionAttributionOut",
    "ConversionListOut",
    "ConversionOut",
    "ConversionRequest",
    "DailyOrderListOut",
    "DashboardOut",
    "JourneyExecutionService",
    "JourneyRunListOut",
    "JourneyRunStartedOut",
    "JourneyStartRequest",
    "LeadOut",
    "LeadRequest",
    "LeadStatusOut",
    "LeadStatusRequest",
    "MAX_PAGE_SIZE",
    "MAX_WINDOW_DAYS",
    "MarketingService",
    "MarketingSummaryOut",
    "RoasRowOut",
    "TouchpointCreatedOut",
    "TouchpointRequest",
    "WriteCtx",
    "_missing_query_params",
    "_wire_money",
    "analytics_daily_orders",
    "analytics_router",
    "analytics_summary",
    "create_campaign",
    "create_lead",
    "dashboard",
    "get_attribution",
    "get_campaign_run",
    "list_campaign_conversions",
    "list_campaigns",
    "list_journey_runs",
    "pause_campaign",
    "record_conversion",
    "record_touchpoint",
    "resume_campaign",
    "router",
    "start_campaign",
    "start_journey",
    "update_lead_status",
]
