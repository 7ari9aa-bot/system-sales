"""The heart button: Instagram's heart sticker, sent from an empty message box.

It is its own kind of send (no text, no file), only on Instagram, and it must reach the
provider as ``like_heart`` while the thread keeps showing a heart.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.errors import DomainError, build_error_body
from app.modules.conversations.gateway.base import OutboundMessage
from app.modules.conversations.gateway.instagram import InstagramAdapter
from app.modules.conversations.routers.inbox import router as inbox_router
from app.modules.conversations.service import ConversationService
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

CONVERSATION = uuid.UUID("66666666-6666-6666-6666-666666666666")
PATH = f"/api/v1/conversations/{CONVERSATION}/messages"


def _app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=build_error_body(exc))

    app.include_router(inbox_router, prefix="/api/v1")
    tenant = uuid.uuid4()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=None,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant, role_code="owner"),
            tenant_id=tenant,
            role_code="owner",
            permission_codes={"conversations:write", "conversations:read"},
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


def _fakes(monkeypatch, channel: str) -> dict[str, list]:
    seen: dict[str, list] = {"messages": []}

    async def fake_get(session, tenant_id, conversation_id):
        return SimpleNamespace(id=conversation_id, status="open", channel=channel)

    async def fake_add_message(session, tenant_id, **kwargs):
        seen["messages"].append(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), status="queued")

    async def fake_outbox(session, **kwargs):
        return None

    monkeypatch.setattr(ConversationService, "get", staticmethod(fake_get))
    monkeypatch.setattr(ConversationService, "add_message", staticmethod(fake_add_message))
    import app.core.events.writer as writer

    monkeypatch.setattr(writer, "add_outbox_event", fake_outbox)
    # channel access/send checks are not what this file is about
    from app.modules.conversations.routers import inbox as inbox_module

    async def _ok(ctx: Any, conversation: Any) -> None:
        return None

    monkeypatch.setattr(inbox_module, "_ensure_channel_access", _ok)
    monkeypatch.setattr(inbox_module, "_ensure_channel_send", _ok)
    return seen


async def _post(body: dict) -> Any:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        return await c.post(PATH, json=body)


async def test_a_heart_is_stored_as_a_heart_and_marked(monkeypatch) -> None:
    seen = _fakes(monkeypatch, "instagram")
    r = await _post({"heart": True})
    assert r.status_code == 201, r.text
    sent = seen["messages"][0]
    assert sent["body"] == "\u2764\ufe0f"
    assert sent["provider_metadata"] == {"like_heart": True}


@pytest.mark.parametrize("channel", ["whatsapp", "messenger", "telegram"])
async def test_a_heart_is_refused_off_instagram(monkeypatch, channel) -> None:
    seen = _fakes(monkeypatch, channel)
    r = await _post({"heart": True})
    assert r.status_code == 400, r.text
    assert seen["messages"] == []


@pytest.mark.parametrize("extra", [{"body": "hi"}, {"template_name": "t"}, {"media_id": str(uuid.uuid4())}])
async def test_a_heart_is_sent_alone(monkeypatch, extra) -> None:
    seen = _fakes(monkeypatch, "instagram")
    r = await _post({"heart": True, **extra})
    assert r.status_code == 400, r.text
    assert seen["messages"] == []


async def test_an_ordinary_message_is_unchanged(monkeypatch) -> None:
    seen = _fakes(monkeypatch, "instagram")
    r = await _post({"body": "hello"})
    assert r.status_code == 201, r.text
    assert seen["messages"][0]["body"] == "hello"
    assert "provider_metadata" not in seen["messages"][0]


async def test_an_empty_send_is_still_refused(monkeypatch) -> None:
    _fakes(monkeypatch, "instagram")
    assert (await _post({})).status_code == 400


def test_the_provider_receives_the_heart_sticker() -> None:
    out = OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="igsid",
        body="\u2764\ufe0f",
        meta={"like_heart": True},
    )
    assert InstagramAdapter.build_send_payload(out)["message"] == {"attachment": {"type": "like_heart"}}
