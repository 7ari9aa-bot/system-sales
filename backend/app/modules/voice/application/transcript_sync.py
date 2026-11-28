"""A spoken turn becomes a message in the conversation, not a parallel record.

The voice tables answer "what did this call do"; the conversation answers "what was said". Until
this module there was no bridge, so a spoken question could not be found by the next typed one and
a reconnect could not resume anything. Everything here writes INTO ``ai_chat_messages``: the turn
row keeps the two ids (``user_message_id``/``assistant_message_id``) and never a second copy of the
words.

This module is the SINGLE writer of a voice turn's message rows, and the live path
(``assistant_turn.run_voice_turn``) is its only production caller:

* ``open_turn`` writes the question — with ``voice_session_id``, ``input_modality`` and
  ``transcript_status`` on the row it creates — and answers whether it wrote it or found it.
* ``complete_turn`` marks the answer that the shared runtime wrote as spoken and inserts the ONE
  ``voice_turns`` row that joins the two messages.

``chat_service.append_user_message`` stays the text route's writer. A spoken question never goes
through it, so two writers can no longer disagree about whether a message carries
``voice_session_id`` — the gap that left every voice turn unlinked.

Three rules are enforced rather than documented:

* A session with no ``ai_chat_thread_id`` cannot record a turn. Guessing a thread would attach a
  stranger's words to somebody's conversation, so it is refused.
* A turn with no heard words is not a message. An empty transcript is a failed recognition, not a
  user who said nothing, and writing it would put a blank bubble in the timeline.
* A turn is recorded once. The idempotency key decides for the question, and the
  ``(session_id, user_message_id)`` pair decides for the turn row, so a replayed delegation adds
  neither a second message nor a second turn.

Ordering is the conversation's own (``sequence_no`` = max + 1), so a spoken turn and a typed turn
interleave correctly and a repeated write cannot jump the queue.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select, update

from app.modules.ai.models import AIChatMessage
from app.modules.voice.domain.models import VoiceTurnRow
from app.modules.voice.domain.states import TurnState

VOICE_MODALITY = "live_voice"
TranscriptStatus = Literal["partial", "final"]
_VALID_STATUS: frozenset[str] = frozenset({"partial", "final"})


class TranscriptError(ValueError):
    """A spoken turn that cannot honestly become a message in the conversation."""


@dataclass(frozen=True, slots=True)
class TranscriptPlan:
    """The two messages a turn will become, before anything is written."""

    thread_id: uuid.UUID
    user_text: str
    assistant_text: str | None
    transcript_status: str


@dataclass(frozen=True, slots=True)
class TurnMessages:
    """What the turn row keeps: the ids of the messages it became."""

    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class OpenedTurn:
    """The question a spoken turn wrote, and whether this call is the one that wrote it."""

    user_message_id: uuid.UUID
    user_sequence_no: int
    created: bool


@dataclass(frozen=True, slots=True)
class CompletedTurn:
    """The one turn row that joins a finished turn's two messages."""

    turn_id: uuid.UUID
    sequence_number: int
    created: bool


def plan_turn(
    *,
    thread_id: uuid.UUID | None,
    user_text: str | None,
    assistant_text: str | None = None,
    transcript_status: str = "final",
) -> TranscriptPlan:
    """Validate a turn and turn it into a plan, or refuse it."""
    if thread_id is None:
        raise TranscriptError(
            "this voice session belongs to no conversation, so its words have nowhere to go"
        )
    clean = (user_text or "").strip()
    if not clean:
        raise TranscriptError("a turn with no recognised words is not a message")
    if transcript_status not in _VALID_STATUS:
        raise TranscriptError(
            f"transcript_status must be one of {sorted(_VALID_STATUS)}, not {transcript_status!r}"
        )
    reply = (assistant_text or "").strip() or None
    return TranscriptPlan(
        thread_id=thread_id,
        user_text=clean,
        assistant_text=reply,
        transcript_status=transcript_status,
    )


def _message(
    *,
    tenant_id: uuid.UUID,
    plan: TranscriptPlan,
    voice_session_id: uuid.UUID | None,
    sequence_no: int,
    role: str,
    content: str,
    idempotency_key: str | None,
) -> AIChatMessage:
    spoken = VOICE_MODALITY
    return AIChatMessage(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        thread_id=plan.thread_id,
        sequence_no=sequence_no,
        role=role,
        status="completed",
        content=content,
        idempotency_key=idempotency_key,
        # The row says how it arrived and how it was answered. Text keeps NULL, which is what
        # every message written before this column existed already reads as.
        input_modality=spoken if role == "user" else None,
        output_modality=spoken if role != "user" else None,
        voice_session_id=voice_session_id,
        transcript_status=plan.transcript_status,
    )


async def _write_question(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    voice_session_id: uuid.UUID | None,
    plan: TranscriptPlan,
    idempotency_key: str | None,
) -> tuple[AIChatMessage, bool]:
    """Insert the question once. Returns ``(row, created)``.

    A worker that reconnects mid-turn replays the same key. Returning the existing message is the
    whole point: the user must not see their question twice, and the backend must not run the same
    analysis twice.
    """
    key = (idempotency_key or "").strip() or None

    if key is not None:
        existing = (
            await session.execute(
                select(AIChatMessage).where(
                    AIChatMessage.tenant_id == tenant_id,
                    AIChatMessage.thread_id == plan.thread_id,
                    AIChatMessage.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

    next_seq = (
        await session.execute(
            select(func.coalesce(func.max(AIChatMessage.sequence_no), 0)).where(
                AIChatMessage.tenant_id == tenant_id,
                AIChatMessage.thread_id == plan.thread_id,
            )
        )
    ).scalar_one() + 1

    row = _message(
        tenant_id=tenant_id,
        plan=plan,
        voice_session_id=voice_session_id,
        sequence_no=next_seq,
        role="user",
        content=plan.user_text,
        idempotency_key=key,
    )
    session.add(row)
    await session.flush()
    return row, True


async def open_turn(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    voice_session_id: uuid.UUID,
    thread: Any,
    user_text: str | None,
    idempotency_key: str | None = None,
    transcript_status: str = "final",
) -> OpenedTurn:
    """Write the question of a live spoken turn into the conversation, once.

    ``thread`` is the conversation ROW (its ``id`` is the conversation), not the id: a created
    question also stamps ``last_message_at`` so the thread list orders by the last thing said.

    The row carries the voice session and the modality from the moment it exists, so there is no
    window in which a spoken question looks typed. A replay returns the row that already answers
    the key and touches nothing.
    """
    plan = plan_turn(
        thread_id=getattr(thread, "id", None),
        user_text=user_text,
        transcript_status=transcript_status,
    )
    row, created = await _write_question(
        session,
        tenant_id=tenant_id,
        voice_session_id=voice_session_id,
        plan=plan,
        idempotency_key=idempotency_key,
    )
    if created:
        # Same as the text route: the thread list orders by when it was last spoken in.
        thread.last_message_at = func.now()
        await session.flush()
    return OpenedTurn(
        user_message_id=row.id,
        user_sequence_no=row.sequence_no,
        created=created,
    )


async def complete_turn(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    voice_session_id: uuid.UUID,
    thread_id: uuid.UUID,
    user_message_id: uuid.UUID,
    assistant_message_id: uuid.UUID | None,
    transcript_status: str = "final",
) -> CompletedTurn:
    """Join a finished turn to both its messages and insert its ``voice_turns`` row, once.

    The answer row is written by the shared runtime (``chat.turns.run_chat_turn``) for typed and
    spoken turns alike, so it is not written again here — it is marked as spoken, which is the one
    fact the runtime does not know. The turn row is the join: one row per ``(session, question)``,
    which is what makes a replayed delegation add nothing.
    """
    if transcript_status not in _VALID_STATUS:
        raise TranscriptError(
            f"transcript_status must be one of {sorted(_VALID_STATUS)}, not {transcript_status!r}"
        )

    if assistant_message_id is not None:
        await session.execute(
            update(AIChatMessage)
            .where(
                AIChatMessage.tenant_id == tenant_id,
                AIChatMessage.thread_id == thread_id,
                AIChatMessage.id == assistant_message_id,
                AIChatMessage.role == "assistant",
            )
            .values(
                output_modality=VOICE_MODALITY,
                voice_session_id=voice_session_id,
                transcript_status=transcript_status,
            )
        )

    existing = (
        await session.execute(
            select(VoiceTurnRow).where(
                VoiceTurnRow.session_id == voice_session_id,
                VoiceTurnRow.user_message_id == user_message_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return CompletedTurn(
            turn_id=existing.id,
            sequence_number=existing.sequence_number,
            created=False,
        )

    next_seq = (
        await session.execute(
            select(func.coalesce(func.max(VoiceTurnRow.sequence_number), 0)).where(
                VoiceTurnRow.session_id == voice_session_id
            )
        )
    ).scalar_one() + 1

    row = VoiceTurnRow(
        id=uuid.uuid4(),
        session_id=voice_session_id,
        tenant_id=tenant_id,
        sequence_number=next_seq,
        # The turn is the caller's utterance and the answer it got, so the speaker is the caller.
        speaker="user",
        state=TurnState.COMPLETED.value,
        input_modality=VOICE_MODALITY,
        output_modality=VOICE_MODALITY,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        completed_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return CompletedTurn(turn_id=row.id, sequence_number=next_seq, created=True)


async def record_turn(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    voice_session_id: uuid.UUID | None,
    plan: TranscriptPlan,
    idempotency_key: str | None = None,
) -> TurnMessages:
    """Write the plan into the conversation and return the ids the turn should keep."""
    user_row, created = await _write_question(
        session,
        tenant_id=tenant_id,
        voice_session_id=voice_session_id,
        plan=plan,
        idempotency_key=idempotency_key,
    )
    if not created:
        return TurnMessages(user_message_id=user_row.id, replayed=True)

    assistant_row: AIChatMessage | None = None
    if plan.assistant_text is not None:
        assistant_row = _message(
            tenant_id=tenant_id,
            plan=plan,
            voice_session_id=voice_session_id,
            sequence_no=user_row.sequence_no + 1,
            role="assistant",
            content=plan.assistant_text,
            idempotency_key=None,
        )
        session.add(assistant_row)
        await session.flush()

    return TurnMessages(
        user_message_id=user_row.id,
        assistant_message_id=assistant_row.id if assistant_row is not None else None,
    )


async def link_turn(session: Any, *, turn_id: uuid.UUID, messages: TurnMessages) -> None:
    """Point the turn row at the messages it became."""
    await session.execute(
        update(VoiceTurnRow)
        .where(VoiceTurnRow.id == turn_id)
        .values(
            user_message_id=messages.user_message_id,
            assistant_message_id=messages.assistant_message_id,
        )
    )
    await session.flush()


async def sync_turn(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    voice_session_id: uuid.UUID,
    thread_id: uuid.UUID | None,
    turn_id: uuid.UUID | None = None,
    user_text: str | None,
    assistant_text: str | None = None,
    transcript_status: str = "final",
    idempotency_key: str | None = None,
) -> TurnMessages:
    """The whole job for a turn: validate, write the messages, link the turn row."""
    plan = plan_turn(
        thread_id=thread_id,
        user_text=user_text,
        assistant_text=assistant_text,
        transcript_status=transcript_status,
    )
    messages = await record_turn(
        session,
        tenant_id=tenant_id,
        voice_session_id=voice_session_id,
        plan=plan,
        idempotency_key=idempotency_key,
    )
    if turn_id is not None and not messages.replayed:
        await link_turn(session, turn_id=turn_id, messages=messages)
    return messages
