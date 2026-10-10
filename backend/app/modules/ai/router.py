"""AI routes — knowledge management, agent admin, usage reporting.

Write endpoints sit behind the ``settings:write`` permission (same gate the
platform settings use); reads only need an authenticated tenant context.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.idempotency import IfMatch, apply_etag, apply_versioned_update
from app.core.pagination import paginate
from app.modules.ai import knowledge
from app.modules.ai.agents.sales_intelligence.agent import (
    AnalysisOut as SalesAnalysisOut,
)
from app.modules.ai.agents.sales_intelligence.agent import (
    AnalysisRequest as SalesAnalysisRequest,
)
from app.modules.ai.agents.sales_intelligence.agent import (
    AnalysisStoredOut as SalesAnalysisStoredOut,
)
from app.modules.ai.agents.sales_intelligence.agent import (
    DeepAnalysisQueuedOut as SalesDeepAnalysisQueuedOut,
)
from app.modules.ai.agents.sales_intelligence.agent import (
    FindingOut,
    FindingStoredOut,
)
from app.modules.ai.approvals import ApprovalService
from app.modules.ai.chat import service as chat_service
from app.modules.ai.chat.schemas import (
    MessageOut as SalesChatMessageOut,
)
from app.modules.ai.chat.schemas import (
    MessageSendRequest as SalesChatMessageSendRequest,
)
from app.modules.ai.chat.schemas import (
    ThreadCreateRequest as SalesChatThreadCreateRequest,
)
from app.modules.ai.chat.schemas import (
    ThreadOut as SalesChatThreadOut,
)
from app.modules.ai.chat.schemas import (
    ThreadUpdateRequest as SalesChatThreadUpdateRequest,
)
from app.modules.ai.chat.turns import retry_chat_turn, run_chat_turn
from app.modules.ai.models import Agent, AIHandover, AIUsage, KnowledgeItem, Memory
from app.modules.ai.policy import AIProviderPolicyService
from app.modules.ai.schemas import (
    HANDOVER_OUTCOMES,
    AgentCreateRequest,
    AgentDetailOut,
    AgentKindOut,
    AgentOut,
    AgentPublishRequest,
    AgentUpdateRequest,
    AgentVersionOut,
    ApprovalDecisionOut,
    ApprovalList,
    EvaluationList,
    EvaluationOut,
    HandoverList,
    HandoverOut,
    HandoverResolveRequest,
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
SettingsReadCtx = Annotated[TenantContext, Depends(require_permission("settings:read"))]
AnalyticsCtx = Annotated[TenantContext, Depends(require_permission("analytics:read"))]


class require_ai_approve:
    """RBAC gate for a decision only a human may make: ``ai:approve``.

    Not plain ``require_permission("ai:approve")`` because the tenant owner
    passes without the code being on their role — the owner is the one who would
    have to seed it onto themselves before they could approve anything.

    A class with a ``code`` attribute, mirroring ``require_permission``, so the
    gate a route declares stays introspectable from the outside; as a bare
    closure it was invisible, and the test that pins this route's gate read it
    as "gated by nothing".
    """

    code = "ai:approve"

    async def __call__(self, ctx: TenantCtxDep) -> TenantContext:
        if self.code not in ctx.permission_codes and ctx.role_code != "owner":
            raise PermissionDeniedError(f"missing permission: {self.code}")
        return ctx


ApproveCtx = Annotated[TenantContext, Depends(require_ai_approve())]

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


@router.get("/agent-kinds")
async def list_agent_kinds(ctx: TenantCtxDep) -> list[AgentKindOut]:
    """List all registered agent kinds and their definitions.

    This is the platform's extensibility surface: a new agent kind added
    to the registry appears here automatically."""
    from app.modules.ai.core.registry import AgentRegistry
    from app.modules.ai.schemas import AgentCapabilityOut

    return [
        AgentKindOut(
            kind=defn.kind,
            name=defn.name,
            description=defn.description,
            definition_version=defn.definition_version,
            default_model=defn.default_model,
            capabilities=[
                AgentCapabilityOut(name=c.name, description=c.description, required=c.required)
                for c in defn.capabilities
            ],
            default_tools=defn.default_tools,
            allowed_tools=defn.allowed_tools,
            task_types=defn.task_types,
            guardrail_profile=defn.guardrail_profile,
            provisioning_policy=defn.provisioning_policy,
        )
        for defn in AgentRegistry.get_all()
    ]


@router.get("/agents")
async def list_agents(ctx: TenantCtxDep) -> list[AgentOut]:
    rows = (
        await ctx.session.execute(
            select(Agent).where(Agent.tenant_id == ctx.tenant_id).order_by(Agent.created_at.asc())
        )
    ).scalars()
    return [AgentOut.model_validate(agent) for agent in rows]


@router.post("/sales/analyses")
async def create_sales_analysis(ctx: AnalyticsCtx, body: SalesAnalysisRequest) -> SalesAnalysisOut:
    """§12.1 — one sales question → one evidence-backed analysis.

    The store's first active agent runs the investigation with the SI tools
    attached idempotently; the SI gates hold before anything reaches the
    merchant."""
    from app.modules.ai.agents.sales_intelligence.agent import (
        ensure_si_tools,
        run_sales_analysis,
    )
    from app.modules.ai.core.resolver import resolve_agent_by_kind

    agent = await resolve_agent_by_kind(ctx.session, ctx.tenant_id, "sales_intelligence")

    await ensure_si_tools(ctx.session, ctx.tenant_id, agent.id)
    result = await run_sales_analysis(
        ctx.session, ctx.tenant_id, agent_id=agent.id, question=body.question
    )
    return SalesAnalysisOut(
        outcome=result.outcome.value,
        answer=result.answer,
        findings=[
            FindingOut(
                statement=f.statement,
                type=f.type,
                relationship=f.relationship.value,
                confidence=f.confidence,
                confidence_reasons=f.confidence_reasons,
                evidence_refs=f.evidence_refs,
            )
            for f in result.findings
        ],
        facts=result.facts,
        data_quality_status=result.data_quality.status.value,
        guardrail_reason=result.guardrail_reason,
    )


@router.post(
    "/sales/deep-analyses",
    status_code=202,
    response_model=SalesDeepAnalysisQueuedOut,
)
async def create_deep_analysis(
    ctx: AnalyticsCtx, body: SalesAnalysisRequest
) -> SalesDeepAnalysisQueuedOut:
    """§13 — queue a DEEP analysis: durable background job, streamed progress.

    The shell row stores the question (the one input a background handler
    cannot otherwise receive); the Job row is the control surface the
    dashboard polls. 202 Accepted — the analysis has NOT run yet."""
    from app.modules.ai.agents.sales_intelligence.agent import ensure_si_tools
    from app.modules.ai.core.resolver import resolve_agent_by_kind
    from app.modules.analytics.persistence import create_pending_analysis
    from app.modules.platform.service import JobService

    agent = await resolve_agent_by_kind(ctx.session, ctx.tenant_id, "sales_intelligence")

    await ensure_si_tools(ctx.session, ctx.tenant_id, agent.id)
    analysis_id = await create_pending_analysis(ctx.session, ctx.tenant_id, question=body.question)
    job = await JobService.create(
        ctx.session,
        ctx.tenant_id,
        kind="si.deep_analysis",
        actor_user_id=ctx.user.id,
        correlation_id=str(analysis_id),
    )
    await ctx.session.commit()
    return SalesDeepAnalysisQueuedOut(job_id=job.id, analysis_id=analysis_id, status="queued")


@router.get("/sales/analyses/{analysis_id}", response_model=SalesAnalysisStoredOut)
async def get_sales_analysis(ctx: AnalyticsCtx, analysis_id: uuid.UUID) -> SalesAnalysisStoredOut:
    """§12.4 — a stored analysis: the immutable pack plus its graded findings."""
    from app.core.errors import NotFoundError
    from app.modules.analytics.persistence import load_analysis

    stored = await load_analysis(ctx.session, ctx.tenant_id, analysis_id)
    if stored is None:
        raise NotFoundError(f"analysis {analysis_id} not found")
    return SalesAnalysisStoredOut(
        analysis_id=stored["analysis_id"],
        run_id=stored["run_id"],
        question=stored["question"],
        outcome=stored["outcome"],
        content_hash=stored["content_hash"],
        model=stored["model"],
        provider=stored["provider"],
        model_version=stored["model_version"],
        prompt_version=stored["prompt_version"],
        created_at=stored["created_at"],
        pack=stored["pack"],
        findings=[
            FindingStoredOut(
                statement=f["statement"],
                type=f["type"],
                relationship=f["relationship"],
                confidence=f["confidence"],
                confidence_reasons=f["confidence_reasons"],
                evidence_refs=f["evidence_refs"],
                materiality=f["materiality"],
            )
            for f in stored["findings"]
        ],
    )


@router.post("/agents", status_code=201)
async def create_agent(ctx: SettingsCtx, body: AgentCreateRequest) -> AgentOut:
    from app.core.errors import ConflictError, ValidationError
    from app.modules.ai.core.registry import AgentRegistry
    from app.modules.ai.models import AgentTool

    defn = AgentRegistry.get_or_none(body.kind)
    if defn is None:
        raise ValidationError(
            f"Unknown agent kind '{body.kind}'. Registered kinds: {AgentRegistry.kinds()}"
        )

    singleton = (defn.provisioning_policy or {}).get("singleton_per_tenant", True)
    if singleton:
        existing = (
            await ctx.session.execute(
                select(Agent).where(
                    Agent.tenant_id == ctx.tenant_id,
                    Agent.kind == body.kind,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(f"Agent of kind '{body.kind}' already exists for this tenant")

    model = body.model or defn.default_model
    base = defn.system_prompt_template
    if (defn.provisioning_policy or {}).get("is_canonical"):
        if body.system_prompt and body.system_prompt.strip():
            custom = body.system_prompt.strip()
            if base and base not in custom:
                system_prompt = f"{base}\n\n[Tenant Instructions]\n{custom}"
            else:
                system_prompt = custom
        else:
            system_prompt = base
    else:
        system_prompt = body.system_prompt or base

    agent = Agent(
        tenant_id=ctx.tenant_id,
        kind=body.kind,
        name=body.name,
        model=model,
        system_prompt=system_prompt,
        description=body.description or defn.description,
    )
    ctx.session.add(agent)
    await ctx.session.flush()

    for tool_name in defn.default_tools:
        if not AgentRegistry.is_tool_authorized(body.kind, tool_name):
            raise ValidationError(
                f"Tool '{tool_name}' is not authorized for agent kind '{body.kind}'"
            )
        ctx.session.add(
            AgentTool(
                tenant_id=ctx.tenant_id,
                agent_id=agent.id,
                name=tool_name,
                policy={},
            )
        )
    if defn.default_tools:
        await ctx.session.flush()

    return AgentOut.model_validate(agent)


@router.get("/agents/{agent_id}/prompt", response_model=AgentDetailOut)
async def get_agent_detail(
    agent_id: uuid.UUID,
    ctx: SettingsReadCtx,
    response: Response,
) -> AgentDetailOut:
    """Fetch one agent including prompt — tenant-isolated by the WHERE clause and RLS."""
    agent = (
        await ctx.session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"agent {agent_id} not found")
    apply_etag(response, agent.version)
    return AgentDetailOut.model_validate(agent)


@router.patch("/agents/{agent_id}", response_model=AgentDetailOut)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdateRequest,
    ctx: SettingsCtx,
    response: Response,
    if_match: IfMatch = None,
) -> AgentDetailOut:
    """Tenant edits their own agent settings / prompt with optimistic concurrency (ADR-060)."""
    agent = (
        await ctx.session.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == ctx.tenant_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"agent {agent_id} not found")

    fields = body.model_dump(exclude_unset=True)
    if fields:
        if "system_prompt" in fields and fields["system_prompt"] is not None:
            from app.modules.ai.core.registry import AgentRegistry

            defn = AgentRegistry.get_or_none(agent.kind)
            if defn and (defn.provisioning_policy or {}).get("is_canonical"):
                base = defn.system_prompt_template
                custom = fields["system_prompt"].strip()
                if base and base not in custom:
                    fields["system_prompt"] = f"{base}\n\n[Tenant Instructions]\n{custom}"
                else:
                    fields["system_prompt"] = custom
        await apply_versioned_update(ctx.session, agent, if_match, fields)

    apply_etag(response, agent.version)
    return AgentDetailOut.model_validate(agent)


@router.post("/agents/{agent_id}/publish", status_code=201, response_model=AgentVersionOut)
async def publish_agent_version(
    agent_id: uuid.UUID,
    ctx: SettingsCtx,
    body: AgentPublishRequest | None = None,
) -> AgentVersionOut:
    """Snapshot the agent row into an immutable published version.

    Idempotent for identical configuration: republishing unchanged settings
    returns the existing snapshot rather than minting a no-op version.
    """
    from app.modules.ai.versions import AIAgentVersionService

    policy = (body.tool_policy if body is not None else None) or None
    version = await AIAgentVersionService.publish(
        ctx.session,
        ctx.tenant_id,
        agent_id,
        published_by=ctx.user_id,
        tool_policy=policy,
    )
    return AgentVersionOut.model_validate(version)


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


@router.post("/memories/{memory_id}/verify", response_model=MemoryOut)
async def verify_memory(memory_id: uuid.UUID, ctx: SettingsCtx):
    """Verify and admit a memory (§158 / V12 Wave D).
    Transitions to active, sets verified_at = now(UTC), actor_id = ctx.user.id.
    """
    memory = await _load_memory(ctx, memory_id)
    now = datetime.now(UTC)
    memory.status = "active"
    memory.verified_at = now
    memory.actor_id = ctx.user.id
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
    ctx: ApproveCtx,
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
                # Explicitly no message. This event re-runs the CONVERSATION, and
                # the approval's own id is the aggregate — naming it a message
                # would have the worker transcribe a message that does not exist
                # and answer whichever inbound happens to share the row's shape.
                # The hook therefore re-evaluates against the newest inbound.
                "message_id": None,
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
async def trace_summary(ctx: TenantCtxDep, days: Annotated[int, Query(ge=1, le=365)] = 7):
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


# ---------- §37/§150 Handover queue & workflow ----------


def _handover_out(h: AIHandover) -> dict:
    """One shape for every handover response — three routes used to build the
    field list by hand, which is how a new column gets forgotten."""
    return HandoverOut(
        id=h.id,
        conversation_id=h.conversation_id,
        run_id=h.run_id,
        reason=h.reason,
        status=h.status,
        claimed_by_user_id=h.claimed_by_user_id,
        note=h.note,
        created_at=h.created_at.isoformat() if h.created_at else None,
        resolved_by_user_id=h.resolved_by_user_id,
        resolved_at=h.resolved_at.isoformat() if h.resolved_at else None,
        outcome=h.outcome,
        outcome_note=h.outcome_note,
    )


@router.get("/handovers", response_model=HandoverList)
async def list_handovers(
    ctx: TenantCtxDep,
    status: Annotated[
        str | None, Query(description="Filter by pending | claimed | resolved")
    ] = None,
):
    query = select(AIHandover).where(AIHandover.tenant_id == ctx.tenant_id)
    if status:
        query = query.where(AIHandover.status == status)
    query = query.order_by(AIHandover.created_at.desc())
    rows = (await ctx.session.execute(query)).scalars().all()
    return {"items": [_handover_out(h) for h in rows], "total": len(rows)}


@router.post("/handovers/{handover_id}/claim", response_model=HandoverOut)
async def claim_handover(
    handover_id: uuid.UUID,
    ctx: TenantCtxDep,
):
    from sqlalchemy import text

    existing = (
        await ctx.session.execute(
            select(AIHandover).where(
                AIHandover.id == handover_id,
                AIHandover.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        raise NotFoundError("handover not found")
    if existing.status != "pending":
        raise ConflictError(f"handover is already {existing.status}")

    # Atomic claim: only pending -> claimed (§29)
    stmt = (
        update(AIHandover)
        .where(
            AIHandover.id == handover_id,
            AIHandover.tenant_id == ctx.tenant_id,
            AIHandover.status == "pending",
        )
        .values(
            status="claimed",
            claimed_by_user_id=ctx.user_id,
        )
        .returning(AIHandover)
    )
    handover = (await ctx.session.execute(stmt)).scalar_one_or_none()
    if not handover:
        raise ConflictError("handover was already claimed by another user")

    await ctx.session.execute(
        text(
            "UPDATE conversations SET assignee_user_id = :uid WHERE id = :cid AND tenant_id = :tid"
        ),
        {
            "uid": str(ctx.user_id),
            "cid": str(handover.conversation_id),
            "tid": str(ctx.tenant_id),
        },
    )
    await ctx.session.flush()
    return _handover_out(handover)


@router.post("/handovers/{handover_id}/resolve", response_model=HandoverOut)
async def resolve_handover(
    handover_id: uuid.UUID,
    ctx: TenantCtxDep,
    body: HandoverResolveRequest | None = None,
):
    """Close a handover, recording WHO closed it, WHEN, and WITH WHAT RESULT.

    §150's outcome half: this route used to flip `status` and leave no trace
    behind, so the queue could count handovers created but never handovers
    answered. `outcome` is a closed vocabulary (a free-text-only field is a
    field nobody aggregates); `note` carries the detail a human would want
    later. Resolving a resolved row is a conflict, not a silent re-write: the
    second resolver would overwrite the first one's record of what happened.
    """
    from app.core.events.writer import add_outbox_event

    handover = (
        await ctx.session.execute(
            select(AIHandover)
            .where(
                AIHandover.id == handover_id,
                AIHandover.tenant_id == ctx.tenant_id,
            )
            # Two reviewers opening one handover both see PENDING; the row
            # lock makes the second one read the resolved state instead of
            # overwriting the first one's outcome.
            .with_for_update()
        )
    ).scalar_one_or_none()
    if handover is None:
        raise NotFoundError("handover not found")
    if handover.status == "resolved":
        raise ConflictError("handover is already resolved")

    outcome = body.outcome if body is not None else None
    if outcome is not None and outcome not in HANDOVER_OUTCOMES:
        raise ValidationError(f"outcome must be one of: {', '.join(HANDOVER_OUTCOMES)}")

    handover.status = "resolved"
    handover.resolved_by_user_id = ctx.user_id
    handover.resolved_at = datetime.now(UTC)
    handover.outcome = outcome
    handover.outcome_note = body.note if body is not None else None

    # Synchronize conversation: conversation leaves waiting_human (§30)
    from sqlalchemy import text

    await ctx.session.execute(
        text(
            "UPDATE conversations SET status = 'open' "
            "WHERE id = :cid AND tenant_id = :tid AND status = 'waiting_human'"
        ),
        {
            "cid": str(handover.conversation_id),
            "tid": str(ctx.tenant_id),
        },
    )
    # The other half of `request_human_takeover`'s three writes: the row and
    # the status moved, so the outbox says so too — that is how SLA clocks and
    # the dashboard learn a handover ENDED rather than only that it began.
    await add_outbox_event(
        ctx.session,
        aggregate_type="ai",
        aggregate_id=handover.conversation_id,
        event_type="ai.handover.resolved",
        tenant_id=ctx.tenant_id,
        payload={
            "event_type": "ai.handover.resolved",
            "handover_id": str(handover.id),
            "conversation_id": str(handover.conversation_id),
            "reason": handover.reason,
            "outcome": outcome,
            "resolved_by_user_id": str(ctx.user_id),
        },
    )
    await ctx.session.flush()
    return _handover_out(handover)


# ————————————————————— Sales chat (spec §SI-chat) ———————————————————————
# Merchant-facing analysis chat. `analytics:read` gates every route because a
# turn IS an analysis run; the thread is creator-scoped unless the caller is
# the tenant owner (service-enforced on every read).


@router.post("/sales-chat/threads", status_code=201, response_model=SalesChatThreadOut)
async def create_sales_chat_thread(
    body: SalesChatThreadCreateRequest, ctx: AnalyticsCtx
) -> SalesChatThreadOut:
    return await chat_service.create_thread(
        ctx.session,
        ctx,
        title=body.title,
        context=body.context.model_dump() if body.context else None,
    )


@router.get("/sales-chat/threads", response_model=list[SalesChatThreadOut])
async def list_sales_chat_threads(
    ctx: AnalyticsCtx,
    include_archived: bool = False,
    search: str | None = None,
    limit: Annotated[int, Query(ge=1)] = 50,
    before: datetime | None = None,
) -> list[SalesChatThreadOut]:
    return await chat_service.list_threads(
        ctx.session,
        ctx,
        include_archived=include_archived,
        search=search,
        limit=limit,
        before=before,
    )


@router.get("/sales-chat/threads/{thread_id}", response_model=SalesChatThreadOut)
async def get_sales_chat_thread(thread_id: uuid.UUID, ctx: AnalyticsCtx) -> SalesChatThreadOut:
    return await chat_service.get_thread(ctx.session, ctx, thread_id)


@router.patch("/sales-chat/threads/{thread_id}", response_model=SalesChatThreadOut)
async def update_sales_chat_thread(
    thread_id: uuid.UUID, body: SalesChatThreadUpdateRequest, ctx: AnalyticsCtx
) -> SalesChatThreadOut:
    thread = await chat_service.get_thread(ctx.session, ctx, thread_id)
    return await chat_service.update_thread(
        ctx.session, ctx, thread, title=body.title, status=body.status
    )


@router.delete("/sales-chat/threads/{thread_id}", status_code=204)
async def delete_sales_chat_thread(thread_id: uuid.UUID, ctx: AnalyticsCtx) -> None:
    thread = await chat_service.get_thread(ctx.session, ctx, thread_id)
    await chat_service.delete_thread(ctx.session, ctx, thread)


@router.get(
    "/sales-chat/threads/{thread_id}/messages", response_model=list[SalesChatMessageOut]
)
async def list_sales_chat_messages(
    thread_id: uuid.UUID,
    ctx: AnalyticsCtx,
    limit: Annotated[int, Query(ge=1)] = 50,
    before_seq: int | None = None,
) -> list[SalesChatMessageOut]:
    thread = await chat_service.get_thread(ctx.session, ctx, thread_id)
    return await chat_service.list_messages(
        ctx.session, ctx, thread, limit=limit, before_seq=before_seq
    )


@router.post(
    "/sales-chat/threads/{thread_id}/messages",
    status_code=201,
    response_model=SalesChatMessageOut,
)
async def send_sales_chat_message(
    thread_id: uuid.UUID, body: SalesChatMessageSendRequest, ctx: AnalyticsCtx
) -> SalesChatMessageOut:
    thread = await chat_service.get_thread(ctx.session, ctx, thread_id)
    user_row, created = await chat_service.append_user_message(
        ctx.session, ctx, thread, content=body.content, idempotency_key=body.idempotency_key
    )
    await ctx.session.commit()
    if not created:
        # Replayed key: the answer already exists — return it verbatim. A
        # second run here would double-bill the gateway for the same question.
        reply = await chat_service.get_assistant_reply_for(
            ctx.session, ctx, thread, user_seq=user_row.sequence_no
        )
        if reply is not None:
            return reply
    return await run_chat_turn(ctx.session, ctx, thread)


@router.post(
    "/sales-chat/threads/{thread_id}/messages/{message_id}/retry",
    response_model=SalesChatMessageOut,
)
async def retry_sales_chat_message(
    thread_id: uuid.UUID, message_id: uuid.UUID, ctx: AnalyticsCtx
) -> SalesChatMessageOut:
    thread = await chat_service.get_thread(ctx.session, ctx, thread_id)
    return await retry_chat_turn(ctx.session, ctx, thread, message_id=message_id)
