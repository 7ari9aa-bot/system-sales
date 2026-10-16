"""Touchpoint, lead, conversion, and journey endpoints for marketing."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Query
from sqlalchemy import select

from app.modules.marketing.journey import (
    JourneyExecutionService,
    JourneyRun,
)
from app.modules.marketing.schemas import (
    ConversionOut,
    ConversionRequest,
    JourneyRunListOut,
    JourneyRunStartedOut,
    JourneyStartRequest,
    LeadOut,
    LeadRequest,
    LeadStatusOut,
    LeadStatusRequest,
    TouchpointCreatedOut,
    TouchpointRequest,
)
from app.modules.marketing.service import MarketingService
from ._deps import (
    MAX_PAGE_SIZE,
    TenantCtxDep,
    WriteCtx,
    _wire_money,
    paginate,
    router,
)


@router.post("/marketing/touchpoints", status_code=201, response_model=TouchpointCreatedOut)
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


@router.post("/marketing/leads", status_code=201, response_model=LeadOut)
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


@router.patch("/marketing/leads/{lead_id}/status", response_model=LeadStatusOut)
async def update_lead_status(lead_id: uuid.UUID, ctx: WriteCtx, body: LeadStatusRequest):
    lead = await MarketingService.update_lead_status(
        ctx.session, ctx.tenant_id, lead_id, body.status
    )
    return {"id": str(lead.id), "status": lead.status}


@router.post("/marketing/conversions", status_code=201, response_model=ConversionOut)
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
        # A conversion with no recorded value has no money to report — null,
        # never the "0.00" that would read as a zero-value purchase.
        "value": None if conversion.value is None else _wire_money(conversion.value),
        "currency": conversion.currency,
        "occurred_at": conversion.occurred_at.isoformat() if conversion.occurred_at else None,
    }


@router.post("/journeys/{journey_id}/start", status_code=201, response_model=JourneyRunStartedOut)
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


@router.get("/journeys/{journey_id}/runs", response_model=JourneyRunListOut)
async def list_journey_runs(
    journey_id: uuid.UUID,
    ctx: TenantCtxDep,
    status: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
):
    """List journey runs for a journey.

    Ordered by ``(created_at, id) DESC`` — the pair the cursor encodes from. The
    query used to carry a bare ``LIMIT`` with no ``ORDER BY`` at all, so Postgres
    returned rows in whatever order it liked and page 2 was not page 2 of the
    same query (gap P7).
    """
    q = select(JourneyRun).where(
        JourneyRun.tenant_id == ctx.tenant_id,
        JourneyRun.journey_id == journey_id,
    )
    if status:
        q = q.where(JourneyRun.status == status)
    rows, next_cursor = await paginate(ctx.session, q, cursor=cursor, limit=limit)
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
        ],
        "next_cursor": next_cursor,
    }
