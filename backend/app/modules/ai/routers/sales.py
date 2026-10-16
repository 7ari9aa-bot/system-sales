"""AI sales routes — sales analyses, deep analyses, and merchant sales chat."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

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
from app.modules.ai.routers._deps import AnalyticsCtx

router = APIRouter(prefix="/ai", tags=["ai"])


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


@router.get("/sales-chat/threads/{thread_id}/messages", response_model=list[SalesChatMessageOut])
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
