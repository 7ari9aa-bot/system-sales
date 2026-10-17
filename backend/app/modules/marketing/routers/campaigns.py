"""Campaign endpoints for marketing."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Query
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.modules.marketing.campaign import (
    CampaignExecutionService,
    CampaignRun,
)
from app.modules.marketing.schemas import (
    CampaignCreatedOut,
    CampaignListOut,
    CampaignRequest,
    CampaignRunProgressOut,
    CampaignRunStartedOut,
    CampaignRunStateOut,
    CampaignStartRequest,
    ConversionListOut,
)
from app.modules.marketing.service import MarketingService

from ._deps import (
    MAX_PAGE_SIZE,
    EntitlementService,
    TenantCtxDep,
    WriteCtx,
    _wire_money,
    decode_cursor,
    encode_cursor,
    page_slice,
    router,
)


@router.get("/marketing/campaigns", response_model=CampaignListOut)
async def list_campaigns(
    ctx: TenantCtxDep,
    status: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
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
                # None stays None: an unbudgeted campaign is not a 0.00 one.
                "budget": None if c.budget is None else _wire_money(c.budget),
                "created_at": c.created_at.isoformat(),
            }
            for c in page
        ],
        "next_cursor": next_cursor,
    }


@router.post("/marketing/campaigns", status_code=201, response_model=CampaignCreatedOut)
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
        "budget": None if campaign.budget is None else _wire_money(campaign.budget),
    }


@router.get("/marketing/campaigns/{campaign_id}/conversions", response_model=ConversionListOut)
async def list_campaign_conversions(
    campaign_id: uuid.UUID,
    ctx: TenantCtxDep,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
):
    """Conversions this campaign's touchpoints took part in.

    ``attribution_models`` names which VIEW credits the campaign — the models are
    alternative readings of the same order, so the rows are not additive.

    Paged by keyset, the way ``GET /marketing/campaigns`` pages. It used to page
    by ``offset`` on a table where conversions arrive between two pages, which
    skips and repeats rows, and it reported the page length under a ``count``
    key that read as a total.
    """
    before_created_at, before_id = decode_cursor(cursor) if cursor else (None, None)
    rows = await MarketingService.list_campaign_conversions(
        ctx.session,
        ctx.tenant_id,
        campaign_id,
        limit=limit + 1,
        before_created_at=before_created_at,
        before_id=before_id,
    )
    # The rows are (conversion, models) pairs, so the cursor is taken from the
    # conversion of the last row of the PAGE rather than through page_slice,
    # which reads ``.created_at`` off the row object itself.
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = (
        encode_cursor(page[-1][0].created_at, page[-1][0].id) if has_more and page else None
    )
    return {
        "items": [
            {
                "id": str(c.id),
                "order_id": str(c.order_id) if c.order_id else None,
                "customer_id": str(c.customer_id) if c.customer_id else None,
                "type": c.type,
                "value": None if c.value is None else _wire_money(c.value),
                "currency": c.currency,
                "occurred_at": c.occurred_at.isoformat() if c.occurred_at else None,
                "attribution_models": models,
            }
            for c, models in page
        ],
        "next_cursor": next_cursor,
    }


@router.post(
    "/campaigns/{campaign_id}/start", status_code=201, response_model=CampaignRunStartedOut
)
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


@router.post("/campaigns/runs/{run_id}/pause", response_model=CampaignRunStateOut)
async def pause_campaign(run_id: uuid.UUID, ctx: WriteCtx):
    """§175: Pause a running campaign."""
    run = await CampaignExecutionService.pause(ctx.session, ctx.tenant_id, run_id)
    return {"id": str(run.id), "status": run.status}


@router.post("/campaigns/runs/{run_id}/resume", response_model=CampaignRunStateOut)
async def resume_campaign(run_id: uuid.UUID, ctx: WriteCtx):
    """§175: Resume a paused campaign."""
    run = await CampaignExecutionService.resume(ctx.session, ctx.tenant_id, run_id)
    return {"id": str(run.id), "status": run.status}


@router.get("/campaigns/runs/{run_id}", response_model=CampaignRunProgressOut)
async def get_campaign_run(run_id: uuid.UUID, ctx: TenantCtxDep):
    """Get campaign run status and progress."""
    run = (
        await ctx.session.execute(
            select(CampaignRun).where(
                CampaignRun.tenant_id == ctx.tenant_id,
                CampaignRun.id == run_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
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
