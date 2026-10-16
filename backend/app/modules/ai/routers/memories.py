"""AI memory management routes — §158 staff review surface."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.core.pagination import paginate
from app.modules.ai import knowledge
from app.modules.ai.models import Memory
from app.modules.ai.routers._deps import SettingsCtx, TenantContext
from app.modules.ai.schemas import MemoryList, MemoryOut

router = APIRouter(prefix="/ai", tags=["ai"])


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
