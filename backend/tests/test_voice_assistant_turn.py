"""A spoken turn is a turn: same conversation, same agent, same runtime.

What makes voice safe is what it does NOT have — its own thread, its own agent,
its own tools. These tests pin that: the transcript lands in the conversation the
voice session belongs to, the turn reaches the shared runtime with
``modality=live_voice``, an empty transcript never costs a model call, and a
replayed key returns the existing answer instead of buying a second one.

They also pin the single-writer rule: the live path writes its question through
``transcript_sync.open_turn`` and finishes the turn through
``transcript_sync.complete_turn``. Nothing here calls
``chat_service.append_user_message`` — a second writer is how the two paths
drifted apart and left every voice turn unlinked.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationError
from app.modules.ai.assistant.contracts import LIVE_VOICE
from app.modules.voice.application import assistant_turn
from app.modules.voice.application.transcript_sync import CompletedTurn, OpenedTurn

TENANT = uuid.uuid4()
AGENT = uuid.uuid4()
THREAD = uuid.uuid4()
VOICE_SESSION = uuid.uuid4()


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


class _Manager:
    def __init__(self, seen):
        self._seen = seen

    async def note_turn_completed(self, session_id, sequence):
        self._seen["counted"].append((session_id, sequence))


def _ctx():
    return SimpleNamespace(tenant_id=TENANT)


def _thread():
    return SimpleNamespace(id=THREAD, tenant_id=TENANT, agent_id=AGENT)


@pytest.fixture
def wired(monkeypatch):
    """Every collaborator stubbed, and every call recorded."""
    seen: dict[str, list] = {
        "runtime": [],
        "opened": [],
        "completed": [],
        "threads": [],
        "counted": [],
    }

    async def fake_ensure_thread(session, ctx, session_id):
        seen["threads"].append(session_id)
        return THREAD

    async def fake_get_thread(session, ctx, thread_id):
        assert thread_id == THREAD
        return _thread()

    async def fake_open_turn(
        session,
        *,
        tenant_id,
        voice_session_id,
        thread,
        user_text,
        idempotency_key=None,
        transcript_status="final",
    ):
        seen["opened"].append((voice_session_id, thread.id, user_text, idempotency_key))
        return OpenedTurn(user_message_id=uuid.uuid4(), user_sequence_no=1, created=True)

    async def fake_complete_turn(
        session,
        *,
        tenant_id,
        voice_session_id,
        thread_id,
        user_message_id,
        assistant_message_id,
        transcript_status="final",
    ):
        seen["completed"].append(
            (voice_session_id, thread_id, user_message_id, assistant_message_id)
        )
        return CompletedTurn(turn_id=uuid.uuid4(), sequence_number=1, created=True)

    async def fake_run_chat_turn(session, ctx, thread):
        seen["runtime"].append(thread.id)
        return SimpleNamespace(
            id=uuid.uuid4(), thread_id=thread.id, content="أيوه، الأوردر اتشحن", status="completed"
        )

    async def fake_bind(session, tenant_id):
        return None

    monkeypatch.setattr(assistant_turn, "ensure_session_thread", fake_ensure_thread)
    monkeypatch.setattr(assistant_turn.chat_service, "get_thread", fake_get_thread)
    monkeypatch.setattr(assistant_turn.transcript_sync, "open_turn", fake_open_turn)
    monkeypatch.setattr(assistant_turn.transcript_sync, "complete_turn", fake_complete_turn)
    monkeypatch.setattr(assistant_turn, "_session_manager", lambda session: _Manager(seen))
    monkeypatch.setattr(assistant_turn, "bind_tenant", fake_bind)
    monkeypatch.setattr("app.modules.ai.chat.turns.run_chat_turn", fake_run_chat_turn)
    return seen


async def test_a_spoken_turn_is_answered_on_the_thread_its_session_belongs_to(wired):
    session = _Session()

    result = await assistant_turn.run_voice_turn(
        session, _ctx(), session_id=VOICE_SESSION, text="الأوردر وصل؟"
    )

    assert result.thread_id == THREAD
    assert result.agent_id == AGENT
    assert result.modality == LIVE_VOICE
    assert result.content == "أيوه، الأوردر اتشحن"
    # The session resolved its own thread, the transcript went in as the question,
    # and the SAME runtime answered it — no second brain, no second conversation.
    assert wired["threads"] == [VOICE_SESSION]
    assert wired["opened"] == [(VOICE_SESSION, THREAD, "الأوردر وصل؟", None)]
    assert wired["runtime"] == [THREAD]
    assert session.commits == 2


async def test_a_completed_turn_is_linked_to_both_messages_and_counted(wired):
    await assistant_turn.run_voice_turn(
        _Session(), _ctx(), session_id=VOICE_SESSION, text="الأوردر وصل؟"
    )

    # ONE turn row, and it keeps both ids: the question transcript_sync wrote and
    # the answer the runtime wrote.
    assert len(wired["completed"]) == 1
    voice_session_id, thread_id, user_message_id, assistant_message_id = wired["completed"][0]
    assert voice_session_id == VOICE_SESSION
    assert thread_id == THREAD
    assert user_message_id is not None
    assert assistant_message_id is not None
    assert user_message_id != assistant_message_id
    # and the session's own turn counter moved, so "resume from turn N" is honest
    assert wired["counted"] == [(VOICE_SESSION, 1)]


async def test_an_empty_transcript_is_refused_before_anything_costs_money(wired):
    with pytest.raises(ValidationError):
        await assistant_turn.run_voice_turn(
            _Session(), _ctx(), session_id=VOICE_SESSION, text="   "
        )

    assert wired["opened"] == []
    assert wired["runtime"] == []


async def test_a_replayed_key_returns_the_existing_answer_instead_of_a_second_call(
    wired, monkeypatch
):
    async def replayed(
        session,
        *,
        tenant_id,
        voice_session_id,
        thread,
        user_text,
        idempotency_key=None,
        transcript_status="final",
    ):
        return OpenedTurn(user_message_id=uuid.uuid4(), user_sequence_no=1, created=False)

    async def existing_reply(session, ctx, thread, *, user_seq):
        return SimpleNamespace(id=uuid.uuid4(), content="الرد الأول", status="completed")

    monkeypatch.setattr(assistant_turn.transcript_sync, "open_turn", replayed)
    monkeypatch.setattr(assistant_turn.chat_service, "get_assistant_reply_for", existing_reply)

    result = await assistant_turn.run_voice_turn(
        _Session(), _ctx(), session_id=VOICE_SESSION, text="الأوردر وصل؟", idempotency_key="k1"
    )

    assert result.content == "الرد الأول"
    assert result.modality == LIVE_VOICE
    # No model call and no second turn: a replay adds nothing.
    assert wired["runtime"] == []
    assert wired["completed"] == []
    assert wired["counted"] == []
