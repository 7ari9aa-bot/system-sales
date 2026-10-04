"""SEC-1 / ADR-059 R5: the SSE query fallback accepts only stream-scoped tokens.

The exposure was precise: ``?token=`` accepted the 30-minute ACCESS token, so
a live credential sat in server access logs, proxy caches and referrer
headers for as long as it was valid — while the same client (the web app)
already owns a fetch-based stream that sends a Bearer header, making the URL
fallback avoidable for everyone except a browser EventSource, which cannot
send headers.

The narrowing: ``?token=`` accepts ONLY ``type=stream`` — a 5-minute,
tenant-bound credential minted by ``POST /realtime/stream-token``. The
Authorization header path (desktop, tests, the fetch client) is unchanged.

DB-free: the gate is driven with the same scripted session factory the
conversations stream tests use; the mint route is driven over the real ASGI
app with ``get_tenant_ctx`` overridden.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.core.errors import PermissionDeniedError
from app.core.security import create_access_token, create_stream_token
from app.modules.identity.deps import AuthedUser, get_current_user
from app.modules.realtime.router import _sse_auth

USER_ID = uuid.uuid4()
TENANT_ID = uuid.uuid4()


def _request(*, authorization: str | None = None, query_token: str | None = None) -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    query = b"token=" + query_token.encode() if query_token else b""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/realtime/events",
            "raw_path": b"/api/v1/realtime/events",
            "query_string": query,
            "headers": headers,
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        }
    )


class _FakeResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, *, is_active, member, lifecycle_state, auth_version=0) -> None:
        self.is_active = is_active
        self.member = member
        self.lifecycle_state = lifecycle_state
        self.auth_version = auth_version

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    def begin(self) -> _FakeSession:
        return self

    async def execute(self, statement, params=None) -> _FakeResult:
        sql = str(statement)
        if "set_config" in sql:
            return _FakeResult(None)
        if "tenant_users" in sql:
            return _FakeResult(self.member)
        if "lifecycle_state" in sql:
            return _FakeResult(self.lifecycle_state)
        if "is_active" in sql:
            return _FakeResult(
                SimpleNamespace(
                    is_active=self.is_active,
                    auth_version=self.auth_version,
                )
            )
        return _FakeResult(None)


def _install_fake_sessions(monkeypatch, *, auth_version=0) -> None:
    def _factory() -> _FakeSession:
        return _FakeSession(
            is_active=True,
            member=uuid.uuid4(),
            lifecycle_state="active",
            auth_version=auth_version,
        )

    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: _factory)


async def test_an_access_token_in_the_query_string_is_refused(monkeypatch) -> None:
    """The narrowing itself: what the old code accepted, it must now refuse."""
    _install_fake_sessions(monkeypatch)

    access = create_access_token(
        str(USER_ID), {"tenant_id": str(TENANT_ID), "role": "staff"}
    )
    with pytest.raises(PermissionDeniedError) as excinfo:
        await _sse_auth(_request(query_token=access), token=access)
    assert "stream-scoped" in str(excinfo.value)


async def test_a_stream_token_opens_the_fallback(monkeypatch) -> None:
    _install_fake_sessions(monkeypatch)

    stream = create_stream_token(str(USER_ID), str(TENANT_ID))
    user = await _sse_auth(_request(query_token=stream), token=stream)

    assert str(user.id) == str(USER_ID)
    assert str(user.tenant_id) == str(TENANT_ID)


async def test_password_reset_invalidates_pre_reset_stream_tokens(monkeypatch) -> None:
    _install_fake_sessions(monkeypatch, auth_version=1)
    stream = create_stream_token(str(USER_ID), str(TENANT_ID), auth_version=0)
    with pytest.raises(PermissionDeniedError, match="session revoked"):
        await _sse_auth(_request(query_token=stream), token=stream)


async def test_an_expired_stream_token_is_refused(monkeypatch) -> None:
    _install_fake_sessions(monkeypatch)

    expired = create_stream_token(str(USER_ID), str(TENANT_ID), ttl_seconds=-1)
    with pytest.raises(PermissionDeniedError):
        await _sse_auth(_request(query_token=expired), token=expired)


async def test_the_mint_route_binds_the_callers_own_tenant() -> None:
    from app.core.security import decode_token
    from app.modules.realtime.router import router as realtime_router

    app = FastAPI()
    app.include_router(realtime_router, prefix="/api/v1")

    def _fake_user() -> AuthedUser:
        return AuthedUser(id=USER_ID, tenant_id=TENANT_ID, role_code="staff")

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            response = await client.post("/api/v1/realtime/stream-token")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    payload = decode_token(body["stream_token"])
    assert payload["type"] == "stream"
    assert payload["sub"] == str(USER_ID)
    assert payload["tenant_id"] == str(TENANT_ID)
    assert payload["auth_version"] == 0
    assert body["expires_in"] == 300
