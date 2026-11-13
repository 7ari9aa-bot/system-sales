"""The owner's memory screen: see, add, edit and delete notes, and switch memory off.

Every route acts on the CALLER's own notes. The service is built from the session's user, so there
is no path, query or body field that reaches another user's memory, and a colleague's note is
answered with a 404 exactly like one that never existed.

The gate is ``analytics:read``, the permission of the assistant itself. A person who may talk to
the assistant may keep notes for it; what they keep is about them, not about the shop's data.

A refused note answers with the REASON and never repeats the text. The text may be the password
that was refused, and an error body ends up in logs and screens.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ConflictError, DomainError, NotFoundError
from app.modules.ai.owner_memory import (
    MAX_ACTIVE_MEMORIES,
    MAX_MEMORY_CHARS,
    MemoryRefused,
    OwnerMemoryService,
)
from app.modules.ai.routers._deps import AnalyticsCtx

# The prefix lives on THIS router: the aggregator copies routes as they are, it does not add "/ai".
router = APIRouter(prefix="/ai", tags=["ai"])

_MESSAGES = {
    "sensitive": "الملاحظة دي شكلها سر (باسورد أو كارت أو رقم قومي أو مفتاح) ومبتتحفظش.",
    "instruction": "الملاحظة دي شكلها تعليمات للمساعد مش معلومة عنك، ومبتتحفظش.",
    "too_long": f"الملاحظة أطول من {MAX_MEMORY_CHARS} حرف.",
    "empty": "الملاحظة فاضية.",
    "bad_source": "مصدر الملاحظة مش مسموح.",
    "full": f"الذاكرة ممتلئة ({MAX_ACTIVE_MEMORIES} ملاحظة). امسح ملاحظات قديمة الأول.",
    "disabled": "الذاكرة مقفولة. شغّلها الأول.",
    "duplicate": "عندك ملاحظة بنفس المعنى بالفعل.",
}
# Refusals about WHAT the owner wrote are 422; refusals about the state of their memory are 409.
_CONFLICT = {"full", "disabled", "duplicate"}


class _MemoryRefusedError(DomainError):
    """The note was not accepted. ``details.reason`` says why; the text itself is never echoed."""

    code = "memory_refused"
    http_status = 422
    expose_details = True


class _MemoryStateError(ConflictError):
    code = "memory_unavailable"
    expose_details = True


def _refusal(refused: MemoryRefused) -> DomainError:
    reason = refused.reason
    message = _MESSAGES.get(reason, "مقدرتش أحفظ الملاحظة دي.")
    cls = _MemoryStateError if reason in _CONFLICT else _MemoryRefusedError
    return cls(message, details={"reason": reason})


class OwnerNoteOut(BaseModel):
    id: uuid.UUID
    content: str
    source: str
    created_at: datetime
    updated_at: datetime


class OwnerMemoryOut(BaseModel):
    enabled: bool
    notes: list[OwnerNoteOut]
    max_notes: int
    max_chars: int


class OwnerNoteIn(BaseModel):
    # extra fields are IGNORED, never read: a body cannot name another user
    model_config = ConfigDict(extra="ignore")
    content: str = Field(max_length=MAX_MEMORY_CHARS * 4)


class OwnerMemoryEnabledIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class OwnerMemoryEnabledOut(BaseModel):
    enabled: bool


class OwnerMemoryRemovedOut(BaseModel):
    removed: int


def _service(ctx: AnalyticsCtx) -> OwnerMemoryService:
    return OwnerMemoryService(ctx.session, ctx.tenant_id, ctx.user.id)


def _note(row) -> OwnerNoteOut:
    return OwnerNoteOut(
        id=row.id,
        content=row.content,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/owner-memory", response_model=OwnerMemoryOut)
async def get_owner_memory(ctx: AnalyticsCtx) -> OwnerMemoryOut:
    svc = _service(ctx)
    return OwnerMemoryOut(
        enabled=await svc.is_enabled(),
        # newest first on the screen; the service lists oldest first (chat numbers them 1, 2, 3)
        notes=[_note(r) for r in reversed(await svc.list_active())],
        max_notes=MAX_ACTIVE_MEMORIES,
        max_chars=MAX_MEMORY_CHARS,
    )


@router.post("/owner-memory", status_code=201, response_model=OwnerNoteOut)
async def add_owner_memory(body: OwnerNoteIn, ctx: AnalyticsCtx) -> OwnerNoteOut:
    try:
        row = await _service(ctx).remember(body.content, source="explicit")
    except MemoryRefused as refused:
        raise _refusal(refused) from None
    return _note(row)


# Registered before the "/{note_id}" routes so the word "enabled" is never read as an id.
@router.put("/owner-memory/enabled", response_model=OwnerMemoryEnabledOut)
async def set_owner_memory_enabled(
    body: OwnerMemoryEnabledIn, ctx: AnalyticsCtx
) -> OwnerMemoryEnabledOut:
    await _service(ctx).set_enabled(body.enabled)
    return OwnerMemoryEnabledOut(enabled=body.enabled)


@router.patch("/owner-memory/{note_id}", response_model=OwnerNoteOut)
async def edit_owner_memory(
    note_id: uuid.UUID, body: OwnerNoteIn, ctx: AnalyticsCtx
) -> OwnerNoteOut:
    try:
        row = await _service(ctx).edit(note_id, body.content)
    except MemoryRefused as refused:
        raise _refusal(refused) from None
    if row is None:
        raise NotFoundError("الملاحظة مش موجودة")
    return _note(row)


@router.delete("/owner-memory/{note_id}", status_code=204)
async def delete_owner_memory(note_id: uuid.UUID, ctx: AnalyticsCtx) -> None:
    if not await _service(ctx).forget(note_id):
        raise NotFoundError("الملاحظة مش موجودة")


@router.delete("/owner-memory", response_model=OwnerMemoryRemovedOut)
async def clear_owner_memory(ctx: AnalyticsCtx) -> OwnerMemoryRemovedOut:
    return OwnerMemoryRemovedOut(removed=await _service(ctx).forget_all())
