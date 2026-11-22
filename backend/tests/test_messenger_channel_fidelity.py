"""The Messenger channel must behave like the real one on the wire and in the thread.

Three gaps, each visible to a customer:
  1. the Page's own outgoing message arrives again on `message_echoes`; without an echo guard the
     store's reply is stored as an INBOUND customer message, so the agent reads their own words as
     if the customer had written them;
  2. the policy layer grants a human a 7-day window, but Meta honours it only when the request
     carries `messaging_type=MESSAGE_TAG` and `tag=HUMAN_AGENT` — so a reply at hour 25 was allowed
     locally and then refused by the provider;
  3. a quote is sent by the client (`replyTo`) and was dropped by the adapter without an error.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.modules.conversations.gateway.messenger import messenger_adapter

CREDS = ProviderCredentials(config={"api_key": "PAGE-TOKEN"})


def _msg(**kw) -> OutboundMessage:
    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="PSID-1",
        **kw,
    )


def _client(sent: list, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(status, json={"recipient_id": "PSID-1", "message_id": "mid.1"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _envelope(message: dict, sender: str = "PSID-1") -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": "PAGE-1",
                "messaging": [
                    {
                        "sender": {"id": sender},
                        "recipient": {"id": "PAGE-1"},
                        "timestamp": 1_700_000_000_000,
                        "message": message,
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------- inbound: echo guard


def test_an_echo_of_our_own_reply_is_not_an_inbound_customer_message():
    parsed = messenger_adapter.parse_inbound(
        _envelope({"mid": "m1", "text": "أهلاً بك", "is_echo": True})
    )
    assert parsed == []


def test_a_real_customer_message_still_parses():
    parsed = messenger_adapter.parse_inbound(_envelope({"mid": "m2", "text": "بكام؟"}))
    assert len(parsed) == 1
    assert parsed[0].body == "بكام؟"
    assert parsed[0].customer_ref == "PSID-1"


def test_a_quote_on_an_inbound_message_is_kept():
    parsed = messenger_adapter.parse_inbound(
        _envelope({"mid": "m3", "text": "ده", "reply_to": {"mid": "m0"}})
    )
    assert parsed[0].reply_to_message_id == "m0"


# ---------------------------------------------------------------- outbound: tag + quote


async def test_a_human_reply_after_the_window_carries_the_human_agent_tag():
    sent: list = []
    await messenger_adapter.send(
        CREDS, _msg(body="تمام يا فندم", meta={"human_agent": True}), _client=_client(sent)
    )
    assert sent[0]["messaging_type"] == "MESSAGE_TAG"
    assert sent[0]["tag"] == "HUMAN_AGENT"
    assert sent[0]["message"] == {"text": "تمام يا فندم"}


async def test_an_ordinary_reply_carries_no_tag():
    sent: list = []
    await messenger_adapter.send(CREDS, _msg(body="أهلاً"), _client=_client(sent))
    assert "tag" not in sent[0]
    assert "messaging_type" not in sent[0]


async def test_a_quote_is_sent_beside_the_message():
    sent: list = []
    await messenger_adapter.send(
        CREDS,
        _msg(body="رد على سؤالك", meta={"reply_to_provider_id": "mid.0"}),
        _client=_client(sent),
    )
    assert sent[0]["reply_to"] == {"mid": "mid.0"}
    assert sent[0]["message"] == {"text": "رد على سؤالك"}


async def test_the_tag_rides_a_captioned_file_too():
    """A file plus a caption is two calls; both belong to the same human-agent reply."""
    sent: list = []
    await messenger_adapter.send(
        CREDS,
        _msg(
            body="الفايل",
            media_url="https://files.example/signed/a.pdf?sig=1",
            meta={"media_type": "file", "human_agent": True},
        ),
        _client=_client(sent),
    )
    assert len(sent) == 2
    assert all(p["tag"] == "HUMAN_AGENT" for p in sent)


# ---------------------------------------------------------------- sender actions (seen / typing)


async def test_mark_seen_is_a_sender_action_with_no_message_body():
    sent: list = []
    await messenger_adapter.send_sender_action(CREDS, "PSID-1", "mark_seen", _client=_client(sent))
    assert sent == [{"recipient": {"id": "PSID-1"}, "sender_action": "mark_seen"}]
    assert "message" not in sent[0]


async def test_typing_on_is_a_sender_action_too():
    sent: list = []
    await messenger_adapter.send_sender_action(CREDS, "PSID-1", "typing_on", _client=_client(sent))
    assert sent[0]["sender_action"] == "typing_on"


async def test_a_refused_sender_action_raises_so_the_caller_can_stay_silent():
    sent: list = []
    client = _client(sent, status=400)
    with pytest.raises(ExternalProviderError):
        await messenger_adapter.send_sender_action(CREDS, "PSID-1", "mark_seen", _client=client)
