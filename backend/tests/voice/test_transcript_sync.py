"""A spoken turn must land in the conversation, and only once.

These tests are the tripwire for the failure that made the voice layer useless: words spoken into
a call that never appear in the thread the merchant is reading. They also pin the two refusals —
a session with no thread, and a turn with no recognised words — because both would otherwise put
somebody else's blank or misplaced bubble in a timeline.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.sql.dml import Update

from app.modules.voice.application.transcript_sync import (
    VOICE_MODALITY,
    TranscriptError,
    plan_turn,
    record_turn,
    sync_turn,
)

TENANT = uuid.uuid4()
THREAD = uuid.uuid4()
SESSION = uuid.uuid4()
TURN = uuid.uuid4()


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value

    def scalar_one(self) -> object:
        return self._value


class _FakeSession:
    """Just enough session to prove what would be written, without a database."""

    def __init__(
        self, *, existing: object = None, max_seq: int = 0, with_key: bool = False
    ) -> None:
        self.existing = existing
        self.max_seq = max_seq
        self._expect_existing = with_key
        self.added: list[object] = []
        self.statements: list[object] = []
        self.flushes = 0

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        if self._expect_existing:
            self._expect_existing = False
            return _Result(self.existing)
        return _Result(self.max_seq)

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushes += 1


def test_a_session_without_a_conversation_cannot_record_a_turn() -> None:
    with pytest.raises(TranscriptError):
        plan_turn(thread_id=None, user_text="كام مبيعات النهاردة؟")


def test_a_turn_with_no_heard_words_is_not_a_message() -> None:
    for empty in ("", "   ", None):
        with pytest.raises(TranscriptError):
            plan_turn(thread_id=THREAD, user_text=empty)


def test_a_transcript_status_outside_the_two_known_values_is_refused() -> None:
    with pytest.raises(TranscriptError):
        plan_turn(thread_id=THREAD, user_text="أيوه", transcript_status="maybe")


def test_an_empty_reply_becomes_no_message_rather_than_a_blank_bubble() -> None:
    plan = plan_turn(thread_id=THREAD, user_text="أيوه", assistant_text="   ")
    assert plan.assistant_text is None


async def test_both_sides_of_a_turn_are_written_with_their_modality() -> None:
    session = _FakeSession(max_seq=4)

    messages = await record_turn(
        session,
        tenant_id=TENANT,
        voice_session_id=SESSION,
        plan=plan_turn(thread_id=THREAD, user_text="قارن مبيعات الأسبوع", assistant_text="تمام"),
    )

    assert [row.sequence_no for row in session.added] == [5, 6]
    user_row, assistant_row = session.added
    assert user_row.role == "user" and assistant_row.role == "assistant"
    assert user_row.input_modality == VOICE_MODALITY
    assert user_row.output_modality is None
    assert assistant_row.output_modality == VOICE_MODALITY
    assert assistant_row.input_modality is None
    for row in (user_row, assistant_row):
        assert row.voice_session_id == SESSION
        assert row.transcript_status == "final"
        assert row.thread_id == THREAD
    assert messages.user_message_id == user_row.id
    assert messages.assistant_message_id == assistant_row.id


async def test_a_turn_that_was_only_heard_writes_one_message() -> None:
    session = _FakeSession()

    messages = await record_turn(
        session,
        tenant_id=TENANT,
        voice_session_id=SESSION,
        plan=plan_turn(thread_id=THREAD, user_text="لحظة"),
    )

    assert len(session.added) == 1
    assert messages.assistant_message_id is None


async def test_a_replayed_turn_returns_the_existing_message_and_writes_nothing() -> None:
    existing = type("Existing", (), {"id": uuid.uuid4()})()
    session = _FakeSession(existing=existing, with_key=True)

    messages = await record_turn(
        session,
        tenant_id=TENANT,
        voice_session_id=SESSION,
        plan=plan_turn(thread_id=THREAD, user_text="قارن مبيعات الأسبوع"),
        idempotency_key="turn-7",
    )

    assert messages.replayed is True
    assert messages.user_message_id == existing.id
    assert session.added == []


async def test_the_turn_row_keeps_the_ids_of_the_messages_it_became() -> None:
    session = _FakeSession()

    await sync_turn(
        session,
        tenant_id=TENANT,
        voice_session_id=SESSION,
        thread_id=THREAD,
        turn_id=TURN,
        user_text="إيه سبب الانخفاض؟",
        assistant_text="الانخفاض من فئة واحدة.",
    )

    updates = [s for s in session.statements if isinstance(s, Update)]
    assert len(updates) == 1
    assert updates[0].table.name == "voice_turns"
    values = updates[0].compile().params
    assert any(isinstance(v, uuid.UUID) for v in values.values())
