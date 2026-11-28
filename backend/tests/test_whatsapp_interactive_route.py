"""POST /conversations/{id}/messages with an ``interactive`` body, through the REAL route.

The builder's limits are pinned in test_whatsapp_interactive.py. This file pins what the ROUTE
does with them: WhatsApp only, nothing else beside it, a bad field refused BEFORE anything is
stored or queued, and the stored message holding both the spec (what Meta gets) and a readable
text (what the thread, search and exports show).
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
from app.applications.apparel.modules.conversations.routers.inbox import router as inbox_router
from app.applications.apparel.modules.conversations.service import ConversationService
from app.platform.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

CONVERSATION = uuid.UUID("88888888-8888-8888-8888-888888888888")
PATH = f"/api/v1/conversations/{CONVERSATION}/messages"

BUTTONS = {
    "kind": "buttons",
    "body": "Confirm your order?",
    "buttons": [{"id": "yes", "title": "Confirm"}, {"id": "no", "title": "Cancel"}],
}


def _app() -> FastAPI:
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=build_error_body(exc))

    app.include_router(inbox_router, prefix="/api/v1")
    tenant_id = uuid.uuid4()

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


def _install(monkeypatch, channel: str) -> dict[str, list]:
    seen: dict[str, list] = {"messages": [], "outbox": []}

    async def fake_get(session, tenant_id, conversation_id):
        return SimpleNamespace(id=conversation_id, status="open", channel=channel)

    async def fake_add_message(session, tenant_id, **kwargs):
        seen["messages"].append(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), status="queued")

    async def fake_outbox(session, **kwargs):
        seen["outbox"].append(kwargs)

    monkeypatch.setattr(ConversationService, "get", staticmethod(fake_get))
    monkeypatch.setattr(ConversationService, "add_message", staticmethod(fake_add_message))
    import app.core.events.writer as writer

    monkeypatch.setattr(writer, "add_outbox_event", fake_outbox)
    return seen


async def _post(payload: dict[str, Any]):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as client:
        return await client.post(PATH, json=payload)


async def test_a_whatsapp_conversation_stores_the_spec_and_a_readable_text(monkeypatch) -> None:
    seen = _install(monkeypatch, "whatsapp")
    response = await _post({"interactive": BUTTONS})
    assert response.status_code == 201, response.text
    (stored,) = seen["messages"]
    assert stored["content_type"] == "interactive"
    assert stored["provider_metadata"] == {"interactive": BUTTONS}
    assert stored["body"] == "Confirm your order?\n[ Confirm ]\n[ Cancel ]"
    assert stored["template_name"] is None
    assert len(seen["outbox"]) == 1, "it must be queued for delivery exactly once"


@pytest.mark.parametrize("channel", ["instagram", "messenger", "facebook", "telegram", "webchat"])
async def test_every_other_channel_refuses_it_and_stores_nothing(monkeypatch, channel) -> None:
    seen = _install(monkeypatch, channel)
    response = await _post({"interactive": BUTTONS})
    assert response.status_code == 400, response.text
    assert "WhatsApp" in response.text
    assert seen["messages"] == [] and seen["outbox"] == []


@pytest.mark.parametrize(
    "extra",
    [
        {"template_name": "order_update"},
        {"media_id": str(uuid.uuid4())},
        {"instagram_heart": True},
        {"instagram_quick_replies": ["Yes"]},
    ],
)
async def test_it_cannot_be_combined_with_anything_else(monkeypatch, extra) -> None:
    seen = _install(monkeypatch, "whatsapp")
    response = await _post({"interactive": BUTTONS, **extra})
    assert response.status_code == 400, response.text
    assert seen["messages"] == [] and seen["outbox"] == []


async def test_text_beside_it_is_refused_not_silently_dropped(monkeypatch) -> None:
    seen = _install(monkeypatch, "whatsapp")
    response = await _post({"interactive": BUTTONS, "body": "ignored?"})
    assert response.status_code == 400, response.text
    assert "inside the interactive message" in response.text
    assert seen["messages"] == []


@pytest.mark.parametrize(
    ("spec", "field"),
    [
        ({**BUTTONS, "body": ""}, "body"),
        ({**BUTTONS, "buttons": [{"id": "a", "title": "x" * 21}]}, "buttons[0].title"),
        ({"kind": "list", "body": "b", "button": "Go", "sections": []}, "sections"),
        ({"kind": "cta_url", "body": "b", "label": "Go", "url": "javascript:x"}, "url"),
        ({"kind": "carousel", "body": "b"}, "kind"),
    ],
)
async def test_a_bad_spec_is_refused_naming_the_field_before_anything_is_stored(
    monkeypatch, spec, field
) -> None:
    seen = _install(monkeypatch, "whatsapp")
    response = await _post({"interactive": spec})
    assert response.status_code == 400, response.text
    assert field in response.text
    assert seen["messages"] == [] and seen["outbox"] == []


async def test_an_empty_interactive_object_is_not_a_message(monkeypatch) -> None:
    seen = _install(monkeypatch, "whatsapp")
    response = await _post({"interactive": {}})
    assert response.status_code == 400, response.text
    assert seen["messages"] == []


async def test_an_empty_interactive_object_beside_text_is_refused_not_sent_as_text(
    monkeypatch,
) -> None:
    """A client that built an empty spec by mistake must hear about it, not send plain text."""
    seen = _install(monkeypatch, "whatsapp")
    response = await _post({"interactive": {}, "body": "hello"})
    assert response.status_code == 400, response.text
    assert seen["messages"] == [] and seen["outbox"] == []


async def test_a_plain_text_message_is_unchanged(monkeypatch) -> None:
    seen = _install(monkeypatch, "whatsapp")
    response = await _post({"body": "hello"})
    assert response.status_code == 201, response.text
    (stored,) = seen["messages"]
    assert stored["body"] == "hello"
    assert "content_type" not in stored and "provider_metadata" not in stored


# ------------------------------------------------------------------ what the thread gets back


def _row(meta, direction="outbound"):
    return SimpleNamespace(provider_metadata=meta, direction=direction)


def test_the_thread_gets_the_checked_message_to_draw():
    from app.applications.apparel.modules.conversations.gateway.whatsapp_interactive import build_interactive
    from app.applications.apparel.modules.conversations.routers.inbox import _present_interactive

    assert _present_interactive(_row({"interactive": BUTTONS})) == build_interactive(BUTTONS)


def test_the_thread_never_gets_the_stored_dict_as_is():
    from app.applications.apparel.modules.conversations.routers.inbox import _present_interactive

    shown = _present_interactive(_row({"interactive": {**BUTTONS, "internal_note": "secret"}}))
    assert "internal_note" not in shown and "kind" not in shown


def test_a_spec_that_no_longer_passes_shows_plain_text_not_an_error():
    from app.applications.apparel.modules.conversations.routers.inbox import _present_interactive

    assert _present_interactive(_row({"interactive": {**BUTTONS, "body": ""}})) is None


@pytest.mark.parametrize("meta", [None, {}, {"interactive": None}, {"interactive": {}}])
def test_a_message_without_one_has_none(meta):
    from app.applications.apparel.modules.conversations.routers.inbox import _present_interactive

    assert _present_interactive(_row(meta)) is None


def test_a_customers_message_never_carries_one():
    from app.applications.apparel.modules.conversations.routers.inbox import _present_interactive

    assert _present_interactive(_row({"interactive": BUTTONS}, direction="inbound")) is None
