"""A browser call must leave a trail: the provider session, ACTIVE, then an ending.

Measured on the owner's live database before this wiring: 30 voice sessions, every
one of them CONFIGURING, not one with a ``provider_session_id``, and no ``voice_turns``
at all. ``VoiceSessionManager`` could already make every move — ``attach_provider``,
``activate``, ``close`` and ``fail`` all existed — but nothing on the socket path ever
called them, so a session was opened and then forgotten.

These tests drive the socket path itself, with the provider, the grant store and the
database replaced by stubs, because the wiring is the thing that was missing.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.voice.domain.states import IllegalTransition
from app.modules.voice.routers import sessions as api
from app.modules.voice.runtime.gpt_live import GptLiveUnavailable

TENANT = uuid.uuid4()
SESSION = uuid.uuid4()
PROVIDER = "sess_live_1"


class _Recorder:
    """A manager that writes down every lifecycle move instead of making it."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def attach_provider(self, session_id, provider_session_id):
        self.calls.append(("attach", session_id, provider_session_id))

    async def activate(self, session_id):
        self.calls.append(("activate", session_id))

    async def close(self, session_id, *, reason="caller_hangup", tenant_id=None):
        self.calls.append(("close", session_id, reason))

    async def fail(self, session_id, *, reason):
        self.calls.append(("fail", session_id, reason))


class _StillConfiguring(_Recorder):
    """The row a socket leaves behind when it dies before the provider connected."""

    async def close(self, session_id, *, reason="caller_hangup", tenant_id=None):
        raise IllegalTransition("voice_session", "CONFIGURING", "CLOSING")


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, *_args, **_kwargs):
        return None

    async def commit(self) -> None:
        return None


class _WebSocket:
    def __init__(self, messages: list[dict] | None = None) -> None:
        self._messages = list(messages or [])
        self.sent: list[bytes] = []
        self.closed_with: int | None = None

    async def accept(self) -> None:
        return None

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    async def receive(self) -> dict:
        if self._messages:
            return self._messages.pop(0)
        return {"type": "websocket.disconnect"}

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


class _Call:
    def __init__(self, provider_session_id: str | None = PROVIDER) -> None:
        self.provider_session_id = provider_session_id
        self.closed = False
        self.pushed: list[bytes] = []
        self.interrupts = 0

    async def pump(self) -> None:
        self.closed = True

    async def push_audio(self, chunk: bytes) -> None:
        self.pushed.append(chunk)

    async def interrupt(self) -> None:
        self.interrupts += 1

    async def close(self) -> None:
        self.closed = True


def _install(monkeypatch, recorder: _Recorder, call_factory) -> None:
    grant = type(
        "Grant",
        (),
        {"session_id": str(SESSION), "tenant_id": str(TENANT), "user_id": str(uuid.uuid4())},
    )()

    class _Issuer:
        def verify(self, _ticket, *, session_id):
            return type("Claims", (), {"jti": "jti", "tenant_id": str(TENANT)})()

    class _Grants:
        async def take(self, _jti):
            return grant

    async def _config(_tenant_id):
        return {}

    monkeypatch.setattr(api, "_stream_issuer", lambda: _Issuer())
    monkeypatch.setattr(api, "_grant_store", lambda: _Grants())
    monkeypatch.setattr(api, "_voice_config", _config)
    monkeypatch.setattr(api, "_call_factory", lambda: call_factory)
    monkeypatch.setattr(api, "_session_factory", lambda: _Session)
    monkeypatch.setattr(api, "VoiceSessionManager", lambda _store: recorder)


@pytest.mark.asyncio
async def test_a_connected_call_records_the_provider_and_goes_active(monkeypatch) -> None:
    recorder = _Recorder()
    call = _Call()
    _install(monkeypatch, recorder, lambda **_kwargs: _await(call))

    await api.stream_audio(_WebSocket(), SESSION, ticket="t")

    assert recorder.calls == [
        ("attach", SESSION, PROVIDER),
        ("activate", SESSION),
        ("close", SESSION, "socket_closed"),
    ]
    assert call.closed is True


@pytest.mark.asyncio
async def test_a_call_that_never_reached_the_provider_ends_as_failed(monkeypatch) -> None:
    recorder = _Recorder()

    async def _unavailable(**_kwargs):
        raise GptLiveUnavailable("no gateway key is configured for voice")

    _install(monkeypatch, recorder, _unavailable)
    websocket = _WebSocket()

    await api.stream_audio(websocket, SESSION, ticket="t")

    assert recorder.calls == [
        ("fail", SESSION, "provider_unavailable:GptLiveUnavailable"),
    ]
    assert websocket.closed_with == 1011


@pytest.mark.asyncio
async def test_a_socket_that_dies_before_connect_is_failed_not_left_configuring(
    monkeypatch,
) -> None:
    recorder = _StillConfiguring()
    _install(monkeypatch, recorder, lambda **_kwargs: _await(_Call(provider_session_id=None)))

    await api.stream_audio(_WebSocket(), SESSION, ticket="t")

    # No provider session means no CONNECTING, so the row must be ended as FAILED
    # rather than closed: CONFIGURING -> CLOSING is a move the machine refuses.
    assert ("fail", SESSION, "socket_closed") in recorder.calls
    assert not any(call[0] == "close" for call in recorder.calls)


async def _await(value):
    return value
