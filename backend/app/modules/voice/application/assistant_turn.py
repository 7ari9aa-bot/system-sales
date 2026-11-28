"""A spoken turn, answered by the assistant the shop already has.

This is the whole of the voice module's claim on the brain: it resolves the
conversation the voice session belongs to, writes what the caller said into it,
and hands the turn to ``AssistantTurnService`` with ``modality=live_voice``.
Nothing here decides which agent answers, which tools exist or what a number
means — voice contributes the carrier, the assistant contributes the thinking.

The conversation rows are written by ``transcript_sync`` and nowhere else: the
question goes through ``open_turn`` (which stamps ``voice_session_id`` and the
voice modality on the row it creates) and the finished turn through
``complete_turn`` (which marks the answer the shared runtime wrote and inserts
the one ``voice_turns`` row that joins the two messages). Nothing here writes a
second copy of the question, and a replayed idempotency key adds neither a second
message nor a second turn.

Same as the text route, the question is committed BEFORE the model is called, so
a dropped call leaves a durable question and a retryable answer instead of a
silent hole.
"""

from __future__ import annotations

import logging
import uuid

from app.core.db import bind_tenant
from app.core.errors import ValidationError
from app.modules.ai.assistant.contracts import LIVE_VOICE, AssistantTurnInput, AssistantTurnResult
from app.modules.ai.assistant.service import AssistantTurnService
from app.modules.ai.chat import service as chat_service
from app.modules.voice.application import transcript_sync
from app.modules.voice.application.session_thread import ensure_session_thread

logger = logging.getLogger(__name__)


def _session_manager(session):
    """The manager that owns the voice session row, built on this turn's transaction.

    Behind a function so the infrastructure import stays out of the module scope and a test can
    drive the wiring without a database.
    """
    from app.modules.voice.application.session_manager import VoiceSessionManager
    from app.modules.voice.infrastructure.sql_store import SqlSessionStore

    return VoiceSessionManager(SqlSessionStore(session))


async def run_voice_turn(
    session,
    ctx,
    *,
    session_id,
    text: str,
    idempotency_key: str | None = None,
) -> AssistantTurnResult:
    """Answer one spoken turn on the thread its voice session belongs to.

    ``text`` is the transcript the caller's words produced; an empty one is
    refused rather than sent to the model, because a turn with no question would
    still cost a paid call and produce an answer nobody asked for.
    """
    clean = (text or "").strip()
    if not clean:
        raise ValidationError("a spoken turn needs an intelligible transcript")
    voice_session_id = uuid.UUID(str(session_id))

    thread_id = await ensure_session_thread(session, ctx, session_id=voice_session_id)
    # ensure_session_thread answers with the id of the conversation; the turn needs the row it
    # names (the write stamps last_message_at, and the runtime reads the thread's agent).
    thread = await chat_service.get_thread(session, ctx, thread_id)

    question = await transcript_sync.open_turn(
        session,
        tenant_id=ctx.tenant_id,
        voice_session_id=voice_session_id,
        thread=thread,
        user_text=clean,
        idempotency_key=idempotency_key,
    )
    await session.commit()
    # COMMIT ends the transaction-local RLS binding; everything below reads
    # FORCE-RLS tables, so re-bind before the replay lookup or the turn.
    await bind_tenant(session, ctx.tenant_id)
    if not question.created:
        reply = await chat_service.get_assistant_reply_for(
            session, ctx, thread, user_seq=question.user_sequence_no
        )
        if reply is not None:
            # Replayed key: the answer already exists. Running it again would
            # double-bill the gateway for the same spoken question, and writing
            # the turn again would make the call look like it had two of them.
            return AssistantTurnResult(
                thread_id=thread.id,
                agent_id=getattr(thread, "agent_id", None),
                assistant_message_id=reply.id,
                content=reply.content or "",
                status=reply.status,
                modality=LIVE_VOICE,
                message=reply,
            )

    result = await AssistantTurnService().run(
        session,
        ctx,
        thread,
        AssistantTurnInput(
            tenant_id=ctx.tenant_id,
            thread_id=thread.id,
            modality=LIVE_VOICE,
            voice_session_id=voice_session_id,
        ),
    )

    # The runtime commits inside the turn, which ends the RLS binding again.
    await bind_tenant(session, ctx.tenant_id)
    completed = await transcript_sync.complete_turn(
        session,
        tenant_id=ctx.tenant_id,
        voice_session_id=voice_session_id,
        thread_id=thread.id,
        user_message_id=question.user_message_id,
        assistant_message_id=result.assistant_message_id,
    )
    if completed.created:
        await _session_manager(session).note_turn_completed(
            voice_session_id, completed.sequence_number
        )
    await session.commit()
    return result
