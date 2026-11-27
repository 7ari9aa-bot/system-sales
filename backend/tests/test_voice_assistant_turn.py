"""A spoken turn is a turn: same conversation, same agent, same runtime.

What makes voice safe is what it does NOT have — its own thread, its own agent,
its own tools. These tests pin that: the transcript lands in the conversation the
voice session belongs to, the turn reaches the shared runtime with
``modality=live_voice``, an empty transcript never costs a model call, and a
replayed key returns the existing answer instead of buying a second one.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationError
from app.modules.ai.assistant.contracts import LIVE_VOICE
from app.modules.voice.application import assistant_turn

TENANT = uuid.uuid4()
AGENT = uuid.uuid4()
THREAD = uuid.uuid4()
VOICE_SESSION = uuid.uuid4()


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _ctx():
    return SimpleNamespace(tenant_id=TENANT)


def _thread():
    return SimpleNamespace(id=THREAD, tenant_id=TENANT, agent_id=AGENT)


@pytest.fixture
def wired(monkeypatch):
    """Every collaborator stubbed, and every call recorded."""
    seen: dict[str, list] = {"runtime": [], "appended": [], "threads": [], "replies": []}

    async def fake_ensure_thread(session, ctx, session_id):
        seen["threads"].append(session_id)
        return _thread()

    async def fake_append(session, ctx, thread, content, idempotency_key=None):
        seen["appended"].append((thread.id, content, idempotency_key))
        return SimpleNamespace(id=uuid.uuid4(), sequence_no=1), True

    async def fake_run_chat_turn(session, ctx, thread):
        seen["runtime"].append(thread.id)
        return SimpleNamespace(
            id=uuid.uuid4(), thread_id=thread.id, content="أيوه، الأوردر اتشحن", status="completed"
        )

    async def fake_bind(session, tenant_id):
        return None

    monkeypatch.setattr(assistant_turn, "ensure_session_thread", fake_ensure_thread)
    monkeypatch.setattr(assistant_turn.chat_service, "append_user_message", fake_append)
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
    assert wired["appended"] == [(THREAD, "الأوردر وصل؟", None)]
    assert wired["runtime"] == [THREAD]
    assert session.commits == 1


async def test_an_empty_transcript_is_refused_before_anything_costs_money(wired):
    with pytest.raises(ValidationError):
        await assistant_turn.run_voice_turn(
            _Session(), _ctx(), session_id=VOICE_SESSION, text="   "
        )

    assert wired["appended"] == []
    assert wired["runtime"] == []


async def test_a_replayed_key_returns_the_existing_answer_instead_of_a_second_call(
    wired, monkeypatch
):
    async def replayed(session, ctx, thread, content, idempotency_key=None):
        return SimpleNamespace(id=uuid.uuid4(), sequence_no=1), False

    async def existing_reply(session, ctx, thread, user_seq):
        return SimpleNamespace(id=uuid.uuid4(), content="الرد الأول", status="completed")

    monkeypatch.setattr(assistant_turn.chat_service, "append_user_message", replayed)
    monkeypatch.setattr(assistant_turn.chat_service, "get_assistant_reply_for", existing_reply)

    result = await assistant_turn.run_voice_turn(
        _Session(), _ctx(), session_id=VOICE_SESSION, text="الأوردر وصل؟", idempotency_key="k1"
    )

    assert result.content == "الرد الأول"
    assert result.modality == LIVE_VOICE
    assert wired["runtime"] == []
