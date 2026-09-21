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


def _wa_payload_with_messages(messages: list[dict]) -> dict:
    """A WhatsApp webhook envelope carrying the given messages verbatim."""
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
                            "messages": messages,
                        }
                    }
                ]
            }
        ]
    }


def _wa_payload() -> dict:
    return _wa_payload_with_messages(
        [
            {
                "id": "wamid.abc123",
                "from": "201234567890",
                "type": "text",
                "text": {"body": "السلام عليكم"},
            }
        ]
    )


def test_whatsapp_parse_inbound_normalizes():
    messages = whatsapp_adapter.parse_inbound(_wa_payload())
    assert len(messages) == 1
    m = messages[0]
    assert m.channel == "whatsapp"
    assert m.channel_message_id == "wamid.abc123"
    assert m.customer_ref == "201234567890"
    assert m.customer_name == "أحمد"
    assert m.body == "السلام عليكم"
    assert m.content_type == "text"


def test_whatsapp_media_payloads_map_to_canonical_content_types():
    """§155: media never degrades to plain text — the canonical content_type
    column is what every surface reads."""
    messages = whatsapp_adapter.parse_inbound(
        _wa_payload_with_messages(
            [
                {
                    "id": "wamid.img",
                    "from": "201234567890",
                    "type": "image",
                    "image": {"link": "https://cdn.example/img.jpg"},
                    "caption": "صورة المنتج",
                },
                {
                    "id": "wamid.aud",
                    "from": "201234567890",
                    "type": "audio",
                    "audio": {"link": "https://cdn.example/voice.ogg"},
                },
                {
                    "id": "wamid.vid",
                    "from": "201234567890",
                    "type": "video",
                    "video": {"link": "https://cdn.example/clip.mp4"},
                },
                {
                    "id": "wamid.doc",
                    "from": "201234567890",
                    "type": "document",
                    "document": {"link": "https://cdn.example/offer.pdf"},
                },
            ]
        )
    )
    by_id = {m.channel_message_id: m for m in messages}
    image = by_id["wamid.img"]
    assert image.content_type == "image"
    assert image.media_type == "image"
    assert image.media_url == "https://cdn.example/img.jpg"
    assert image.body == "صورة المنتج"  # caption kept as body
    voice = by_id["wamid.aud"]
    # WhatsApp voice notes arrive as type "audio" — canonically they are voice.
    assert voice.content_type == "voice"
    assert voice.media_type == "audio"
    assert by_id["wamid.vid"].content_type == "video"
    document = by_id["wamid.doc"]
    assert document.content_type == "file"
    assert document.media_type == "document"


def test_whatsapp_location_contact_buttons_list_and_reaction_types():
    """§155: structured payloads keep their canonical kind, and a reaction
    threads to the message it reacts to."""
    messages = whatsapp_adapter.parse_inbound(
        _wa_payload_with_messages(
            [
                {
                    "id": "wamid.loc",
                    "from": "201234567890",
                    "type": "location",
                    "location": {"name": "المكتب", "address": "القاهرة"},
                },
                {
                    "id": "wamid.con",
                    "from": "201234567890",
                    "type": "contacts",
                    "contacts": [
                        {
                            "name": {"formatted_name": "سارة"},
                            "phones": [{"phone": "+201111111111"}],
                        }
                    ],
                },
                {
                    "id": "wamid.btn",
                    "from": "201234567890",
                    "type": "button",
                    "button": {"text": "تأكيد الطلب", "payload": "PAY-1"},
                },
                {
                    "id": "wamid.itr",
                    "from": "201234567890",
                    "type": "interactive",
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": "opt-2", "title": "شحن سريع"},
                    },
                },
                {
                    "id": "wamid.rea",
                    "from": "201234567890",
                    "type": "reaction",
                    "reaction": {"emoji": "👍", "message_id": "wamid.orig"},
                    "context": {"id": "wamid.orig"},
                },
                {
                    "id": "wamid.unk",
                    "from": "201234567890",
                    "type": "order",
                    "order": {"catalog_id": "c1"},
                },
            ]
        )
    )
    by_id = {m.channel_message_id: m for m in messages}
    location = by_id["wamid.loc"]
    assert location.content_type == "location"
    assert "المكتب" in (location.body or "")
    contact = by_id["wamid.con"]
    assert contact.content_type == "contact"
    assert "سارة" in (contact.body or "")
    assert by_id["wamid.btn"].content_type == "buttons"
    assert by_id["wamid.itr"].content_type == "list"
    assert by_id["wamid.itr"].body == "شحن سريع"
    reaction = by_id["wamid.rea"]
    assert reaction.content_type == "reaction"
    assert reaction.body == "👍"
    assert reaction.reply_to_message_id == "wamid.orig"
    assert by_id["wamid.unk"].content_type == "unsupported"


def test_whatsapp_reply_context_sets_reply_to_message_id():
    """§155 threading: context.id (the quoted wamid) rides on the message."""
    messages = whatsapp_adapter.parse_inbound(
        _wa_payload_with_messages(
            [
                {
                    "id": "wamid.reply",
                    "from": "201234567890",
                    "type": "text",
                    "text": {"body": "شكراً"},
                    "context": {"id": "wamid.orig", "from": "201234567890"},
                }
            ]
        )
    )
    assert messages[0].reply_to_message_id == "wamid.orig"


def test_whatsapp_interactive_button_reply_is_buttons_and_threads():
    messages = whatsapp_adapter.parse_inbound(
        _wa_payload_with_messages(
            [
                {
                    "id": "wamid.itrbtn",
                    "from": "201234567890",
                    "type": "interactive",
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": "b-1", "title": "تم"},
                    },
                    "context": {"id": "wamid.template-msg"},
                }
            ]
        )
    )
    assert messages[0].content_type == "buttons"
    assert messages[0].reply_to_message_id == "wamid.template-msg"


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
    assert messages[0].content_type == "text"
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


def test_telegram_media_payloads_map_to_canonical_content_types():
    """§155: photo/voice/document/video updates set the canonical kind, and a
    reply threads to the provider message it answers."""
    messages = telegram_adapter.parse_inbound(
        {
            "message": {
                "message_id": 7,
                "chat": {"id": 555},
                "from": {"first_name": "Sara"},
                "photo": [{"file_id": "f1"}],
                "caption": "غلاف الطلب",
                "reply_to_message": {"message_id": 3},
            }
        }
    )
    photo = messages[0]
    assert photo.content_type == "image"
    assert photo.media_url == "telegram:photo"
    assert photo.body == "غلاف الطلب"
    assert photo.reply_to_message_id == "3"

    voice = telegram_adapter.parse_inbound(
        {"message": {"message_id": 8, "chat": {"id": 555}, "voice": {"file_id": "v1"}}}
    )[0]
    assert voice.content_type == "voice"
    assert voice.media_url == "telegram:voice"

    document = telegram_adapter.parse_inbound(
        {
            "message": {
                "message_id": 9,
                "chat": {"id": 555},
                "document": {"file_id": "d1", "file_name": "invoice.pdf"},
            }
        }
    )[0]
    assert document.content_type == "file"
    assert document.media_url == "telegram:document"

    video = telegram_adapter.parse_inbound(
        {"message": {"message_id": 10, "chat": {"id": 555}, "video": {"file_id": "vv"}}}
    )[0]
    assert video.content_type == "video"

    # An animation update also carries a `document` field — animation wins.
    animation = telegram_adapter.parse_inbound(
        {
            "message": {
                "message_id": 11,
                "chat": {"id": 555},
                "animation": {"file_id": "a1"},
                "document": {"file_id": "a1"},
            }
        }
    )[0]
    assert animation.content_type == "video"
    assert animation.media_url == "telegram:animation"
