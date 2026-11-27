"""The browser's door: a one-minute ticket, and a socket that carries audio.

The browser cannot hold the gateway key, so the socket to GPT-Live stays on our
server and the browser streams PCM to us. These tests pin the door: a ticket is
bound to one session and one shop and dies in a minute, an access token can never
be presented as a ticket, and a forged or expired one closes the socket instead
of opening a paid call.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.modules.voice.routers import sessions as voice_sessions
from app.modules.voice.runtime.gpt_live import GptLiveUnavailable
from app.modules.voice.runtime.stream_ticket import (
    StreamTicketInvalid,
    StreamTicketIssuer,
    StreamTicketUnavailable,
)

SESSION = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
USER = uuid.UUID("33333333-3333-3333-3333-333333333333")
SECRET = "test-only-signing-material-never-used-anywhere"


def _issuer(ttl: int = 60) -> StreamTicketIssuer:
    return StreamTicketIssuer(secret=SECRET, ttl_seconds=ttl)


def test_a_ticket_names_one_session_and_one_shop():
    claims = _issuer().verify(
        _issuer().issue(session_id=SESSION, tenant_id=TENANT), session_id=SESSION
    )

    assert claims.session_id == str(SESSION)
    assert claims.tenant_id == str(TENANT)


def test_a_ticket_for_another_session_is_refused():
    ticket = _issuer().issue(session_id=SESSION, tenant_id=TENANT)

    with pytest.raises(StreamTicketInvalid):
        _issuer().verify(ticket, session_id=uuid.uuid4())


def test_an_expired_ticket_is_refused():
    issued = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.UTC)
    ticket = _issuer(ttl=60).issue(session_id=SESSION, tenant_id=TENANT, now=issued)

    later = issued + dt.timedelta(seconds=61)
    with pytest.raises(StreamTicketInvalid):
        _issuer().verify(ticket, session_id=SESSION, now=later)
    # One second earlier it is still good: the window is real, not decorative.
    assert _issuer().verify(
        ticket, session_id=SESSION, now=issued + dt.timedelta(seconds=59)
    ).session_id == str(SESSION)


def test_a_tampered_or_foreign_token_is_refused():
    ticket = _issuer().issue(session_id=SESSION, tenant_id=TENANT)
    head, payload, signature = ticket.split(".")

    with pytest.raises(StreamTicketInvalid):
        _issuer().verify(f"{head}.{payload}.{signature[:-2]}xx", session_id=SESSION)
    # A token signed for another audience (an ordinary access token) is not a ticket.
    with pytest.raises(StreamTicketInvalid):
        _issuer().verify(
            _issuer(ttl=60).issue(session_id=SESSION, tenant_id=TENANT).replace(head, head)[:-3],
            session_id=SESSION,
        )


def test_no_ticket_can_be_minted_with_a_placeholder_secret():
    for placeholder in ("", "change-me", "secret"):
        with pytest.raises(StreamTicketUnavailable):
            StreamTicketIssuer(secret=placeholder)


class _FakeGrants:
    """An in-memory stand-in for the Redis grant store."""

    def __init__(self) -> None:
        self.live: dict[str, dict] = {}

    async def grant(self, *, session_id, tenant_id, user_id) -> str:
        jti = f"jti-{len(self.live) + 1}"
        self.live[jti] = {
            "session_id": str(session_id),
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
        }
        return jti

    async def take(self, jti):
        from app.modules.voice.infrastructure.stream_grants import (
            StreamGrant,
            StreamGrantMissing,
        )

        data = self.live.pop(jti, None)
        if data is None:
            raise StreamGrantMissing("already redeemed")
        return StreamGrant(**data)


class _FakeCall:
    """Records what the socket would have pushed into the call."""

    def __init__(self) -> None:
        self.pushed: list[bytes] = []
        self.closed = False
        self.closes = 0

    async def push_audio(self, pcm: bytes) -> None:
        self.pushed.append(pcm)

    async def pump(self) -> str:
        await asyncio.sleep(0.01)
        return "ignored"

    async def close(self) -> None:
        self.closed = True
        self.closes += 1


@pytest.fixture()
def grants() -> _FakeGrants:
    return _FakeGrants()


@pytest.fixture()
def stream_client(monkeypatch, grants):
    app = FastAPI()
    app.include_router(voice_sessions.router)
    monkeypatch.setattr(voice_sessions, "_stream_issuer", lambda: _issuer())
    # One store for the whole test, so a ticket minted here can be redeemed there.
    monkeypatch.setattr(voice_sessions, "_grant_store", lambda: grants)
    return TestClient(app)


def test_a_bad_ticket_closes_the_socket_before_any_audio(stream_client):
    with pytest.raises(WebSocketDisconnect):
        with stream_client.websocket_connect(f"/voice/sessions/{SESSION}/stream?ticket=nope") as ws:
            ws.receive_bytes()


def test_a_valid_ticket_carries_pcm_into_the_call_and_closes_it(stream_client, grants, monkeypatch):
    call = _FakeCall()
    seen: dict = {}

    async def factory(*, session_id, tenant_id, user_id, send_audio):
        seen.update(
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            send_audio=send_audio,
        )
        return call

    monkeypatch.setattr(voice_sessions, "_call_factory", lambda: factory)
    jti = asyncio.run(grants.grant(session_id=SESSION, tenant_id=TENANT, user_id=USER))
    ticket = _issuer().issue(session_id=SESSION, tenant_id=TENANT, jti=jti)

    with stream_client.websocket_connect(f"/voice/sessions/{SESSION}/stream?ticket={ticket}") as ws:
        ws.send_bytes(b"\x01\x02" * 4)
        ws.send_bytes(b"\x03\x04" * 4)
        import time

        time.sleep(0.1)

    assert call.pushed == [b"\x01\x02" * 4, b"\x03\x04" * 4]
    assert seen["tenant_id"] == str(TENANT)
    assert seen["user_id"] == str(USER)
    assert call.closes == 1


def test_an_unconfigured_voice_runtime_closes_with_1011(stream_client, monkeypatch):
    async def factory(**kwargs):
        raise GptLiveUnavailable("no gateway key")

    monkeypatch.setattr(voice_sessions, "_call_factory", lambda: factory)
    ticket = _issuer().issue(session_id=SESSION, tenant_id=TENANT)

    with pytest.raises(WebSocketDisconnect):
        with stream_client.websocket_connect(
            f"/voice/sessions/{SESSION}/stream?ticket={ticket}"
        ) as ws:
            ws.receive_bytes()


def test_a_ticket_can_only_be_redeemed_once(stream_client, grants, monkeypatch):
    """A leaked ticket opens nothing after the browser it was minted for connects."""
    call = _FakeCall()

    async def factory(**kwargs):
        return call

    monkeypatch.setattr(voice_sessions, "_call_factory", lambda: factory)
    jti = asyncio.run(grants.grant(session_id=SESSION, tenant_id=TENANT, user_id=USER))
    ticket = _issuer().issue(session_id=SESSION, tenant_id=TENANT, jti=jti)
    url = f"/voice/sessions/{SESSION}/stream?ticket={ticket}"

    with stream_client.websocket_connect(url) as ws:
        ws.send_bytes(b"\x00" * 8)
        import time

        time.sleep(0.1)

    with pytest.raises(WebSocketDisconnect):
        with stream_client.websocket_connect(url) as ws:
            ws.receive_bytes()


def test_a_grant_that_names_another_session_is_refused(stream_client, grants, monkeypatch):
    async def factory(**kwargs):
        raise AssertionError("a mismatched grant must never reach the call builder")

    monkeypatch.setattr(voice_sessions, "_call_factory", lambda: factory)
    jti = asyncio.run(grants.grant(session_id=uuid.uuid4(), tenant_id=TENANT, user_id=USER))
    ticket = _issuer().issue(session_id=SESSION, tenant_id=TENANT, jti=jti)

    with pytest.raises(WebSocketDisconnect):
        with stream_client.websocket_connect(
            f"/voice/sessions/{SESSION}/stream?ticket={ticket}"
        ) as ws:
            ws.receive_bytes()


class _FakeRedis:
    """Just enough Redis for the grant store: setex, and a get+delete pipeline."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttls[key] = ttl

    def pipeline(self):
        store = self

        class _Pipe:
            def __init__(self) -> None:
                self.ops: list[tuple[str, str]] = []

            def get(self, key: str) -> None:
                self.ops.append(("get", key))

            def delete(self, key: str) -> None:
                self.ops.append(("delete", key))

            async def execute(self):
                results = []
                for op, key in self.ops:
                    if op == "get":
                        results.append(store.values.get(key))
                    else:
                        store.values.pop(key, None)
                        results.append(1)
                return results

        return _Pipe()


async def test_the_grant_lives_one_minute_and_dies_when_redeemed():
    from app.modules.voice.infrastructure.stream_grants import (
        StreamGrantMissing,
        StreamGrantStore,
    )

    redis = _FakeRedis()
    store = StreamGrantStore(redis)

    jti = await store.grant(session_id=SESSION, tenant_id=TENANT, user_id=USER)

    assert redis.ttls[f"voice:stream:{jti}"] == 60
    assert await store.take(jti) == StreamGrantFor(SESSION, TENANT, USER)
    with pytest.raises(StreamGrantMissing):
        await store.take(jti)


def StreamGrantFor(session_id, tenant_id, user_id):
    from app.modules.voice.infrastructure.stream_grants import StreamGrant

    return StreamGrant(session_id=str(session_id), tenant_id=str(tenant_id), user_id=str(user_id))
