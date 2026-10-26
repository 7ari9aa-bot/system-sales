"""Sending an inbox reply honours ``Idempotency-Key`` (a retry must not message the customer twice).

An agent presses Send, the connection stalls AFTER the server stored the message and
queued it for delivery, the client times out and the agent presses Send again. Without
a replay guard the second request is a second message: the customer receives the same
reply twice on WhatsApp / Telegram.

``/api/v1/conversations`` is on ``IDEMPOTENT_PATHS`` ("send message, assign, close") but
nothing exercised it for the send route, and the dashboard never sent the header, so the
guard protected nobody. These tests mount the REAL inbox router behind the REAL
middleware (same pattern as ``test_pos_idempotency.py``) and fail if the route stops
being retry-safe.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.errors import DomainError, build_error_body
from app.core.idempotency import IDEMPOTENT_PATHS, IdempotencyMiddleware
from app.modules.conversations.routers import inbox as inbox_router_module
from app.modules.conversations.routers.inbox import router as inbox_router
from app.modules.conversations.service import ConversationService
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from tests.test_order_idempotency import MemoryStore

KEY_HEADER = "Idempotency-Key"
CONVERSATION = uuid.UUID("66666666-6666-6666-6666-666666666666")
OTHER_CONVERSATION = uuid.UUID("77777777-7777-7777-7777-777777777777")
PATH = f"/api/v1/conversations/{CONVERSATION}/messages"


def _build_app(store: Any, tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=build_error_body(exc))

    app.include_router(inbox_router, prefix="/api/v1")
    app.add_middleware(IdempotencyMiddleware, store=store)

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=None,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="owner"),
            tenant_id=tenant_id,
            role_code="owner",
            permission_codes={"conversations:write", "conversations:read"},
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


def _install_fakes(monkeypatch) -> dict[str, list]:
    """Stub the service + outbox so we count real side effects without a database."""
    seen: dict[str, list] = {"messages": [], "outbox": []}

    async def fake_get(session, tenant_id, conversation_id):
        return SimpleNamespace(id=conversation_id, status="open")

    async def fake_add_message(session, tenant_id, **kwargs):
        seen["messages"].append(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), status="queued")

    async def fake_outbox(session, **kwargs):
        seen["outbox"].append(kwargs)

    monkeypatch.setattr(ConversationService, "get", staticmethod(fake_get))
    monkeypatch.setattr(ConversationService, "add_message", staticmethod(fake_add_message))
    # send_message imports add_outbox_event inside the function from this module.
    import app.core.events.writer as writer

    monkeypatch.setattr(writer, "add_outbox_event", fake_outbox)
    assert inbox_router_module  # the router under test is the real one
    return seen


def test_conversations_is_on_the_idempotency_allow_list() -> None:
    """The guard is opt-in by path: a route not on the list is unprotected."""
    assert any(
        p.rstrip("/") == "/api/v1/conversations" or "/api/v1/conversations".startswith(p)
        for p in IDEMPOTENT_PATHS
    ), "inbox send/assign/close are not retry-safe"


async def test_a_retried_send_messages_the_customer_once(monkeypatch) -> None:
    seen = _install_fakes(monkeypatch)
    app = _build_app(MemoryStore(), uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        first = await client.post(PATH, json={"body": "hello"}, headers={KEY_HEADER: "msg-1"})
        second = await client.post(PATH, json={"body": "hello"}, headers={KEY_HEADER: "msg-1"})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json(), "a retry must return the FIRST message"
    assert second.headers.get("idempotency-replayed") == "true"
    assert len(seen["messages"]) == 1, "the customer must receive the reply once"
    assert len(seen["outbox"]) == 1, "the provider send must be queued once"


async def test_reusing_a_key_for_different_text_is_refused(monkeypatch) -> None:
    """Edited text is a new intention; the dashboard must mint a new key for it."""
    seen = _install_fakes(monkeypatch)
    app = _build_app(MemoryStore(), uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        await client.post(PATH, json={"body": "hello"}, headers={KEY_HEADER: "msg-2"})
        conflict = await client.post(
            PATH, json={"body": "hello there"}, headers={KEY_HEADER: "msg-2"}
        )

    assert conflict.status_code == 409, conflict.text
    assert len(seen["messages"]) == 1


async def test_the_same_key_on_another_conversation_is_independent(monkeypatch) -> None:
    seen = _install_fakes(monkeypatch)
    app = _build_app(MemoryStore(), uuid.uuid4())
    other = f"/api/v1/conversations/{OTHER_CONVERSATION}/messages"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        a = await client.post(PATH, json={"body": "hi"}, headers={KEY_HEADER: "same"})
        b = await client.post(other, json={"body": "hi"}, headers={KEY_HEADER: "same"})

    assert a.status_code == b.status_code == 201
    assert len(seen["messages"]) == 2, "keys are scoped per route, not global"


async def test_send_without_a_key_keeps_the_old_behaviour(monkeypatch) -> None:
    """Opt-in: clients that send no key are unchanged."""
    seen = _install_fakes(monkeypatch)
    app = _build_app(MemoryStore(), uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        await client.post(PATH, json={"body": "hello"})
        await client.post(PATH, json={"body": "hello"})

    assert len(seen["messages"]) == 2


async def test_a_rejected_send_releases_the_key(monkeypatch) -> None:
    """A 4xx means nothing ran, so the agent can fix the request and reuse the key."""
    seen = _install_fakes(monkeypatch)
    app = _build_app(MemoryStore(), uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        bad = await client.post(
            PATH, json={}, headers={KEY_HEADER: "msg-3"}
        )  # no body, no template
        good = await client.post(PATH, json={"body": "fixed"}, headers={KEY_HEADER: "msg-3"})

    assert bad.status_code in (400, 422), bad.text
    assert good.status_code == 201, good.text
    assert len(seen["messages"]) == 1
