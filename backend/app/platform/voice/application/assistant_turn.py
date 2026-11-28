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

A spoken turn can also be ABANDONED. The caller talks over the answer and asks
something else; the work for the old question keeps running, and when it
finishes its answer must not be spoken. So every spoken turn carries the id
``spoken_turns`` gave it (minted at the delegation boundary, or here when the
caller brought none), and before this function records anything it asks the
ledger whether that turn is still the one the call is answering. If it is not,
the answer is written ``cancelled`` through the same ``complete_turn`` — the
record keeps the work and loses the status — and the result comes back empty and
flagged ``superseded``, which is what stops it being spoken.
"""

from __future__ import annotations

import logging
import uuid

from app.core.db import bind_tenant
from app.core.errors import ValidationError
from app.applications.apparel.modules.ai.assistant.contracts import LIVE_VOICE, AssistantTurnInput, AssistantTurnResult
from app.applications.apparel.modules.ai.assistant.service import AssistantTurnService
from app.applications.apparel.modules.ai.chat import service as chat_service
from app.platform.voice.application import spoken_turns, transcript_sync
from app.platform.voice.application.session_thread import ensure_session_thread
from app.platform.voice.application.spoken_turns import SpokenTurn, TurnLedger

logger = logging.getLogger(__name__)


def _session_manager(session):
    """The manager that owns the voice session row, built on this turn's transaction.

    Behind a function so the infrastructure import stays out of the module scope and a test can
    drive the wiring without a database.
    """
    from app.platform.voice.application.session_manager import VoiceSessionManager
    from app.platform.voice.infrastructure.sql_store import SqlSessionStore

    return VoiceSessionManager(SqlSessionStore(session))


async def run_voice_turn(
    session,
    ctx,
    *,
    session_id,
    text: str,
    idempotency_key: str | None = None,
    turn: SpokenTurn | None = None,
    ledger: TurnLedger | None = None,
) -> AssistantTurnResult:
    """Answer one spoken turn on the thread its voice session belongs to.

    ``text`` is the transcript the caller's words produced; an empty one is
    refused rather than sent to the model, because a turn with no question would
    still cost a paid call and produce an answer nobody asked for.

    ``turn`` is the id this question already has when the caller minted one (the
    delegation path always does). Without it the turn gets a fresh id from
    ``ledger`` here — before any paid work — so even a direct caller is
    supersedable. Both halves must consult the SAME ledger; when they do not,
    the turn is not current and the answer is dropped rather than spoken, which
    is the failure direction this guarantee wants.
    """
    clean = (text or "").strip()
    if not clean:
        raise ValidationError("a spoken turn needs an intelligible transcript")
    voice_session_id = uuid.UUID(str(session_id))
    ledger = ledger if ledger is not None else spoken_turns.DEFAULT_LEDGER
    turn = turn if turn is not None else ledger.begin(voice_session_id)

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
            # the question again would put it in the timeline twice.
            #
            # The turn is a different matter. The answer is written by the shared
            # runtime and the link by ``complete_turn``, which are two commits: a
            # crash in between leaves an answer with no ``voice_turns`` row, and
            # the retry lands exactly here. Returning the message alone would
            # leave that turn unlinked and unbilled for ever, so the link is
            # healed on the replay. ``complete_turn`` is idempotent on
            # ``(session, question)`` and books spend only when it creates the
            # row, so a healthy replay adds nothing and costs nothing.
            #
            # DELIVERED, deliberately, even when the turn is no longer current:
            # the answer's own status is the runtime's to write, and rewriting it
            # from here could un-deliver an answer the caller already heard. The
            # return value below is what stops a stale one being spoken.
            completed = await transcript_sync.complete_turn(
                session,
                tenant_id=ctx.tenant_id,
                voice_session_id=voice_session_id,
                thread_id=thread.id,
                user_message_id=question.user_message_id,
                assistant_message_id=reply.id,
                outcome=transcript_sync.DELIVERED,
            )
            if completed.created:
                await _session_manager(session).note_turn_completed(
                    voice_session_id, completed.sequence_number
                )
            await session.commit()
            if not ledger.is_current(turn):
                # The caller asked something else while this one was replayed. The
                # answer exists, but it is the answer to an abandoned question.
                return _superseded(
                    thread_id=thread.id,
                    agent_id=getattr(thread, "agent_id", None),
                    assistant_message_id=reply.id,
                    message=reply,
                )
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
    # THE supersession check. The model has answered, so this is the last moment
    # at which the answer is still free to be dropped: a newer question began (or
    # the caller interrupted) while the tools ran, and what came back answers a
    # question nobody is waiting for any more.
    superseded = not ledger.is_current(turn)
    if superseded:
        logger.info(
            "voice.turn_superseded voice_session=%s turn=%s thread=%s",
            voice_session_id,
            turn.turn_id,
            thread.id,
        )
    completed = await transcript_sync.complete_turn(
        session,
        tenant_id=ctx.tenant_id,
        voice_session_id=voice_session_id,
        thread_id=thread.id,
        user_message_id=question.user_message_id,
        assistant_message_id=result.assistant_message_id,
        outcome=transcript_sync.outcome_for(superseded),
    )
    if completed.created:
        # The turn number is consumed either way: a resume must not replay a turn
        # the caller already abandoned.
        await _session_manager(session).note_turn_completed(
            voice_session_id, completed.sequence_number
        )
    await session.commit()
    if superseded:
        return _superseded(
            thread_id=result.thread_id,
            agent_id=result.agent_id,
            assistant_message_id=result.assistant_message_id,
            message=result.message,
        )
    return result


def _superseded(
    *,
    thread_id,
    agent_id,
    assistant_message_id,
    message,
) -> AssistantTurnResult:
    """The answer as the caller must receive it when a newer question took over.

    Empty on purpose: every delivery path speaks ``content``, so an empty one is
    the only answer that cannot be heard. The words are still in the row, and
    ``superseded`` says why nothing was spoken.
    """
    return AssistantTurnResult(
        thread_id=thread_id,
        agent_id=agent_id,
        assistant_message_id=assistant_message_id,
        content="",
        status=transcript_sync.CANCELLED,
        modality=LIVE_VOICE,
        message=message,
        superseded=True,
    )
