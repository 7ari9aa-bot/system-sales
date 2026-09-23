"""MARKETING & ANALYTICS routes — campaigns, touchpoint capture, leads,
analytics summary.

Reads use plain TenantCtxDep; writes require the ``marketing:write``
permission. All routes run inside the request transaction owned by get_db —
services never commit.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.pagination import decode_cursor, page_slice
from app.modules.billing.service import EntitlementService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.marketing import analytics
from app.modules.marketing.attribution_service import AttributionService
from app.modules.marketing.campaign import CampaignExecutionService
from app.modules.marketing.journey import JourneyExecutionService
from app.modules.marketing.service import MarketingService

router = APIRouter(tags=["marketing"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("marketing:write"))]


class CampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(default="manual", max_length=31)
    external_id: str | None = None
    objective: str | None = None
    budget: float | None = Field(default=None, ge=0)


class TouchpointRequest(BaseModel):
    customer_id: uuid.UUID | None = None
    source: str | None = Field(default=None, max_length=63)
    medium: str | None = Field(default=None, max_length=63)
    campaign_id: uuid.UUID | None = None
    ad_set_id: uuid.UUID | None = None
    ad_id: uuid.UUID | None = None
    click_id: str | None = None
    landing_url: str | None = None
    session_key: str | None = None


class LeadRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=31)
    email: str | None = Field(default=None, max_length=320)
    source: str | None = Field(default=None, max_length=63)
    campaign_id: uuid.UUID | None = None


class LeadStatusRequest(BaseModel):
    status: str = Field(pattern="^(new|contacted|qualified|converted|lost)$")


class ConversionRequest(BaseModel):
    customer_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    type: str = Field(default="purchase", pattern="^(purchase|signup|lead|custom)$")
    # Decimal, and the NUMERIC(14,2) shape stated explicitly: this is money.
    value: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    occurred_at: datetime | None = None



# --------------------------------------------------------- campaigns ----


@router.get("/marketing/campaigns")
async def list_campaigns(
    ctx: TenantCtxDep,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    before_created_at, before_id = decode_cursor(cursor) if cursor else (None, None)
    rows = await MarketingService.list_campaigns(
        ctx.session,
        ctx.tenant_id,
        status=status,
        limit=limit + 1,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    page, next_cursor = page_slice(rows, limit)
    return {
        "items": [
            {
                "id": str(c.id),
                "name": c.name,
                "provider": c.provider,
                "external_id": c.external_id,
                "objective": c.objective,
                "status": c.status,
                "budget": float(c.budget) if c.budget is not None else None,
                "created_at": c.created_at.isoformat(),
            }
            for c in page
        ],
        "next_cursor": next_cursor,
    }


@router.post("/marketing/campaigns", status_code=201)
async def create_campaign(ctx: WriteCtx, body: CampaignRequest):
    # §165: entitlement enforcement lives in ONE service, not per module.
    # Without this the plan was decorative — any tenant could launch campaigns
    # regardless of what they pay for.
    await EntitlementService.ensure(ctx.session, ctx.tenant_id, "CanSendCampaign")
    campaign = await MarketingService.create_campaign(
        ctx.session,
        ctx.tenant_id,
        name=body.name,
        provider=body.provider,
        external_id=body.external_id,
        objective=body.objective,
        budget=body.budget,
    )
    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "provider": campaign.provider,
        "status": campaign.status,
        "budget": float(campaign.budget) if campaign.budget is not None else None,
    }


# ------------------------------------------------------- touchpoints ----


@router.post("/marketing/touchpoints", status_code=201)
async def record_touchpoint(ctx: WriteCtx, body: TouchpointRequest):
    touchpoint = await MarketingService.record_touchpoint(
        ctx.session,
        ctx.tenant_id,
        customer_id=body.customer_id,
        source=body.source,
        medium=body.medium,
        campaign_id=body.campaign_id,
        ad_set_id=body.ad_set_id,
        ad_id=body.ad_id,
        click_id=body.click_id,
        landing_url=body.landing_url,
        session_key=body.session_key,
    )
    return {"id": str(touchpoint.id), "created_at": touchpoint.created_at.isoformat()}


# ------------------------------------------------------------- leads ----


@router.post("/marketing/leads", status_code=201)
async def create_lead(ctx: WriteCtx, body: LeadRequest):
    lead = await MarketingService.create_lead(
        ctx.session,
        ctx.tenant_id,
        name=body.name,
        phone=body.phone,
        email=body.email,
        source=body.source,
        campaign_id=body.campaign_id,
    )
    return {
        "id": str(lead.id),
        "status": lead.status,
        "name": lead.name,
        "phone": lead.phone,
        "source": lead.source,
    }


@router.patch("/marketing/leads/{lead_id}/status")
async def update_lead_status(lead_id: uuid.UUID, ctx: WriteCtx, body: LeadStatusRequest):
    lead = await MarketingService.update_lead_status(
        ctx.session, ctx.tenant_id, lead_id, body.status
    )
    return {"id": str(lead.id), "status": lead.status}


# ------------------------------------------------------ conversions ----


@router.post("/marketing/conversions", status_code=201)
async def record_conversion(ctx: WriteCtx, body: ConversionRequest):
    """Record one conversion. A replay of the same order/type is a 409.

    The database owns that guarantee (uq_conversions_tenant_order_type), so two
    concurrent retries cannot both book the money.
    """
    conversion = await MarketingService.record_conversion(
        ctx.session,
        ctx.tenant_id,
        customer_id=body.customer_id,
        order_id=body.order_id,
        type=body.type,
        value=body.value,
        occurred_at=body.occurred_at,
    )
    return {
        "id": str(conversion.id),
        "order_id": str(conversion.order_id) if conversion.order_id else None,
        "customer_id": str(conversion.customer_id) if conversion.customer_id else None,
        "type": conversion.type,
        "value": float(conversion.value) if conversion.value is not None else None,
        "currency": conversion.currency,
        "occurred_at": conversion.occurred_at.isoformat() if conversion.occurred_at else None,
    }


@router.get("/marketing/campaigns/{campaign_id}/conversions")
async def list_campaign_conversions(
    campaign_id: uuid.UUID,
    ctx: TenantCtxDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Conversions this campaign's touchpoints took part in.

    ``attribution_models`` names which VIEW credits the campaign — the models are
    alternative readings of the same order, so the rows are not additive.
    """
    rows = await MarketingService.list_campaign_conversions(
        ctx.session, ctx.tenant_id, campaign_id, limit=limit, offset=offset
    )
    return {
        "items": [
            {
                "id": str(c.id),
                "order_id": str(c.order_id) if c.order_id else None,
                "customer_id": str(c.customer_id) if c.customer_id else None,
                "type": c.type,
                "value": float(c.value) if c.value is not None else None,
                "currency": c.currency,
                "occurred_at": c.occurred_at.isoformat() if c.occurred_at else None,
                "attribution_models": models,
            }
            for c, models in rows
        ],
        "count": len(rows),
    }


# --------------------------------------------------------- analytics ----


@analytics_router.get("/summary")
async def analytics_summary(ctx: TenantCtxDep, days: int = 30):
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



@analytics_router.get("/daily-orders")
async def analytics_daily_orders(
    ctx: TenantCtxDep,
    days: int = 30,
    timezone: str | None = Query(
        default=None,
        description=(
            "IANA zone the merchant counts days in — the day label is local to "
            "it. Defaults to the deployment's ANALYTICS_TIMEZONE (UTC)."
        ),
    ),
):
    """Daily buckets on the MERCHANT's day, with gross/net money named apart."""
    return await analytics.daily_orders(
        ctx.session, ctx.tenant_id, days=days, timezone=timezone
    )


@analytics_router.get("/dashboard")
async def dashboard(ctx: TenantCtxDep, days: int = 14, timezone: str | None = None):
    """One-call aggregate powering the dashboard home screen."""
    summary = await analytics.dashboard_summary(ctx.session, ctx.tenant_id)
    summary["daily_orders"] = await analytics.daily_orders(
        ctx.session, ctx.tenant_id, days=days, timezone=timezone
    )
    summary["revenue_by_source"] = await analytics.revenue_by_source(ctx.session, ctx.tenant_id)
    return summary


# ------------------------------------------------------- journeys ----


class JourneyStartRequest(BaseModel):
    journey_id: uuid.UUID
    customer_id: uuid.UUID


class CampaignStartRequest(BaseModel):
    campaign_id: uuid.UUID
    segment_id: uuid.UUID | None = None
    body: str | None = None
    template: str | None = None
    channel: str = "whatsapp"


@router.post("/journeys/{journey_id}/start", status_code=201)
async def start_journey(journey_id: uuid.UUID, ctx: WriteCtx, body: JourneyStartRequest):
    """§175: Start a journey run for a customer."""
    run = await JourneyExecutionService.start_journey(
        ctx.session,
        ctx.tenant_id,
        journey_id=journey_id,
        customer_id=body.customer_id,
    )
    return {
        "id": str(run.id),
        "journey_id": str(run.journey_id),
        "customer_id": str(run.customer_id),
        "status": run.status,
        "current_step": run.current_step,
    }


@router.get("/journeys/{journey_id}/runs")
async def list_journey_runs(
    journey_id: uuid.UUID,
    ctx: TenantCtxDep,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """List journey runs for a journey."""
    from sqlalchemy import select

    from app.modules.marketing.journey import JourneyRun

    q = select(JourneyRun).where(
        JourneyRun.tenant_id == ctx.tenant_id,
        JourneyRun.journey_id == journey_id,
    )
    if status:
        q = q.where(JourneyRun.status == status)
    q = q.limit(limit)
    rows = (await ctx.session.execute(q)).scalars().all()
    return {
        "items": [
            {
                "id": str(r.id),
                "customer_id": str(r.customer_id),
                "status": r.status,
                "current_step": r.current_step,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ]
    }


@router.post("/campaigns/{campaign_id}/start", status_code=201)
async def start_campaign(campaign_id: uuid.UUID, ctx: WriteCtx, body: CampaignStartRequest):
    """§175: Start a campaign run."""
    await EntitlementService.ensure(ctx.session, ctx.tenant_id, "CanSendCampaign")
    run = await CampaignExecutionService.start_campaign(
        ctx.session,
        ctx.tenant_id,
        campaign_id=campaign_id,
        segment_id=body.segment_id,
        config={
            "body": body.body or "",
            "template": body.template,
            "channel": body.channel,
        },
    )
    return {
        "id": str(run.id),
        "campaign_id": str(run.campaign_id),
        "status": run.status,
        "total_recipients": run.total_recipients,
    }


@router.post("/campaigns/runs/{run_id}/pause")
async def pause_campaign(run_id: uuid.UUID, ctx: WriteCtx):
    """§175: Pause a running campaign."""
    run = await CampaignExecutionService.pause(ctx.session, ctx.tenant_id, run_id)
    return {"id": str(run.id), "status": run.status}


@router.post("/campaigns/runs/{run_id}/resume")
async def resume_campaign(run_id: uuid.UUID, ctx: WriteCtx):
    """§175: Resume a paused campaign."""
    run = await CampaignExecutionService.resume(ctx.session, ctx.tenant_id, run_id)
    return {"id": str(run.id), "status": run.status}


@router.get("/campaigns/runs/{run_id}")
async def get_campaign_run(run_id: uuid.UUID, ctx: TenantCtxDep):
    """Get campaign run status and progress."""
    from sqlalchemy import select

    from app.modules.marketing.campaign import CampaignRun

    run = (
        await ctx.session.execute(
            select(CampaignRun).where(
                CampaignRun.tenant_id == ctx.tenant_id,
                CampaignRun.id == run_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        from app.core.errors import NotFoundError
        raise NotFoundError("campaign run not found")
    return {
        "id": str(run.id),
        "campaign_id": str(run.campaign_id),
        "status": run.status,
        "total_recipients": run.total_recipients,
        "sent_count": run.sent_count,
        "failed_count": run.failed_count,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


# ----------------------------------------------------- attribution ----


@router.get("/marketing/attribution")
async def get_attribution(
    ctx: TenantCtxDep,
    campaign_id: uuid.UUID | None = None,
    conversion_id: uuid.UUID | None = None,
    days: int = Query(default=30, ge=1, le=365),
):
    """§82: Attribution report for a campaign or conversion."""
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
                    "weight": r.weight,
                    "credited_value": float(r.credited_value),
                }
                for r in records
            ],
        }
    if campaign_id:
        report = await AttributionService.get_campaign_attribution(
            ctx.session, ctx.tenant_id, campaign_id, days=days
        )
        return report
    return {"error": "provide campaign_id or conversion_id"}
