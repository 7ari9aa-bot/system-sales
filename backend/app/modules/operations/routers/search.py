"""Search endpoints for operations."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

from app.core.search import get_search
from app.modules.operations.schemas import SearchHit
from ._deps import TenantCtxDep, search_router


@search_router.get("", response_model=list[SearchHit])
async def global_search(
    ctx: TenantCtxDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """§45: unified search through the SearchPort (engine-agnostic)."""
    hits = await get_search().search(ctx.session, ctx.tenant_id, q, limit=limit)
    return [
        SearchHit(
            entity_type=h.entity_type,
            entity_id=h.entity_id,
            title=h.title,
            snippet=h.snippet,
        )
        for h in hits
    ]
