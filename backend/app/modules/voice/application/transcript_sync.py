"""A spoken turn becomes a message in the conversation, not a parallel record.

The voice tables answer "what did this call do"; the conversation answers "what was said". Until
this module there was no bridge, so a spoken question could not be found by the next typed one and
a reconnect could not resume anything. Everything here writes INTO ``ai_chat_messages``: the turn
row keeps the two ids (``user_message_id``/``assistant_message_id``) and never a second copy of the
words.

Two rules are enforced rather than documented:

* A session with no ``ai_chat_thread_id`` cannot record a turn. Guessing a thread would attach a
  stranger's words to somebody's conversation, so it is refused.
* A turn with no heard words is not a message. An empty transcript is a failed recognition, not a
  user who said nothing, and writing it would put a blank bubble in the timeline.

Ordering is the conversation's own (``sequence_no`` = max + 1), so a spoken turn and a typed turn
interleave correctly and a repeated write cannot jump the queue.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import func, select, update

from app.modules.ai.models import AIChatMessage
from app.modules.voice.domain.models import VoiceTurnRow

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


async def record_turn(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    voice_session_id: uuid.UUID | None,
    plan: TranscriptPlan,
    idempotency_key: str | None = None,
) -> TurnMessages:
    """Write the plan into the conversation and return the ids the turn should keep."""
    key = (idempotency_key or "").strip() or None

    if key is not None:
        # A worker that reconnects mid-turn replays the same key. Returning the existing message
        # is the whole point: the user must not see their question twice, and the backend must
        # not run the same analysis twice.
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
            return TurnMessages(user_message_id=existing.id, replayed=True)

    next_seq = (
        await session.execute(
            select(func.coalesce(func.max(AIChatMessage.sequence_no), 0)).where(
                AIChatMessage.tenant_id == tenant_id,
                AIChatMessage.thread_id == plan.thread_id,
            )
        )
    ).scalar_one() + 1

    user_row = _message(
        tenant_id=tenant_id,
        plan=plan,
        voice_session_id=voice_session_id,
        sequence_no=next_seq,
        role="user",
        content=plan.user_text,
        idempotency_key=key,
    )
    session.add(user_row)

    assistant_row: AIChatMessage | None = None
    if plan.assistant_text is not None:
        assistant_row = _message(
            tenant_id=tenant_id,
            plan=plan,
            voice_session_id=voice_session_id,
            sequence_no=next_seq + 1,
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
    """The whole job for one turn: validate, write the messages, link the turn row."""
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
