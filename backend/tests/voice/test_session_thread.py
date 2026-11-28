"""A voice session must own a conversation, and only one.

The bug this pins: ``voice_sessions.ai_chat_thread_id`` was added and never written, so every call
belonged to no conversation and transcript sync had to refuse every turn. These tests prove the
thread is opened once, reused on a replay, and refused across tenants.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import NotFoundError
from app.applications.apparel.modules.ai.chat import service as chat_service
from app.modules.voice.application import session_thread
from app.modules.voice.application.session_thread import DEFAULT_TITLE, ensure_session_thread

TENANT = uuid.uuid4()
SESSION_ID = uuid.uuid4()


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Row:
    def __init__(self, thread_id: uuid.UUID | None = None) -> None:
        self.ai_chat_thread_id = thread_id


class _Session:
    def __init__(self, row: object) -> None:
        self.row = row
        self.flushes = 0
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        return _Result(self.row)

    async def flush(self) -> None:
        self.flushes += 1


class _Ctx:
    def __init__(self) -> None:
        self.tenant_id = TENANT
        self.user = type("U", (), {"id": uuid.uuid4()})()


def _patch_create(monkeypatch: pytest.MonkeyPatch, thread_id: uuid.UUID) -> list[dict]:
    calls: list[dict] = []

    async def fake_create(session, ctx, *, title=None, context=None):
        calls.append({"title": title})
        return type("T", (), {"id": thread_id})()

    monkeypatch.setattr(chat_service, "create_thread", fake_create)
    return calls


async def test_a_session_without_a_conversation_opens_exactly_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread_id = uuid.uuid4()
    calls = _patch_create(monkeypatch, thread_id)
    row = _Row()
    session = _Session(row)

    opened = await ensure_session_thread(session, _Ctx(), session_id=SESSION_ID)

    assert opened == thread_id
    assert row.ai_chat_thread_id == thread_id
    assert session.flushes == 1
    assert calls == [{"title": DEFAULT_TITLE}]


async def test_a_replay_returns_the_thread_it_already_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = uuid.uuid4()
    calls = _patch_create(monkeypatch, uuid.uuid4())
    row = _Row(existing)
    session = _Session(row)

    opened = await ensure_session_thread(session, _Ctx(), session_id=SESSION_ID)

    assert opened == existing
    assert calls == []
    assert session.flushes == 0


async def test_another_shops_session_is_not_found_rather_than_adopted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_create(monkeypatch, uuid.uuid4())
    session = _Session(None)

    with pytest.raises(NotFoundError):
        await ensure_session_thread(session, _Ctx(), session_id=SESSION_ID)

    assert calls == []


def test_the_thread_is_opened_through_the_chat_module_not_by_hand() -> None:
    """The agent is resolved server-side by kind, so this must go through create_thread.

    A hand-built AIChatThread would need an agent_id, and the only way to get one here is to trust
    something the caller supplied — which is the hole create_thread exists to close.
    """
    import inspect

    source = inspect.getsource(session_thread.ensure_session_thread)
    assert "chat_service.create_thread(" in source
    assert "AIChatThread(" not in source
