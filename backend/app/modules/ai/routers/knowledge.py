"""AI knowledge-base routes — ingestion, listing, and semantic search."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.pagination import paginate
from app.modules.ai import knowledge
from app.modules.ai.models import KnowledgeItem
from app.modules.ai.routers._deps import SettingsCtx, TenantCtxDep
from app.modules.ai.schemas import (
    KnowledgeIngested,
    KnowledgeIngestRequest,
    KnowledgeList,
    KnowledgeSearchHit,
)

router = APIRouter(prefix="/ai", tags=["ai"])


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
