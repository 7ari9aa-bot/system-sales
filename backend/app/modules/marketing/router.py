"""MARKETING & ANALYTICS routes — campaigns, touchpoint capture, leads,
analytics summary.

Reads use plain TenantCtxDep; writes require the ``marketing:write``
permission. All routes run inside the request transaction owned by get_db —
services never commit.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.marketing import analytics
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


# --------------------------------------------------------- campaigns ----


@router.get("/marketing/campaigns")
async def list_campaigns(ctx: TenantCtxDep, status: str | None = None, limit: int = 100):
    campaigns = await MarketingService.list_campaigns(
        ctx.session, ctx.tenant_id, status=status, limit=limit
    )
    return [
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
        for c in campaigns
    ]


@router.post("/marketing/campaigns", status_code=201)
async def create_campaign(ctx: WriteCtx, body: CampaignRequest):
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


# --------------------------------------------------------- analytics ----


@analytics_router.get("/summary")
async def analytics_summary(ctx: TenantCtxDep, days: int = 30):
    return {
        "orders_summary": await analytics.orders_summary(ctx.session, ctx.tenant_id, days=days),
        "revenue_by_source": await analytics.revenue_by_source(
            ctx.session, ctx.tenant_id, days=days
        ),
        "revenue_by_campaign": await analytics.revenue_by_campaign(
            ctx.session, ctx.tenant_id, days=days
        ),
        "campaign_roas": await analytics.campaign_roas(ctx.session, ctx.tenant_id, days=days),
    }


@analytics_router.get("/daily-orders")
async def analytics_daily_orders(ctx: TenantCtxDep, days: int = 30):
    return await analytics.daily_orders(ctx.session, ctx.tenant_id, days=days)


@analytics_router.get("/dashboard")
async def dashboard(ctx: TenantCtxDep, days: int = 14):
    """One-call aggregate powering the dashboard home screen."""
    summary = await analytics.dashboard_summary(ctx.session, ctx.tenant_id)
    summary["daily_orders"] = await analytics.daily_orders(ctx.session, ctx.tenant_id, days=days)
    summary["revenue_by_source"] = await analytics.revenue_by_source(ctx.session, ctx.tenant_id)
    return summary
