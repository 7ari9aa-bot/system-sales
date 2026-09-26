"""AI routes — knowledge management, agent admin, usage reporting.

Write endpoints sit behind the ``settings:write`` permission (same gate the
platform settings use); reads only need an authenticated tenant context.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.errors import NotFoundError
from app.core.pagination import paginate
from app.modules.ai import knowledge
from app.modules.ai.approvals import ApprovalService
from app.modules.ai.models import Agent, AIUsage, KnowledgeItem, Memory
from app.modules.ai.policy import AIProviderPolicyService
from app.modules.ai.schemas import (
    AgentCreateRequest,
    AgentOut,
    ApprovalDecisionOut,
    ApprovalList,
    EvaluationList,
    EvaluationOut,
    KnowledgeIngested,
    KnowledgeIngestRequest,
    KnowledgeList,
    KnowledgeSearchHit,
    MemoryList,
    MemoryOut,
    PolicyList,
    PolicyOut,
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
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

router = APIRouter(prefix="/ai", tags=["ai"])

SettingsCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

# Query params are declared `Annotated[type, Query(...)] = <value>` (a required
# one keeps no default), never `name: type = Query(...)` — see the
# parameter-declaration rule in app/modules/analytics/router.py and the full-app
# gate in tests/test_route_parameter_declarations.py.


@router.post("/knowledge", status_code=201, response_model=KnowledgeIngested)
async def ingest_knowledge(ctx: SettingsCtx, body: KnowledgeIngestRequest):
    item = await knowledge.ingest_knowledge(
        ctx.session,
        ctx.tenant_id,
        title=body.title,
        content=body.content,
        source_type=body.source_type,
        source_ref=body.source_ref,
    )
    # §157: the two columns that decide whether retrieval may show this row at
    # all. Shipping only `status` left the visibility of what staff just
    # published unreadable from the write's own answer.
    return {"id": str(item.id), "status": item.status, "visibility": item.visibility}


@router.get("/knowledge/search", response_model=list[KnowledgeSearchHit])
async def search_knowledge(
    ctx: TenantCtxDep,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
):
    results = await knowledge.search_knowledge(ctx.session, ctx.tenant_id, q, limit=limit)
    return [
        {
            "id": str(item.id),
            "title": item.title,
            "source_type": item.source_type,
            "content": item.content,
            "distance": distance,
            "visibility": item.visibility,
        }
        for item, distance in results
    ]


@router.get("/agents")
async def list_agents(ctx: TenantCtxDep) -> list[AgentOut]:
    rows = (
        await ctx.session.execute(
            select(Agent).where(Agent.tenant_id == ctx.tenant_id).order_by(Agent.created_at.asc())
        )
    ).scalars()
    return [AgentOut.model_validate(agent) for agent in rows]


@router.post("/agents", status_code=201)
async def create_agent(ctx: SettingsCtx, body: AgentCreateRequest) -> AgentOut:
    agent = Agent(
        tenant_id=ctx.tenant_id,
        name=body.name,
        model=body.model,
        system_prompt=body.system_prompt,
        description=body.description,
    )
    ctx.session.add(agent)
    await ctx.session.flush()
    return AgentOut.model_validate(agent)


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


@router.get("/knowledge", response_model=KnowledgeList)
async def list_knowledge(
    ctx: SettingsCtx,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    stmt = select(KnowledgeItem).where(KnowledgeItem.tenant_id == ctx.tenant_id)
    items, next_cursor = await paginate(ctx.session, stmt, cursor=cursor, limit=limit)
    return {
        "items": [
            {
                "id": str(item.id),
                "title": item.title,
                "source_type": item.source_type,
                "source_ref": item.source_ref,
                "status": item.status,
                # §157 was NEVER on the wire: the column retrieval filters on
                # before a row may reach a model's context is the one thing the
                # review surface cannot be allowed to omit.
                "visibility": item.visibility,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
        "next_cursor": next_cursor,
    }


# ---------- memories (§158 staff review surface) ----------
#
# A memory claim is governed only while staff can review, edit, delete and
# invalidate it. Writes are gated like platform settings; reads too — a
# memory is customer-attributed free text, not public data.


class MemoryCreateRequest(BaseModel):
    kind: str = Field(pattern="^(summary|preference|fact)$")
    content: str = Field(min_length=1, max_length=8000)
    customer_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class MemoryEditRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=8000)
    kind: str | None = Field(default=None, pattern="^(summary|preference|fact)$")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


def _memory_out(m: Memory) -> dict:
    return {
        "id": str(m.id),
        "kind": m.kind,
        "content": m.content,
        "source": m.source,
        "status": m.status,
        "confidence": float(m.confidence) if m.confidence is not None else None,
        "customer_id": str(m.customer_id) if m.customer_id else None,
        "conversation_id": str(m.conversation_id) if m.conversation_id else None,
        "actor_id": str(m.actor_id) if m.actor_id else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "verified_at": m.verified_at.isoformat() if m.verified_at else None,
        "invalidated_at": m.invalidated_at.isoformat() if m.invalidated_at else None,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
    }


async def _load_memory(ctx: TenantContext, memory_id: uuid.UUID) -> Memory:
    """Fetch the row for mutation — tenant filter AND RLS, never either alone."""
    row = (
        await ctx.session.execute(
            select(Memory).where(Memory.id == memory_id, Memory.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"memory {memory_id} not found")
    return row


@router.get("/memories", response_model=MemoryList)
async def list_memories(
    ctx: SettingsCtx,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[str | None, Query(description="active | invalidated")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    stmt = select(Memory).where(Memory.tenant_id == ctx.tenant_id)
    if customer_id is not None:
        stmt = stmt.where(Memory.customer_id == customer_id)
    if status is not None:
        stmt = stmt.where(Memory.status == status)
    items, next_cursor = await paginate(ctx.session, stmt, cursor=cursor, limit=limit)
    return {"items": [_memory_out(m) for m in items], "next_cursor": next_cursor}


@router.post("/memories", status_code=201, response_model=MemoryOut)
async def create_memory(body: MemoryCreateRequest, ctx: SettingsCtx):
    """Record a STAFF-entered memory (§158: human-attributed provenance)."""
    embedding = await knowledge.embed_text(ctx.session, ctx.tenant_id, body.content)
    memory = await knowledge.add_memory(
        ctx.session,
        ctx.tenant_id,
        customer_id=body.customer_id,
        conversation_id=body.conversation_id,
        kind=body.kind,
        content=body.content,
        embedding=embedding,
        source="staff_entered",
        confidence=body.confidence,
        actor_id=ctx.user.id,
    )
    return _memory_out(memory)


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def edit_memory(memory_id: uuid.UUID, body: MemoryEditRequest, ctx: SettingsCtx):
    memory = await _load_memory(ctx, memory_id)
    if body.content is not None:
        memory.content = body.content
        memory.embedding = await knowledge.embed_text(ctx.session, ctx.tenant_id, body.content)
    if body.kind is not None:
        memory.kind = body.kind
    if body.confidence is not None:
        memory.confidence = body.confidence
    await ctx.session.flush()
    return _memory_out(memory)


@router.post("/memories/{memory_id}/invalidate", response_model=MemoryOut)
async def invalidate_memory(memory_id: uuid.UUID, ctx: SettingsCtx):
    """Take a claim out of service (§158) — recall filters it, the row stays.

    Idempotent: a second invalidate keeps the FIRST timestamp, so the audit
    trail records when staff actually retired the claim, not when someone
    re-clicked the button.
    """
    memory = await _load_memory(ctx, memory_id)
    if memory.status != "invalidated":
        memory.status = "invalidated"
        memory.invalidated_at = datetime.now(UTC)
        await ctx.session.flush()
    return _memory_out(memory)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: uuid.UUID, ctx: SettingsCtx) -> None:
    """Hard purge (§158 delete) — distinct from invalidate, which keeps the
    row for audit. GDPR-style erasure requests go through the privacy
    deletion chain instead, which handles every related table."""
    memory = await _load_memory(ctx, memory_id)
    await ctx.session.delete(memory)
    await ctx.session.flush()


# ---------- approvals (§135) ----------
#
# A HIGH-risk tool call parks the run in WAITING_APPROVAL and the action has
# NOT happened. These routes are how a human releases (or kills) it — without
# them the run would wait forever with no way to decide.

class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(description="APPROVED | REJECTED | CANCELLED")
    reason: str | None = Field(default=None, max_length=512)


def _approval_out(a) -> dict:
    return {
        "id": str(a.id),
        "status": a.status,
        "action": a.action,
        "risk_level": a.risk_level,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "conversation_id": str(a.conversation_id) if a.conversation_id else None,
        "run_id": str(a.run_id) if a.run_id else None,
        "payload": a.payload or {},
        # §135 review G-02: the digest is what makes an approval cover the
        # ARGUMENTS it approved rather than merely the action name, and
        # `approved_by_user_id` is who owns that decision. A queue that cannot
        # be audited after the fact is not a governance surface, so both ride
        # with the row.
        "payload_hash": a.payload_hash,
        "requested_by": a.requested_by,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        "consumed_at": a.consumed_at.isoformat() if a.consumed_at else None,
        "approved_by_user_id": str(a.approved_by_user_id) if a.approved_by_user_id else None,
        "rejection_reason": a.rejection_reason,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/approvals", response_model=ApprovalList)
async def list_approvals(
    ctx: TenantCtxDep,
    status: Annotated[str | None, Query(description="PENDING | APPROVED | ...")] = None,
):
    rows, truncated = await ApprovalService.list_for_tenant(
        ctx.session, ctx.tenant_id, status=status
    )
    return {"items": [_approval_out(a) for a in rows], "truncated": truncated}


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalDecisionOut)
async def decide_approval(
    approval_id: uuid.UUID,
    body: ApprovalDecisionRequest,
    ctx: SettingsCtx,
):
    """Approve, reject or cancel a parked HIGH-risk action.

    Approving RE-ENQUEUES the conversation so the agent re-evaluates context and
    retries: the gate then finds the granted approval and executes the action
    exactly once. A customer who replied while the approval was pending makes it
    stale, which is why the run is re-planned rather than blindly continued.
    """
    from app.core.events.writer import add_outbox_event

    approval = await ApprovalService.decide(
        ctx.session,
        ctx.tenant_id,
        approval_id,
        decision=body.decision,
        decided_by_user_id=ctx.user.id,
        rejection_reason=body.reason,
    )

    resumed = False
    if approval.status == "APPROVED" and approval.conversation_id is not None:
        await add_outbox_event(
            ctx.session,
            aggregate_type="message",
            aggregate_id=approval.id,
            event_type="message.received",
            tenant_id=ctx.tenant_id,
            payload={
                "conversation_id": str(approval.conversation_id),
                "resumed_approval_id": str(approval.id),
            },
        )
        resumed = True

    return {**_approval_out(approval), "resumed": resumed}


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
async def trace_summary(
    ctx: TenantCtxDep, days: Annotated[int, Query(ge=1, le=365)] = 7
):
    return await AITraceService.summary(ctx.session, ctx.tenant_id, days=days)


# ---------- provider policies (§43) ----------
#
# Data-egress governance: which providers/models may receive tenant data.
# Writes are gated like platform settings (settings:write).


class ProviderPolicyUpsertRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=31)
    status: str = Field(default="allowed", description="allowed | denied")
    allowed_models: list[str] = Field(default_factory=list)
    pii_redaction_required: bool = False
    data_classification: str = Field(default="internal", max_length=31)
    data_residency: str | None = Field(
        default=None, max_length=31, description="§43 region data may not leave, e.g. 'eu'"
    )
    retention_terms: str | None = Field(
        default=None, max_length=2000, description="§43 documented provider retention terms"
    )
    notes: str | None = None


def _policy_out(policy) -> dict:
    return {
        "id": str(policy.id),
        "provider": policy.provider,
        "status": policy.status,
        "allowed_models": list(policy.allowed_models or []),
        "pii_redaction_required": bool(policy.pii_redaction_required),
        "data_classification": policy.data_classification,
        "data_residency": policy.data_residency,
        "retention_terms": policy.retention_terms,
        "notes": policy.notes,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }


@router.get("/provider-policies", response_model=PolicyList)
async def list_provider_policies(ctx: SettingsCtx):
    policies = await AIProviderPolicyService.list_policies(ctx.session, ctx.tenant_id)
    return {"items": [_policy_out(p) for p in policies]}


@router.put("/provider-policies", response_model=PolicyOut)
async def upsert_provider_policy(body: ProviderPolicyUpsertRequest, ctx: SettingsCtx):
    policy = await AIProviderPolicyService.upsert(
        ctx.session,
        ctx.tenant_id,
        provider=body.provider,
        status=body.status,
        allowed_models=body.allowed_models,
        pii_redaction_required=body.pii_redaction_required,
        data_classification=body.data_classification,
        data_residency=body.data_residency,
        retention_terms=body.retention_terms,
        notes=body.notes,
    )
    return _policy_out(policy)


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
    agent_version_id: uuid.UUID
    dataset_id: str | None = Field(default=None, max_length=255)
    results: dict = Field(default_factory=dict)


@router.post("/evaluations/submit", status_code=201, response_model=EvaluationOut)
async def submit_evaluation(body: EvaluationSubmitRequest, ctx: SettingsCtx):
    from app.modules.ai.evaluation import AIEvaluationService

    ev = await AIEvaluationService.submit_evaluation(
        ctx.session,
        ctx.tenant_id,
        agent_version_id=body.agent_version_id,
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
async def approve_evaluation(agent_version_id: uuid.UUID, ctx: SettingsCtx):
    from app.modules.ai.evaluation import AIEvaluationService

    ev = await AIEvaluationService.approve_rollout(
        ctx.session, ctx.tenant_id, agent_version_id
    )
    return _evaluation_out(ev)
