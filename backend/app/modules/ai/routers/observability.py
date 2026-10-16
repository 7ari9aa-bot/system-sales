"""AI observability routes — usage summary, traces (§44), evaluations (§169)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import NotFoundError
from app.modules.ai.models import AIUsage
from app.modules.ai.routers._deps import ApproveCtx, SettingsCtx, TenantCtxDep
from app.modules.ai.schemas import (
    EvaluationList,
    EvaluationOut,
    TraceCorrelationOut,
    TraceRunOut,
    TraceSummaryOut,
    UsageSummaryOut,
    decimal_amount,
)
from app.modules.ai.trace import (
    AITraceService,
    create_evaluation,
    list_evaluations,
    update_evaluation_status,
)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/usage/summary", response_model=UsageSummaryOut)
async def usage_summary(ctx: TenantCtxDep, days: Annotated[int, Query(ge=1, le=365)] = 30):
    since = date.today() - timedelta(days=days)
    rows = (
        await ctx.session.execute(
            select(
                AIUsage.period_date,
                func.coalesce(func.sum(AIUsage.tokens_in), 0),
                func.coalesce(func.sum(AIUsage.tokens_out), 0),
                func.coalesce(func.sum(AIUsage.cost), 0),
            )
            .where(AIUsage.tenant_id == ctx.tenant_id, AIUsage.period_date >= since)
            .group_by(AIUsage.period_date)
            .order_by(AIUsage.period_date.asc())
        )
    ).all()
    return {
        "days": days,
        "summary": [
            {
                "date": period.isoformat(),
                "tokens_in": int(tokens_in),
                "tokens_out": int(tokens_out),
                # §47/ADR-053: AI spend is an AMOUNT, so it crosses JSON as a
                # Decimal string — `Numeric(18,8)` carries sub-cent money a
                # float64 cannot round-trip. The token columns beside it are
                # counts and stay numbers. `decimal_amount` rather than `str`:
                # the plain-text spelling of 0.00000002 is "2E-8", which is exact
                # but is not the fixed-point decimal this field promises.
                "cost": decimal_amount(cost),
            }
            for period, tokens_in, tokens_out, cost in rows
        ],
        # §55 forbids the browser from doing business aggregation, so the period
        # total is answered here rather than left to the caller: SQL has already
        # grouped by day, and adding the days on a Decimal is exact. Summing it
        # client-side would also be the wrong shape — the money would pass
        # through float64 on its way to a `toFixed`.
        "totals": {
            "cost": decimal_amount(sum((Decimal(cost) for _, _, _, cost in rows), Decimal(0))),
            "tokens_in": sum(int(tokens_in) for _, tokens_in, _, _ in rows),
            "tokens_out": sum(int(tokens_out) for _, _, tokens_out, _ in rows),
        },
    }


# ---------- trace (§44) ----------
#
# "What did the AI actually do, and why?" — assembled from agent_runs and its
# model_calls / tool_calls children. Reads only need an authenticated tenant
# context: a trace is operational evidence, not a settings mutation.


@router.get("/trace/runs/{run_id}", response_model=TraceRunOut)
async def trace_run(run_id: uuid.UUID, ctx: TenantCtxDep):
    return await AITraceService.for_run(ctx.session, ctx.tenant_id, run_id)


@router.get("/trace/correlation/{correlation_id}", response_model=TraceCorrelationOut)
async def trace_correlation(correlation_id: str, ctx: TenantCtxDep):
    runs = await AITraceService.by_correlation(ctx.session, ctx.tenant_id, correlation_id)
    return {"correlation_id": correlation_id, "runs": runs}


@router.get("/trace/summary", response_model=TraceSummaryOut)
async def trace_summary(ctx: TenantCtxDep, days: Annotated[int, Query(ge=1, le=365)] = 7):
    return await AITraceService.summary(ctx.session, ctx.tenant_id, days=days)


# ---------- evaluations (§169) ----------
#
# Offline evaluation of an agent/prompt version before rollout.


class EvaluationCreateRequest(BaseModel):
    agent_id: uuid.UUID
    prompt_version: int = Field(default=1, ge=1)
    dataset_ref: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class EvaluationUpdateRequest(BaseModel):
    status: str = Field(description="pending | running | passed | failed | approved | rolled_back")
    quality_metrics: dict | None = None
    rollout_status: str | None = Field(default=None, description="none | canary | full")
    notes: str | None = None


def _evaluation_out(ev) -> dict:
    return {
        "id": str(ev.id),
        "agent_id": str(ev.agent_id),
        "prompt_version": ev.prompt_version,
        "dataset_ref": ev.dataset_ref,
        "status": ev.status,
        "quality_metrics": ev.quality_metrics or {},
        "rollout_status": ev.rollout_status,
        "notes": ev.notes,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
        "updated_at": ev.updated_at.isoformat() if ev.updated_at else None,
    }


@router.get("/evaluations", response_model=EvaluationList)
async def list_eval(
    ctx: TenantCtxDep,
    agent_id: Annotated[uuid.UUID | None, Query()] = None,
):
    rows = await list_evaluations(ctx.session, ctx.tenant_id, agent_id=agent_id)
    return {"items": [_evaluation_out(ev) for ev in rows]}


@router.post("/evaluations", status_code=201, response_model=EvaluationOut)
async def create_eval(body: EvaluationCreateRequest, ctx: SettingsCtx):
    ev = await create_evaluation(
        ctx.session,
        ctx.tenant_id,
        agent_id=body.agent_id,
        prompt_version=body.prompt_version,
        dataset_ref=body.dataset_ref,
        notes=body.notes,
    )
    return _evaluation_out(ev)


@router.patch("/evaluations/{evaluation_id}", response_model=EvaluationOut)
async def update_eval(
    evaluation_id: uuid.UUID,
    body: EvaluationUpdateRequest,
    ctx: SettingsCtx,
):
    ev = await update_evaluation_status(
        ctx.session,
        ctx.tenant_id,
        evaluation_id,
        status=body.status,
        quality_metrics=body.quality_metrics,
        rollout_status=body.rollout_status,
        notes=body.notes,
    )
    return _evaluation_out(ev)


# ---------- §169 canary rollout gate ----------
#
# Dedicated submit/status/approve flow — complements the trace.py-based CRUD
# above with a service-level pipeline that gates rollout behind explicit approval.


class EvaluationSubmitRequest(BaseModel):
    agent_id: uuid.UUID | None = None
    agent_version_id: uuid.UUID | None = None
    prompt_version: int = 1
    dataset_id: str | None = Field(default=None, max_length=255)
    results: dict = Field(default_factory=dict)


@router.post("/evaluations/submit", status_code=201, response_model=EvaluationOut)
async def submit_evaluation(body: EvaluationSubmitRequest, ctx: SettingsCtx):
    from app.modules.ai.evaluation import AIEvaluationService

    ev = await AIEvaluationService.submit_evaluation(
        ctx.session,
        ctx.tenant_id,
        agent_id=body.agent_id,
        agent_version_id=body.agent_version_id,
        prompt_version=body.prompt_version,
        dataset_id=body.dataset_id,
        results=body.results,
    )
    return _evaluation_out(ev)


@router.get("/evaluations/{agent_version_id}/status", response_model=EvaluationOut)
async def evaluation_status(agent_version_id: uuid.UUID, ctx: TenantCtxDep):
    from app.modules.ai.evaluation import AIEvaluationService

    ev = await AIEvaluationService.get_evaluation_status(
        ctx.session, ctx.tenant_id, agent_version_id
    )
    if ev is None:
        raise NotFoundError(f"no evaluation found for agent {agent_version_id}")
    return _evaluation_out(ev)


@router.post("/evaluations/{agent_version_id}/approve", response_model=EvaluationOut)
async def approve_evaluation(agent_version_id: uuid.UUID, ctx: ApproveCtx):
    from app.modules.ai.evaluation import AIEvaluationService

    ev = await AIEvaluationService.approve_rollout(ctx.session, ctx.tenant_id, agent_version_id)
    return _evaluation_out(ev)
