"""Authorization for the staff inbox stream and the send route.

`GET /api/v1/conversations/stream` used to authenticate by JWT signature alone:
no `User.is_active`, no `TenantUser` membership and no `Tenant.lifecycle_state`
check. A deactivated user or a removed member kept a live feed of message bodies
for the whole token lifetime. `_stream_auth` now mirrors
`app.modules.realtime.router._sse_auth`.

`POST /conversations/{id}/messages` was the only mutation in the module that did
not require `conversations:write` — `assign`, `close` and every template route
did. A member without the write permission could send as the tenant.

Two classes of test:

* DB-free (run locally): the stream gate is driven with a fake session factory so
  the three checks are exercised without a database, and the send route is driven
  over a real ASGI app with `get_tenant_ctx` overridden.
* DB-backed (run in CI): the same gates against real rows and real RLS.
"""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from app.core.errors import DomainError, PermissionDeniedError, build_error_body
from app.core.security import create_access_token, hash_password
from app.modules.conversations.router import (
    router as conversations_router,
)
from app.modules.conversations.router import (
    send_message,
    stream_conversations,
)
from app.modules.conversations.service import ConversationService
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant, User


def _request(*, authorization: str | None = None) -> Request:
    """A minimal ASGI scope — enough for `request.headers`."""
    headers = [(b"authorization", authorization.encode())] if authorization else []
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/conversations/stream",
            "raw_path": b"/api/v1/conversations/stream",
            "query_string": b"",
            "headers": headers,
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        }
    )


def _token(user_id: uuid.UUID | None = None, tenant_id: uuid.UUID | None = None) -> str:
    return create_access_token(
        str(user_id or uuid.uuid4()),
        {"tenant_id": str(tenant_id or uuid.uuid4()), "role": "staff"},
    )


# ------------------------------------------------ DB-free stream gate -----
#
# The gate opens its OWN short-lived session, so the test drives it with a
# scripted stand-in instead of a real connection. `execute` keys on the
# statement's table rather than call order, so the test does not depend on the
# exact sequence of the three checks.


class _FakeResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def one_or_none(self):
        # The stream gate reads (is_active, auth_version) as a row since the
        # password-reset revocation check landed — same shape, different read.
        return self._value


class _FakeSession:
    def __init__(self, *, is_active, member, lifecycle_state) -> None:
        self.is_active = is_active
        self.member = member
        self.lifecycle_state = lifecycle_state

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
            # The gate selects a ROW now: (is_active, auth_version). The fake
            # mints the token without an auth_version claim, so 0 matches 0.
            return _FakeResult(
                SimpleNamespace(is_active=self.is_active, auth_version=0)
            )
        return _FakeResult(None)


def _install_fake_sessions(
    monkeypatch, *, is_active: bool, member, lifecycle_state
) -> None:
    def _factory() -> _FakeSession:
        return _FakeSession(
            is_active=is_active, member=member, lifecycle_state=lifecycle_state
        )

    # `SessionLocal` resolves through `app.core.db.__getattr__` -> get_sessionmaker,
    # so patching the factory is enough (same trick as the realtime SSE tests).
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: _factory)


async def test_stream_opens_for_an_active_member(monkeypatch) -> None:
    _install_fake_sessions(
        monkeypatch, is_active=True, member=uuid.uuid4(), lifecycle_state="active"
    )

    response = await stream_conversations(_request(), _token())

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"


async def test_stream_accepts_a_bearer_header(monkeypatch) -> None:
    """EventSource uses ?token=, but a plain Bearer header must work too."""
    _install_fake_sessions(
        monkeypatch, is_active=True, member=uuid.uuid4(), lifecycle_state="active"
    )

    response = await stream_conversations(_request(authorization=f"Bearer {_token()}"), None)

    assert response.status_code == 200


async def test_stream_refuses_a_deactivated_user(monkeypatch) -> None:
    """A user switched off after the token was minted must not keep a feed."""
    _install_fake_sessions(
        monkeypatch, is_active=False, member=uuid.uuid4(), lifecycle_state="active"
    )

    with pytest.raises(PermissionDeniedError) as exc:
        await stream_conversations(_request(), _token())
    assert "inactive" in str(exc.value)


async def test_stream_refuses_a_removed_member(monkeypatch) -> None:
    """An active user who is not a member of the token's tenant is refused."""
    _install_fake_sessions(
        monkeypatch, is_active=True, member=None, lifecycle_state="active"
    )

    with pytest.raises(PermissionDeniedError) as exc:
        await stream_conversations(_request(), _token())
    assert "member" in str(exc.value)


async def test_stream_refuses_a_suspended_workspace(monkeypatch) -> None:
    """§48: a suspended workspace must not keep a live inbox."""
    _install_fake_sessions(
        monkeypatch, is_active=True, member=uuid.uuid4(), lifecycle_state="suspended"
    )

    with pytest.raises(PermissionDeniedError) as exc:
        await stream_conversations(_request(), _token())
    assert "suspended" in str(exc.value)


async def test_stream_refuses_a_token_without_a_tenant(monkeypatch) -> None:
    _install_fake_sessions(
        monkeypatch, is_active=True, member=uuid.uuid4(), lifecycle_state="active"
    )

    token = create_access_token(str(uuid.uuid4()), {"role": "staff"})
    with pytest.raises(PermissionDeniedError):
        await stream_conversations(_request(), token)


# ------------------------------------------------- DB-free send authz -----


def _send_app(permission_codes: set[str]) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _handle(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=build_error_body(exc))

    app.include_router(conversations_router, prefix="/api/v1")
    tenant_id = uuid.uuid4()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=None,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="staff"),
            tenant_id=tenant_id,
            role_code="staff",
            permission_codes=permission_codes,
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


def _stub_message_services(monkeypatch) -> None:
    async def _get(_session, _tenant_id, conversation_id):
        return SimpleNamespace(id=conversation_id, status="open")

    async def _add(_session, _tenant_id, **_kwargs):
        return SimpleNamespace(id=uuid.uuid4(), status="queued")

    async def _outbox(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(ConversationService, "get", _get)
    monkeypatch.setattr(ConversationService, "add_message", _add)
    monkeypatch.setattr("app.core.events.writer.add_outbox_event", _outbox)


def test_send_message_declares_the_write_permission_gate() -> None:
    """The gap WAS the missing dependency; assert it is attached by name."""
    default = inspect.signature(send_message).parameters["ctx"].default
    gate = getattr(default, "dependency", None)
    assert getattr(gate, "code", None) == "conversations:write"


async def test_send_message_is_refused_without_conversations_write(monkeypatch) -> None:
    _stub_message_services(monkeypatch)
    app = _send_app(permission_codes={"conversations:read"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{uuid.uuid4()}/messages", json={"body": "hi"}
        )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "permission_denied"


async def test_send_message_is_allowed_with_conversations_write(monkeypatch) -> None:
    _stub_message_services(monkeypatch)
    app = _send_app(permission_codes={"conversations:write"})

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{uuid.uuid4()}/messages", json={"body": "hi"}
        )

    assert response.status_code == 201, response.text


# ------------------------------------------------------- DB-backed (CI) -----


async def _set_state(db: AsyncSession, tenant_id: uuid.UUID, state: str) -> None:
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    tenant.lifecycle_state = state
    await db.flush()


@pytest.fixture
async def stream_sessions(monkeypatch, db):
    """Point the stream gate's own session factory at the test connection.

    The gate deliberately opens its OWN short-lived session — a request-scoped
    one would pin a pooled connection for the whole stream. That is right in
    production but means it cannot see the `db` fixture's uncommitted rows, so
    bind it to the same connection rather than committing test data into the
    database.
    """
    conn = await db.connection()
    factory = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: factory)
    return factory


async def test_db_stream_opens_for_an_active_member(
    db: AsyncSession, tenant_ctx, stream_sessions
) -> None:
    token = _token(tenant_ctx.user.id, tenant_ctx.tenant_id)

    response = await stream_conversations(_request(), token)

    assert response.status_code == 200


async def test_db_stream_refuses_a_deactivated_user(
    db: AsyncSession, tenant_ctx, stream_sessions
) -> None:
    token = _token(tenant_ctx.user.id, tenant_ctx.tenant_id)
    tenant_ctx.user.is_active = False
    await db.flush()

    with pytest.raises(PermissionDeniedError):
        await stream_conversations(_request(), token)


async def test_db_stream_refuses_a_non_member(
    db: AsyncSession, tenant_ctx, stream_sessions
) -> None:
    stranger = User(
        email=f"stranger-{uuid.uuid4().hex[:10]}@test.local",
        password_hash=hash_password("secret-password"),
        full_name="Not A Member",
    )
    db.add(stranger)
    await db.flush()

    with pytest.raises(PermissionDeniedError) as exc:
        await stream_conversations(_request(), _token(stranger.id, tenant_ctx.tenant_id))
    assert "member" in str(exc.value)


async def test_db_stream_refuses_a_suspended_workspace(
    db: AsyncSession, tenant_ctx, stream_sessions
) -> None:
    """The endpoint's own gate: open while active, refused once suspended."""
    token = _token(tenant_ctx.user.id, tenant_ctx.tenant_id)
    assert (await stream_conversations(_request(), token)).status_code == 200

    await _set_state(db, tenant_ctx.tenant_id, "suspended")

    with pytest.raises(PermissionDeniedError) as exc:
        await stream_conversations(_request(), token)
    assert "suspended" in str(exc.value)
