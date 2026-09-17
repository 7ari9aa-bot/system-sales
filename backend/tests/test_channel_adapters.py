"""Channel adapter tests — WhatsApp & Telegram normalization, signatures, sends."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.modules.conversations.gateway.telegram import telegram_adapter
from app.modules.conversations.gateway.whatsapp import whatsapp_adapter


def _wa_payload() -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "PNID123"},
                            "contacts": [
                                {"wa_id": "201234567890", "profile": {"name": "أحمد"}}
                            ],
                            "messages": [
                                {
                                    "id": "wamid.abc123",
                                    "from": "201234567890",
                                    "type": "text",
                                    "text": {"body": "السلام عليكم"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_whatsapp_parse_inbound_normalizes():
    messages = whatsapp_adapter.parse_inbound(_wa_payload())
    assert len(messages) == 1
    m = messages[0]
    assert m.channel == "whatsapp"
    assert m.channel_message_id == "wamid.abc123"
    assert m.customer_ref == "201234567890"
    assert m.customer_name == "أحمد"
    assert m.body == "السلام عليكم"


def test_whatsapp_resolve_tenant_key():
    assert whatsapp_adapter.resolve_tenant_key(_wa_payload()) == "PNID123"
    assert whatsapp_adapter.resolve_tenant_key({}) is None


def test_whatsapp_signature_check(monkeypatch):
    secret = "test-secret"
    monkeypatch.setattr(
        "app.modules.conversations.gateway.whatsapp.get_settings",
        lambda: type(
            "S",
            (),
            {"whatsapp_app_secret": secret, "whatsapp_verify_token": "tok"},
        )(),
    )
    raw = json.dumps(_wa_payload()).encode()
    good = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert whatsapp_adapter.check_signature({"x-hub-signature-256": good}, raw)
    assert not whatsapp_adapter.check_signature({"x-hub-signature-256": "sha256=bad"}, raw)
    assert not whatsapp_adapter.check_signature({}, raw)


def test_whatsapp_verify_handshake(monkeypatch):
    monkeypatch.setattr(
        "app.modules.conversations.gateway.whatsapp.get_settings",
        lambda: type("S", (), {"whatsapp_app_secret": "", "whatsapp_verify_token": "tok"})(),
    )
    challenge = whatsapp_adapter.verify_request(
        {"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "CH123"}
    )
    assert challenge == "CH123"
    assert (
        whatsapp_adapter.verify_request({"hub.mode": "subscribe", "hub.verify_token": "x"})
        is None
    )


def test_whatsapp_parse_status_updates():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": "wamid.abc123", "status": "delivered"},
                                {
                                    "id": "wamid.err",
                                    "status": "failed",
                                    "errors": [{"message": "phone not on whatsapp"}],
                                },
                            ]
                        }
                    }
                ]
            }
        ]
    }
    updates = whatsapp_adapter.parse_status_updates(payload)
    assert updates[0].status == "delivered"
    assert updates[1].status == "failed"
    assert updates[1].error == "phone not on whatsapp"


async def test_whatsapp_send_text_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["Authorization"]
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.out1"}]})

    transport = httpx.MockTransport(handler)
    message = OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="201234567890",
        body="أهلاً",
    )
    provider_id = await whatsapp_adapter.send(
        ProviderCredentials(config={"phone_number_id": "PNID123", "access_token": "TK"}),
        message,
        _client=httpx.AsyncClient(transport=transport),
    )
    assert provider_id == "wamid.out1"
    assert captured["url"].endswith("/PNID123/messages")
    assert captured["auth"] == "Bearer TK"
    assert captured["json"]["type"] == "text"
    assert captured["json"]["text"]["body"] == "أهلاً"


async def test_whatsapp_send_template_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.t1"}]})

    message = OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="201234567890",
        template_name="order_confirmation",
        template_vars={"language_code": "ar", "body_params": ["ORD-1", "250 EGP"]},
    )
    await whatsapp_adapter.send(
        ProviderCredentials(config={"phone_number_id": "P", "access_token": "T"}),
        message,
        _client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert captured["json"]["type"] == "template"
    assert captured["json"]["template"]["name"] == "order_confirmation"


async def test_whatsapp_send_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad phone"}})

    with pytest.raises(ExternalProviderError):
        await whatsapp_adapter.send(
            ProviderCredentials(config={"phone_number_id": "P", "access_token": "T"}),
            OutboundMessage(
                tenant_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                message_id=uuid.uuid4(),
                customer_ref="x",
                body="hi",
            ),
            _client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )


async def test_telegram_send_and_parse():
    payload = {
        "message": {
            "message_id": 42,
            "chat": {"id": 555, "first_name": "Sara"},
            "from": {"first_name": "Sara"},
            "text": "مرحبا",
        }
    }
    messages = telegram_adapter.parse_inbound(payload)
    assert messages[0].customer_ref == "555"
    assert messages[0].body == "مرحبا"
    assert telegram_adapter.resolve_tenant_key({"_query": {"tenant_key": "pk1"}}) == "pk1"

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    provider_id = await telegram_adapter.send(
        ProviderCredentials(config={"bot_token": "BOT"}),
        OutboundMessage(
            tenant_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            customer_ref="555",
            body="رد",
        ),
        _client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert provider_id == "77"
    assert "/botBOT/sendMessage" in captured["url"]
