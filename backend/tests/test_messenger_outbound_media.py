"""A file an agent sends on Messenger is delivered as a file, not as its name in a text bubble.

Before this, the adapter read only `body`, so an uploaded PDF went out as the words of its file
name. Messenger takes a text and an attachment as two messages, so a captioned file is two calls.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.applications.apparel.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.applications.apparel.modules.conversations.gateway.messenger import messenger_adapter
from app.applications.apparel.modules.conversations.gateway.messenger_media import (
    MAX_BYTES,
    MessengerLimitError,
    attachment_type,
    check_attachment,
)

MB = 1024 * 1024
LINK = "https://files.example/signed/abc?sig=1"
CREDS = ProviderCredentials(config={"api_key": "PAGE-TOKEN"})


def _msg(**kw) -> OutboundMessage:
    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="PSID-1",
        **kw,
    )


def _client(sent: list, ids=("mid.1", "mid.2"), status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        n = len(sent) - 1
        return httpx.Response(status, json={"recipient_id": "PSID-1", "message_id": ids[n]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("image", "image"),
        ("photo", "image"),
        ("sticker", "image"),
        ("audio", "audio"),
        ("voice", "audio"),
        ("video", "video"),
        ("document", "file"),
        ("file", "file"),
        ("something-new", "file"),  # never guessed to be an image
        (None, "file"),
    ],
)
def test_the_inbox_kind_becomes_a_send_api_attachment_type(raw, kind):
    assert attachment_type(raw) == kind


def test_the_size_limits_are_metas():
    assert MAX_BYTES["image"] == 8 * MB
    assert MAX_BYTES["audio"] == MAX_BYTES["video"] == MAX_BYTES["file"] == 25 * MB


def test_check_attachment_enforces_size_link_and_kind():
    check_attachment(LINK, "image", 8 * MB)  # exactly at the limit
    check_attachment(LINK, "file", 25 * MB)
    check_attachment(LINK, "file", None)  # unknown size is not refused
    with pytest.raises(MessengerLimitError) as e:
        check_attachment(LINK, "image", 8 * MB + 1)
    assert e.value.code == "media_size"
    with pytest.raises(MessengerLimitError, match="25 MB"):
        check_attachment(LINK, "video", 25 * MB + 1)
    with pytest.raises(MessengerLimitError) as e:
        check_attachment("http://plain.example/a.pdf", "file")
    assert e.value.code == "media_url"
    with pytest.raises(MessengerLimitError) as e:
        check_attachment(LINK, "template")
    assert e.value.code == "media_kind"


async def test_a_file_goes_out_as_an_attachment_with_its_link():
    sent: list = []
    mid = await messenger_adapter.send(
        CREDS,
        _msg(media_url=LINK, meta={"media_type": "document", "filename": "price list.pdf"}),
        _client=_client(sent),
    )
    assert mid == "mid.1"
    assert sent == [
        {
            "recipient": {"id": "PSID-1"},
            "message": {"attachment": {"type": "file", "payload": {"url": LINK}}},
        }
    ]
    assert "price list" not in json.dumps(sent)  # the name is not sent as text
    assert "is_reusable" not in json.dumps(sent)  # sent in one step: no id that expires


@pytest.mark.parametrize(
    ("media_type", "kind"), [("image", "image"), ("audio", "audio"), ("video", "video")]
)
async def test_each_kind_uses_its_own_attachment_type(media_type, kind):
    sent: list = []
    await messenger_adapter.send(
        CREDS, _msg(media_url=LINK, meta={"media_type": media_type}), _client=_client(sent)
    )
    assert sent[0]["message"]["attachment"]["type"] == kind


async def test_a_caption_follows_the_file_as_its_own_message_and_the_file_id_is_kept():
    sent: list = []
    mid = await messenger_adapter.send(
        CREDS,
        _msg(body="Here is the catalogue", media_url=LINK, meta={"media_type": "document"}),
        _client=_client(sent),
    )
    assert len(sent) == 2
    assert sent[0]["message"]["attachment"]["type"] == "file"
    assert sent[1]["message"] == {"text": "Here is the catalogue"}
    assert "attachment" not in sent[1]["message"]
    assert mid == "mid.1"


async def test_a_plain_text_message_is_unchanged():
    sent: list = []
    mid = await messenger_adapter.send(CREDS, _msg(body="hello"), _client=_client(sent))
    assert sent == [{"recipient": {"id": "PSID-1"}, "message": {"text": "hello"}}]
    assert mid == "mid.1"


async def test_a_template_is_unchanged():
    sent: list = []
    await messenger_adapter.send(
        CREDS,
        _msg(template_name="button", template_vars={"text": "Pick", "buttons": []}),
        _client=_client(sent),
    )
    assert sent[0]["message"]["attachment"]["type"] == "template"
    assert sent[0]["message"]["attachment"]["payload"]["template_type"] == "button"


async def test_a_file_over_the_limit_is_refused_before_any_call():
    sent: list = []
    with pytest.raises(ExternalProviderError, match="25 MB"):
        await messenger_adapter.send(
            CREDS,
            _msg(
                media_url=LINK,
                meta={"media_type": "document", "media_size_bytes": 26 * MB},
            ),
            _client=_client(sent),
        )
    assert sent == []


async def test_an_image_over_8_mb_is_refused_but_the_same_size_video_is_not():
    sent: list = []
    big = 9 * MB
    with pytest.raises(ExternalProviderError, match="8 MB"):
        await messenger_adapter.send(
            CREDS,
            _msg(media_url=LINK, meta={"media_type": "image", "media_size_bytes": big}),
            _client=_client(sent),
        )
    assert sent == []
    await messenger_adapter.send(
        CREDS,
        _msg(media_url=LINK, meta={"media_type": "video", "media_size_bytes": big}),
        _client=_client(sent),
    )
    assert len(sent) == 1


async def test_a_rejected_file_is_a_failure_not_a_silent_success():
    sent: list = []
    with pytest.raises(ExternalProviderError, match="HTTP 400"):
        await messenger_adapter.send(
            CREDS,
            _msg(media_url=LINK, meta={"media_type": "image"}),
            _client=_client(sent, status=400),
        )


async def test_a_refused_file_is_a_definitive_failure_the_worker_does_not_retry():
    """The worker retries only what it classes `unknown`; a rule we broke can never succeed."""
    from app.workers.message_worker import _classify_send_failure

    for meta in (
        {"media_type": "image", "media_size_bytes": 9 * MB},
        {"media_type": "document", "media_size_bytes": 26 * MB},
    ):
        with pytest.raises(ExternalProviderError) as e:
            await messenger_adapter.send(
                CREDS, _msg(media_url=LINK, meta=meta), _client=_client([])
            )
        assert _classify_send_failure(e.value) == "failed", str(e.value)
