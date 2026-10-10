"""Thread/message state for the merchant SI chat — spec §SI-chat.

Every read is creator-scoped unless the caller holds the tenant owner role;
cross-tenant rows never come back because tenant_id rides in every WHERE, and
RLS backs that up at the database. Deleted threads are soft-deleted (audit
keeps them) and disappear from every path immediately.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.sql import like_pattern
from app.modules.ai.core.resolver import resolve_agent_by_kind
from app.modules.ai.models import AIChatMessage, AIChatThread

TITLE_MAX = 200
MESSAGE_MAX = 4000
PAGE_LIMIT_MAX = 100
IDEMPOTENCY_KEY_MAX = 64


def _is_tenant_owner(ctx) -> bool:
    return getattr(ctx, "role_code", None) == "owner"


async def create_thread(session, ctx, *, title: str | None = None, context: dict | None = None):
    """Open a chat thread against the tenant's active SI agent.

    The agent is resolved server-side by kind — a client-specified agent_id is
    never trusted (it would let one tenant probe another's agents).
    """
    agent = await resolve_agent_by_kind(session, ctx.tenant_id, "sales_intelligence")
    clean_title = (title or "").strip()
    if len(clean_title) > TITLE_MAX:
        raise ValidationError(f"title must be at most {TITLE_MAX} characters")
    thread = AIChatThread(
        tenant_id=ctx.tenant_id,
        agent_id=agent.id,
        created_by_user_id=ctx.user.id,
        title=clean_title[:TITLE_MAX],
        context=context or {},
    )
    session.add(thread)
    await session.flush()
    return thread


async def get_thread(session, ctx, thread_id: uuid.UUID):
    """One thread, visible to its creator (or a tenant owner) only.

    Foreign/cross-tenant/deleted all answer NotFoundError — 404 semantics, so
    the route leaks nothing about threads the caller cannot see.
    """
    thread = (
        await session.execute(
            select(AIChatThread).where(
                AIChatThread.tenant_id == ctx.tenant_id,
                AIChatThread.id == thread_id,
                AIChatThread.status != "deleted",
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        raise NotFoundError("thread not found")
    if thread.created_by_user_id != ctx.user.id and not _is_tenant_owner(ctx):
        raise NotFoundError("thread not found")
    return thread


async def list_threads(
    session,
    ctx,
    *,
    include_archived: bool = False,
    search: str | None = None,
    limit: int = 50,
    before=None,
):
    cap = max(1, min(limit, PAGE_LIMIT_MAX))
    stmt = select(AIChatThread).where(
        AIChatThread.tenant_id == ctx.tenant_id,
        AIChatThread.status != "deleted",
    )
    if include_archived:
        stmt = stmt.where(AIChatThread.status.in_(("active", "archived")))
    else:
        stmt = stmt.where(AIChatThread.status == "active")
    if not _is_tenant_owner(ctx):
        stmt = stmt.where(AIChatThread.created_by_user_id == ctx.user.id)
    if search:
        stmt = stmt.where(
            AIChatThread.title.ilike(like_pattern(search.strip()), escape="\\")
        )
    if before is not None:
        stmt = stmt.where(AIChatThread.updated_at < before)
    stmt = stmt.order_by(AIChatThread.updated_at.desc()).limit(cap)
    return list((await session.execute(stmt)).scalars().all())


async def update_thread(
    session, ctx, thread, *, title: str | None = None, status: str | None = None
):
    if title is not None:
        clean = title.strip()
        if not clean:
            raise ValidationError("title must not be empty")
        if len(clean) > TITLE_MAX:
            raise ValidationError(f"title must be at most {TITLE_MAX} characters")
        thread.title = clean
    if status is not None:
        # legal transitions: active -> archived (archive), archived -> active
        # (restore). Re-stating the current status is a conflict, not a no-op —
        # the client and the server disagree about the thread's state.
        if status == thread.status:
            raise ConflictError(f"thread is already {status}")
        if thread.status not in ("active", "archived") or status not in ("active", "archived"):
            raise ConflictError(f"cannot move a {thread.status} thread to {status}")
        thread.status = status
    await session.flush()
    return thread


async def delete_thread(session, ctx, thread) -> None:
    """Soft delete — the rows stay for audit, every read path stops seeing them."""
    thread.status = "deleted"
    await session.flush()


async def append_user_message(
    session,
    ctx,
    thread,
    *,
    content: str,
    idempotency_key: str | None,
):
    """Persist the merchant's turn. Returns (row, created).

    A repeated `idempotency_key` on the same thread returns the SAME row with
    created=False — a retried submit never double-runs the analysis (and never
    double-bills the gateway).
    """
    clean = (content or "").strip()
    if not clean:
        raise ValidationError("message must not be empty")
    if len(clean) > MESSAGE_MAX:
        raise ValidationError(f"message must be at most {MESSAGE_MAX} characters")
    key = (idempotency_key or "").strip() or None
    if key and len(key) > IDEMPOTENCY_KEY_MAX:
        raise ValidationError(f"idempotency_key must be at most {IDEMPOTENCY_KEY_MAX} characters")

    if key is not None:
        existing = (
            await session.execute(
                select(AIChatMessage).where(
                    AIChatMessage.tenant_id == ctx.tenant_id,
                    AIChatMessage.thread_id == thread.id,
                    AIChatMessage.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

    next_seq = (
        await session.execute(
            select(func.coalesce(func.max(AIChatMessage.sequence_no), 0)).where(
                AIChatMessage.tenant_id == ctx.tenant_id,
                AIChatMessage.thread_id == thread.id,
            )
        )
    ).scalar_one() + 1
    row = AIChatMessage(
        tenant_id=ctx.tenant_id,
        thread_id=thread.id,
        sequence_no=next_seq,
        role="user",
        status="completed",
        content=clean,
        idempotency_key=key,
    )
    session.add(row)
    thread.last_message_at = func.now()
    await session.flush()
    return row, True


async def list_messages(
    session,
    ctx,
    thread,
    *,
    limit: int = 50,
    before_seq: int | None = None,
):
    cap = max(1, min(limit, PAGE_LIMIT_MAX))
    stmt = select(AIChatMessage).where(
        AIChatMessage.tenant_id == ctx.tenant_id,
        AIChatMessage.thread_id == thread.id,
    )
    if before_seq is not None:
        stmt = stmt.where(AIChatMessage.sequence_no < before_seq)
    stmt = stmt.order_by(AIChatMessage.sequence_no.desc()).limit(cap)
    return list((await session.execute(stmt)).scalars().all())


async def get_assistant_reply_for(session, ctx, thread, *, user_seq: int):
    """The assistant row that answers the user turn at `user_seq` (seq+1)."""
    return (
        await session.execute(
            select(AIChatMessage).where(
                AIChatMessage.tenant_id == ctx.tenant_id,
                AIChatMessage.thread_id == thread.id,
                AIChatMessage.sequence_no == user_seq + 1,
                AIChatMessage.role == "assistant",
            )
        )
    ).scalar_one_or_none()
