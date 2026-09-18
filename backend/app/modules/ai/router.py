"""AI routes — knowledge management, agent admin, usage reporting.

Write endpoints sit behind the ``settings:write`` permission (same gate the
platform settings use); reads only need an authenticated tenant context.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.pagination import paginate
from app.modules.ai import knowledge
from app.modules.ai.models import Agent, AIUsage, KnowledgeItem
from app.modules.ai.schemas import AgentCreateRequest, AgentOut, KnowledgeIngestRequest
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

router = APIRouter(prefix="/ai", tags=["ai"])

SettingsCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]


@router.post("/knowledge", status_code=201)
async def ingest_knowledge(ctx: SettingsCtx, body: KnowledgeIngestRequest) -> dict:
    item = await knowledge.ingest_knowledge(
        ctx.session,
        ctx.tenant_id,
        title=body.title,
        content=body.content,
        source_type=body.source_type,
        source_ref=body.source_ref,
    )
    return {"id": str(item.id), "status": item.status}


@router.get("/knowledge/search")
async def search_knowledge(
    ctx: TenantCtxDep,
    q: str = Query(min_length=1),
    limit: int = Query(default=5, ge=1, le=50),
) -> list[dict]:
    results = await knowledge.search_knowledge(ctx.session, ctx.tenant_id, q, limit=limit)
    return [
        {
            "id": str(item.id),
            "title": item.title,
            "source_type": item.source_type,
            "content": item.content,
            "distance": distance,
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


@router.get("/usage/summary")
async def usage_summary(ctx: TenantCtxDep, days: Annotated[int, Query(ge=1, le=365)] = 30) -> dict:
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
                "cost": float(cost),
            }
            for period, tokens_in, tokens_out, cost in rows
        ],
    }


@router.get("/knowledge")
async def list_knowledge(
    ctx: SettingsCtx,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    stmt = select(KnowledgeItem).where(KnowledgeItem.tenant_id == ctx.tenant_id)
    items, next_cursor = await paginate(ctx.session, stmt, cursor=cursor, limit=limit)
    return {
        "items": [
            {
                "id": str(item.id),
                "title": item.title,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
        "next_cursor": next_cursor,
    }
