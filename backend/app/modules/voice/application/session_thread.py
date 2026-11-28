"""A voice session opens a conversation, so the words have somewhere to land.

``voice_sessions.ai_chat_thread_id`` existed with nothing writing it: every call opened a session
that belonged to no conversation, which is why transcript sync had to refuse every turn. This is
the missing half — one thread per session, created through the chat module's own ``create_thread``
so the agent is resolved server-side by kind and a client still cannot name an agent.

Deliberate: the thread is created when the session starts, not when the first word is heard. A
session that connects and stays silent must still be resumable, and a thread with no messages yet
is a normal, empty conversation rather than a leak.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.errors import NotFoundError
from app.applications.apparel.modules.ai.chat import service as chat_service
from app.modules.voice.domain.models import VoiceSessionRow

DEFAULT_TITLE = "محادثة صوتية"


async def ensure_session_thread(
    session,
    ctx,
    *,
    session_id: uuid.UUID,
    title: str | None = None,
    thread_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Return the conversation this voice session belongs to, opening it if needed.

    Idempotent: a second call for the same session returns the same thread instead of opening a
    second one. A session id from another shop answers 404, exactly like an id that never existed.

    ``thread_id`` is the conversation the merchant is already in. A spoken turn must land in the
    conversation that was typed into, not in a second one opened by pressing the call button, so
    when the client names its thread we continue that one instead of creating another. The id is
    resolved through the chat module's own ``get_thread``, which answers 404 for a thread that
    belongs to someone else, so a caller cannot point a session at another shop's conversation.
    """
    row = (
        await session.execute(
            select(VoiceSessionRow).where(
                VoiceSessionRow.id == session_id,
                VoiceSessionRow.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("voice session not found")
    if row.ai_chat_thread_id is not None:
        return row.ai_chat_thread_id

    if thread_id is not None:
        existing = await chat_service.get_thread(session, ctx, thread_id)
        row.ai_chat_thread_id = existing.id
        await session.flush()
        return existing.id

    thread = await chat_service.create_thread(session, ctx, title=title or DEFAULT_TITLE)
    row.ai_chat_thread_id = thread.id
    await session.flush()
    return thread.id
