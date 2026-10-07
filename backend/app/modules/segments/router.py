"""SEGMENTS routes — shared segment entity + DSL preview (§82).

A segment's definition is a validated AST/DSL (never free SQL from the UI).
``/preview`` compiles a definition and returns the matching customer count
WITHOUT persisting anything — the pre-flight check a marketer runs before
saving. An invalid definition is rejected by the whitelist compiler as a
``ValidationError`` (HTTP 400), never a 500.

Reads use plain ``TenantCtxDep``; writes require ``marketing:write`` (segments
are a CRM/marketing concept — no new permission codes are invented).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.segments.service import Segment, SegmentService, validate_dsl

router = APIRouter(prefix="/segments", tags=["segments"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("marketing:write"))]


class SegmentOut(BaseModel):
    """One segment and the evaluation state that makes it worth having.

    Declared field-for-field against ``_segment_dict`` (``test_segments_contract``
    holds the two in sync), because a response model that omits a key is a
    SILENT filter: the handler can keep building it and the client stops
    receiving it, with nothing failing anywhere. ``last_count`` /
    ``last_evaluated_at`` stay explicitly nullable — an un-evaluated segment must
    answer ``null`` rather than the ``0`` that would read as "ran, matched
    nobody".
    """

    id: uuid.UUID
    name: str
    definition: dict[str, Any]
    is_active: bool
    last_count: int | None
    last_evaluated_at: datetime | None
    created_at: datetime


class SegmentPreviewOut(BaseModel):
    """``/preview``'s answer: how many match, and a few ids to eyeball.

    Customer ids are STRINGS here as everywhere else in this API — a UUID has no
    lossless JSON number form.
    """

    count: int
    sample: list[str]


class SegmentArchiveOut(BaseModel):
    """Archive is a SOFT delete, so the body says which way the flag moved."""

    id: uuid.UUID
    is_active: bool
    archived: bool


class SegmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    definition: dict


class SegmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    definition: dict | None = None
    is_active: bool | None = None


class SegmentPreviewRequest(BaseModel):
    definition: dict
    sample_limit: int = Field(default=0, ge=0, le=50)


def _segment_dict(segment: Segment) -> dict:
    return {
        "id": str(segment.id),
        "name": segment.name,
        "definition": segment.definition,
        "is_active": segment.is_active,
        "last_count": segment.last_count,
        "last_evaluated_at": (
            segment.last_evaluated_at.isoformat() if segment.last_evaluated_at else None
        ),
        "created_at": segment.created_at.isoformat(),
    }


async def _get_segment(ctx: TenantContext, segment_id: uuid.UUID) -> Segment:
    segment = (
        await ctx.session.execute(
            select(Segment).where(
                Segment.tenant_id == ctx.tenant_id,
                Segment.id == segment_id,
            )
        )
    ).scalar_one_or_none()
    if segment is None:
        raise NotFoundError("segment not found")
    return segment


@router.get("", response_model=list[SegmentOut])
async def list_segments(ctx: TenantCtxDep, is_active: bool | None = None):
    """List this tenant's segments (optionally only active ones)."""
    stmt = select(Segment).where(Segment.tenant_id == ctx.tenant_id)
    if is_active is not None:
        stmt = stmt.where(Segment.is_active == is_active)
    rows = (
        (await ctx.session.execute(stmt.order_by(Segment.created_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return [_segment_dict(segment) for segment in rows]


@router.post("", response_model=SegmentOut, status_code=201)
async def create_segment(ctx: WriteCtx, body: SegmentCreate):
    """Create a segment from a name + DSL definition (definition is validated)."""
    segment = await SegmentService.create(
        ctx.session, ctx.tenant_id, name=body.name, definition=body.definition
    )
    return _segment_dict(segment)


@router.post("/preview", response_model=SegmentPreviewOut)
async def preview_segment(ctx: TenantCtxDep, body: SegmentPreviewRequest):
    """Compile a DSL definition and return the matching count WITHOUT persisting.

    The definition is validated first, so a bad DSL is a 400 (``ValidationError``)
    and never reaches the database.
    """
    validate_dsl(body.definition)
    probe = Segment(tenant_id=ctx.tenant_id, name="__preview__", definition=body.definition)
    matched = await SegmentService.evaluate(ctx.session, ctx.tenant_id, probe)
    return {
        "count": len(matched),
        "sample": [str(customer_id) for customer_id in matched[: body.sample_limit]],
    }


@router.get("/{segment_id}", response_model=SegmentOut)
async def get_segment(ctx: TenantCtxDep, segment_id: uuid.UUID):
    """Fetch one segment by id."""
    return _segment_dict(await _get_segment(ctx, segment_id))


@router.put("/{segment_id}", response_model=SegmentOut)
async def update_segment(ctx: WriteCtx, segment_id: uuid.UUID, body: SegmentUpdate):
    """Update a segment's name / definition / active flag (definition validated)."""
    segment = await _get_segment(ctx, segment_id)
    if body.name is not None:
        segment.name = body.name
    if body.definition is not None:
        validate_dsl(body.definition)
        segment.definition = body.definition
    if body.is_active is not None:
        segment.is_active = body.is_active
    await ctx.session.flush()
    return _segment_dict(segment)


@router.delete("/{segment_id}", response_model=SegmentArchiveOut)
async def archive_segment(ctx: WriteCtx, segment_id: uuid.UUID):
    """Archive a segment (soft delete: ``is_active`` flipped to false)."""
    segment = await _get_segment(ctx, segment_id)
    segment.is_active = False
    await ctx.session.flush()
    return {"id": str(segment.id), "is_active": segment.is_active, "archived": True}
