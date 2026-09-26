"""MARKETING & ANALYTICS routes — campaigns, touchpoint capture, leads,
analytics summary.

Reads use plain TenantCtxDep; writes require the ``marketing:write``
permission. All routes run inside the request transaction owned by get_db —
services never commit.

Money in a response leaves as a Decimal STRING (ADR-001/§47, the same shape
``orders/router.py`` ships for ``grand_total``) so no client can lose a cent to a
float64; ratios (``budget_roas``) and counts (``conversions``) are not money and
stay numbers, and an amount that does not exist stays ``null`` rather than 0.00.

Every route below publishes a model (gap P8). The models live in
``marketing/schemas.py``, which carries the reasoning for each field type; what
stays here is the routing, the window and page bounds, and the payload builders
that turn read-model rows into those shapes. A handler still returns the plain
``dict`` it always returned and ``response_model=`` validates it at the edge —
that is where an amount that left as a float gets refused before a client ever
sees it, which is the whole reason the models are worth having here.
"""

from __future__ import annotations

import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.pagination import decode_cursor, encode_cursor, page_slice, paginate
from app.modules.billing.service import EntitlementService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.marketing import analytics
from app.modules.marketing.attribution_service import AttributionService
from app.modules.marketing.campaign import CampaignExecutionService
from app.modules.marketing.journey import JourneyExecutionService
from app.modules.marketing.schemas import (
    # ``CampaignOut`` and ``RoasRowOut`` are not named by any route below — a
    # list model references them — but they are imported explicitly because
    # they ARE this module's contract surface: callers (and the contract suite)
    # reach a module's wire models as ``marketing_router.CampaignOut``.
    AttributionViewOut,  # noqa: F401 — an arm of the campaign rollup, re-exported
    CampaignAttributionOut,
    CampaignCreatedOut,
    CampaignListOut,
    CampaignOut,  # noqa: F401 — the campaign row shape, re-exported
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
    RoasRowOut,  # noqa: F401 — the ROI row shape, re-exported
    TouchpointCreatedOut,
    TouchpointRequest,
)
from app.modules.marketing.service import MarketingService

router = APIRouter(tags=["marketing"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("marketing:write"))]

#: The one window length a merchant may ask a marketing read model for, in days.
#: ``days`` is bound into ``occurred_at >= now() - timedelta(days=days)`` and into
#: a ``date_trunc`` bucketing pass over ``order_payments``, so an unbounded value
#: is not a wider report, it is a full scan behind a screen the dashboard
#: re-polls every twenty seconds. ``days=0`` and a negative were accepted and
#: answered 200: a negative does not look backwards, it flips the interval and
#: selects the FUTURE (gap P7, ``docs/GAP_REGISTER.md``). 1..365 is the same
#: ceiling ``/analytics/overview`` and ``/marketing/attribution`` already held.
MAX_WINDOW_DAYS = 365

#: The one page size, and the one cursor fetch. ``limit + 1`` is how
#: :func:`app.core.pagination.page_slice` knows whether a next page exists.
MAX_PAGE_SIZE = 200

# Query params are declared `Annotated[type, Query(...)] = <value>`, never
# `name: type = Query(...)` — see the parameter-declaration rule in
# app/modules/analytics/router.py (CI run 35959902953) and the full-app gate in
# tests/test_route_parameter_declarations.py. The same file is why nothing below
# resolves a default with a `Query(default_factory=...)`.

#: ADR-001/§47 — an AMOUNT leaves as a Decimal string, the same helper the read
#: models use, so this module has exactly one money-to-wire rule. A ratio
#: (``budget_roas``) and a count (``conversions``) are not money and are never
#: passed through it.
_wire_money = analytics.wire_money


def _missing_query_params(*names: str) -> NoReturn:
    """Answer 422 in the shape the framework uses for a bad query parameter.

    ``GET /marketing/attribution`` used to answer this case with a 200 and a
    prose ``{"error": ...}`` body — which no client checks, which no response
    model can describe, and which is the same class of lie as
    ``{"detail": "not found"}`` at HTTP 200 (gap P3). The refusal is the field
    list FastAPI itself emits, built the way ``analytics/router._bind_window``
    builds its own, so one client reads both.
    """
    raise HTTPException(
        status_code=422,
        detail=[
            {
                "type": "missing",
                "loc": ["query", name],
                "msg": f"provide {' or '.join(names)}",
                "input": None,
            }
            for name in names
        ],
    )


# --------------------------------------------------------- campaigns ----


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


# ------------------------------------------------------- touchpoints ----


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


# ------------------------------------------------------------- leads ----


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


# ------------------------------------------------------ conversions ----


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


@router.get(
    "/marketing/campaigns/{campaign_id}/conversions", response_model=ConversionListOut
)
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


# --------------------------------------------------------- analytics ----


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
    rows = await analytics.daily_orders(
        ctx.session, ctx.tenant_id, days=days, timezone=timezone
    )
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


# ------------------------------------------------------------- journeys ----


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
    from sqlalchemy import select

    from app.modules.marketing.journey import JourneyRun

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


# --------------------------------------------------------- attribution ----


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
