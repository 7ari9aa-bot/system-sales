"""A spoken turn, answered by the assistant the shop already has.

This is the whole of the voice module's claim on the brain: it resolves the
conversation the voice session belongs to, writes what the caller said into it,
and hands the turn to ``AssistantTurnService`` with ``modality=live_voice``.
Nothing here decides which agent answers, which tools exist or what a number
means — voice contributes the carrier, the assistant contributes the thinking.

Same as the text route, the question is committed BEFORE the model is called, so
a dropped call leaves a durable question and a retryable answer instead of a
silent hole.
"""

from __future__ import annotations

import logging

from app.core.db import bind_tenant
from app.core.errors import ValidationError
from app.modules.ai.assistant.contracts import LIVE_VOICE, AssistantTurnInput, AssistantTurnResult
from app.modules.ai.assistant.service import AssistantTurnService
from app.modules.ai.chat import service as chat_service
from app.modules.voice.application.session_thread import ensure_session_thread

logger = logging.getLogger(__name__)


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
    if not (text or "").strip():
        raise ValidationError("a spoken turn needs an intelligible transcript")

    thread = await ensure_session_thread(session, ctx, session_id=session_id)
    user_row, created = await chat_service.append_user_message(
        session, ctx, thread, content=text.strip(), idempotency_key=idempotency_key
    )
    await session.commit()
    # COMMIT ends the transaction-local RLS binding; everything below reads
    # FORCE-RLS tables, so re-bind before the replay lookup or the turn.
    await bind_tenant(session, ctx.tenant_id)
    if not created:
        reply = await chat_service.get_assistant_reply_for(
            session, ctx, thread, user_seq=user_row.sequence_no
        )
        if reply is not None:
            # Replayed key: the answer already exists. Running it again would
            # double-bill the gateway for the same spoken question.
            return AssistantTurnResult(
                thread_id=thread.id,
                agent_id=getattr(thread, "agent_id", None),
                assistant_message_id=reply.id,
                content=reply.content or "",
                status=reply.status,
                modality=LIVE_VOICE,
                message=reply,
            )

    return await AssistantTurnService().run(
        session,
        ctx,
        thread,
        AssistantTurnInput(
            tenant_id=ctx.tenant_id,
            thread_id=thread.id,
            modality=LIVE_VOICE,
            voice_session_id=session_id,
        ),
    )
