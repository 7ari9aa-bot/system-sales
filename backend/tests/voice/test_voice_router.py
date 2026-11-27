"""The control-plane endpoints, driven directly: the request cannot choose the persona.

Calling the endpoint functions (instead of going through HTTP) keeps this test free of a database
while still proving the two things that matter: the persona and scopes come from the authenticated
context, and a retried client key returns the session that is already open.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.ai.chat import service as chat_service
from app.modules.voice.application.session_manager import (
    InMemorySessionStore,
    VoiceSessionManager,
)
from app.modules.voice.routers import sessions as api

TENANT = uuid.uuid4()
USER = uuid.uuid4()


class _SessionRow:
    """The voice_sessions row the start path reads to find (or open) its conversation."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.ai_chat_thread_id = None


class _DbStub:
    """Just enough AsyncSession for the thread bridge, with no database behind it."""

    def __init__(self, row: object) -> None:
        self.row = row
        self.flushed = 0

    async def execute(self, _statement: object) -> object:
        row = self.row
        return SimpleNamespace(scalar_one_or_none=lambda: row)

    async def flush(self) -> None:
        self.flushed += 1


def _ctx(permissions: set[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        session=_DbStub(_SessionRow()),
        user=SimpleNamespace(id=USER),
        tenant_id=TENANT,
        workspace_id=None,
        permission_codes=permissions or {"orders:read", "inventory:read"},
    )


@pytest.fixture()
def manager(monkeypatch: pytest.MonkeyPatch) -> VoiceSessionManager:
    built = VoiceSessionManager(InMemorySessionStore())
    monkeypatch.setattr(api, "_manager", lambda _ctx: built)

    # Starting a session opens its conversation through the chat module. That module needs the
    # real agent registry, so it is stubbed here: what this file proves is the control plane, and
    # the bridge itself is covered by tests/voice/test_session_thread.py.
    async def _fake_create_thread(_session, _ctx, *, title=None, context=None):
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(chat_service, "create_thread", _fake_create_thread)
    return built


class TestStartSession:
    async def test_the_persona_comes_from_the_context_not_the_body(
        self, manager: VoiceSessionManager
    ) -> None:
        response = await api.start_session(_ctx(), api.StartSessionRequest())

        assert response.persona == "merchant_assistant"
        assert response.tenant_id == TENANT
        assert response.state == "CONFIGURING"
        assert response.scopes == ["inventory:read", "orders:read"]
        assert response.trace_id

    def test_a_caller_cannot_ask_for_a_persona(self) -> None:
        with pytest.raises(ValidationError):
            api.StartSessionRequest.model_validate(
                {"channel": "web_voice", "persona": "merchant_assistant"}
            )

    async def test_a_retried_client_key_returns_the_open_session(
        self, manager: VoiceSessionManager
    ) -> None:
        body = api.StartSessionRequest(client_key="browser-tab-1")
        first = await api.start_session(_ctx(), body)
        second = await api.start_session(_ctx(), body)

        assert first.session_id == second.session_id

    async def test_a_member_with_no_readable_scope_cannot_open_a_session(self) -> None:
        from app.core.errors import PermissionDeniedError

        with pytest.raises(PermissionDeniedError):
            await api.start_session(_ctx({"settings:write"}), api.StartSessionRequest())


class TestSessionLifecycle:
    async def test_interrupt_handoff_and_close_are_reflected_in_the_response(
        self, manager: VoiceSessionManager
    ) -> None:
        started = await api.start_session(_ctx(), api.StartSessionRequest())
        # A call can only be interrupted once the media path is up.
        await manager.attach_provider(started.session_id, "prov-1")
        await manager.activate(started.session_id)

        interrupted = await api.interrupt_session(_ctx(), started.session_id)
        assert interrupted.state == "INTERRUPTED"

        handoff = await api.hand_off_session(_ctx(), started.session_id)
        assert handoff.state == "HANDOFF_PENDING"

        closed = await api.close_session(
            _ctx(), started.session_id, api.CloseSessionRequest(reason="caller_hangup")
        )
        assert closed.state == "CLOSED"

    async def test_reading_another_tenants_session_is_a_not_found(
        self, manager: VoiceSessionManager
    ) -> None:
        from app.core.errors import NotFoundError

        started = await api.start_session(_ctx(), api.StartSessionRequest())
        stranger = _ctx()
        stranger.tenant_id = uuid.uuid4()

        with pytest.raises(NotFoundError):
            await api.read_session(stranger, started.session_id)

    async def test_an_unknown_channel_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            api.StartSessionRequest.model_validate({"channel": "carrier_pigeon"})
