"""Messenger must understand every event Meta sends for a Page, not only plain text.

The adapter used to read ``event.message`` and nothing else, so button taps, ad/link referrals,
reactions, receipts, echoes and thread-control handovers were silently dropped, an album lost every
attachment but the first, and a person's reply after the 24h window went out without the
HUMAN_AGENT tag Meta requires.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.modules.conversations.gateway.messenger import messenger_adapter

PAGE = "PAGE-1"
USER = "PSID-9"


def _envelope(*events: dict) -> dict:
    return {"object": "page", "entry": [{"id": PAGE, "messaging": list(events)}]}


def _evt(**body) -> dict:
    return {"sender": {"id": USER}, "recipient": {"id": PAGE}, "timestamp": 1700000000000, **body}


# ---------------------------------------------------------------- inbound events


def test_a_button_tap_becomes_a_message_with_a_stable_id() -> None:
    payload = _envelope(_evt(postback={"title": "Track order", "payload": "TRACK"}))
    [msg] = messenger_adapter.parse_inbound(payload)
    assert msg.body == "Track order"
    assert msg.content_type == "text"
    assert msg.customer_ref == USER
    # a redelivered tap is the SAME id, so it cannot be stored twice
    [again] = messenger_adapter.parse_inbound(payload)
    assert msg.channel_message_id == again.channel_message_id
    assert msg.channel_message_id.startswith("postback:")


def test_a_referral_is_kept_with_its_ad_id() -> None:
    payload = _envelope(_evt(referral={"source": "ADS", "type": "OPEN_THREAD", "ad_id": "AD-7"}))
    [msg] = messenger_adapter.parse_inbound(payload)
    assert "AD-7" in (msg.body or "")
    assert msg.raw["_messenger"]["referral"]["ad_id"] == "AD-7"


def test_a_reaction_has_a_deterministic_id_never_none() -> None:
    payload = _envelope(_evt(reaction={"mid": "m.out", "action": "react", "emoji": "\u2764"}))
    [msg] = messenger_adapter.parse_inbound(payload)
    assert msg.content_type == "reaction"
    assert msg.reply_to_message_id == "m.out"
    assert msg.channel_message_id  # idempotency key present
    [again] = messenger_adapter.parse_inbound(payload)
    assert again.channel_message_id == msg.channel_message_id


def test_an_unreact_is_not_confused_with_the_reaction() -> None:
    react = _envelope(_evt(reaction={"mid": "m.out", "action": "react", "emoji": "\u2764"}))
    unreact = _envelope(_evt(reaction={"mid": "m.out", "action": "unreact"}))
    [a] = messenger_adapter.parse_inbound(react)
    [b] = messenger_adapter.parse_inbound(unreact)
    assert a.channel_message_id != b.channel_message_id


def test_an_album_keeps_every_attachment() -> None:
    att = lambda n: {"type": "image", "payload": {"url": f"https://cdn/{n}.jpg"}}  # noqa: E731
    payload = _envelope(
        _evt(message={"mid": "m1", "text": "look", "attachments": [att(1), att(2), att(3)]})
    )
    msgs = messenger_adapter.parse_inbound(payload)
    assert [m.media_url for m in msgs] == [f"https://cdn/{n}.jpg" for n in (1, 2, 3)]
    # first keeps the real id and caption; the rest get stable suffixed ids and no caption
    assert [m.channel_message_id for m in msgs] == ["m1", "m1#1", "m1#2"]
    assert [m.body for m in msgs] == ["look", None, None]


def test_our_own_echo_is_not_an_inbound_message() -> None:
    payload = _envelope(
        {
            "sender": {"id": PAGE},
            "recipient": {"id": USER},
            "message": {"mid": "m.echo", "is_echo": True, "text": "hi", "app_id": 123},
        }
    )
    assert messenger_adapter.parse_inbound(payload) == []
    [echo] = messenger_adapter.parse_echoes(payload)
    assert echo["customer_ref"] == USER
    assert echo["mid"] == "m.echo"
    assert echo["app_id"] == 123


def test_a_plain_text_message_still_parses() -> None:
    [msg] = messenger_adapter.parse_inbound(_envelope(_evt(message={"mid": "m1", "text": "hello"})))
    assert (msg.body, msg.channel_message_id, msg.content_type) == ("hello", "m1", "text")


# ---------------------------------------------------------------- receipts


def test_delivery_receipts_become_delivered_status_updates() -> None:
    payload = _envelope(_evt(delivery={"mids": ["m.a", "m.b"], "watermark": 1700000000500}))
    updates = messenger_adapter.parse_status_updates(payload)
    assert [(u.channel_message_id, u.status) for u in updates] == [
        ("m.a", "delivered"),
        ("m.b", "delivered"),
    ]


def test_a_read_receipt_is_a_watermark_not_a_message_id() -> None:
    payload = _envelope(_evt(read={"watermark": 1700000000900}))
    assert messenger_adapter.parse_status_updates(payload) == []
    assert messenger_adapter.parse_read_watermarks(payload) == [
        {"customer_ref": USER, "watermark": 1700000000900}
    ]


def test_receipts_are_not_inbound_messages() -> None:
    payload = _envelope(_evt(delivery={"mids": ["m.a"]}), _evt(read={"watermark": 1}))
    assert messenger_adapter.parse_inbound(payload) == []


# ---------------------------------------------------------------- handovers


def test_thread_control_events_are_reported_with_their_reason() -> None:
    payload = _envelope(
        _evt(
            pass_thread_control={
                "new_owner_app_id": "META-BUSINESS-AI",
                "previous_owner_app_id": "OURS",
                "handoff_reason": "needs_human",
                "metadata": "x",
            }
        )
    )
    [handover] = messenger_adapter.parse_handovers(payload)
    assert handover["event"] == "pass_thread_control"
    assert handover["reason"] == "needs_human"
    assert handover["new_owner_app_id"] == "META-BUSINESS-AI"
    assert messenger_adapter.parse_inbound(payload) == []


# ---------------------------------------------------------------- sending


def _client(sent: list) -> httpx.AsyncClient:
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"message_id": "mid.out"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _msg(**meta) -> OutboundMessage:
    import uuid

    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref=USER,
        body="hello",
        meta=meta,
    )


CREDS = ProviderCredentials(config={"api_key": "PAGE-TOKEN"})


@pytest.mark.asyncio
async def test_a_human_reply_after_24h_carries_the_human_agent_tag() -> None:
    sent: list = []
    await messenger_adapter.send(CREDS, _msg(human_agent=True), _client=_client(sent))
    assert sent[0]["messaging_type"] == "MESSAGE_TAG"
    assert sent[0]["tag"] == "HUMAN_AGENT"


@pytest.mark.asyncio
async def test_an_ordinary_reply_carries_no_tag() -> None:
    sent: list = []
    await messenger_adapter.send(CREDS, _msg(), _client=_client(sent))
    assert "tag" not in sent[0]
    assert sent[0].get("messaging_type") in (None, "RESPONSE")


@pytest.mark.asyncio
async def test_the_tag_is_on_every_part_of_a_file_with_a_caption() -> None:
    sent: list = []
    message = _msg(human_agent=True, media_type="image")
    message.media_url = "https://cdn/x.jpg"
    await messenger_adapter.send(CREDS, message, _client=_client(sent))
    assert len(sent) == 2
    assert all(p["tag"] == "HUMAN_AGENT" for p in sent)
