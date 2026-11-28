"""A file an agent sends on Telegram is delivered as a photo, video, audio or document.

Before this the adapter always called sendMessage, so any file went out as the text "[media]".
Telegram downloads a linked file itself, with tighter limits than an upload; a file it would not
deliver is refused in plain words before any call.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.applications.apparel.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.applications.apparel.modules.conversations.gateway.telegram import telegram_adapter
from app.applications.apparel.modules.conversations.gateway.telegram_media import (
    MAX_BYTES,
    MAX_CAPTION_CHARS,
    TelegramLimitError,
    check_file,
    file_field,
    send_method,
)

MB = 1024 * 1024
LINK = "https://files.example/signed/abc?sig=1"
CREDS = ProviderCredentials(config={"bot_token": "123:ABC"})


def _msg(**kw) -> OutboundMessage:
    return OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="555",
        **kw,
    )


def _client(calls: list, status=200, ok=True):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        body = {"ok": ok, "result": {"message_id": 100 + len(calls)}}
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("raw", "method", "field"),
    [
        ("image", "sendPhoto", "photo"),
        ("photo", "sendPhoto", "photo"),
        ("video", "sendVideo", "video"),
        ("audio", "sendAudio", "audio"),
        ("voice", "sendAudio", "audio"),
        ("document", "sendDocument", "document"),
        ("file", "sendDocument", "document"),
        ("something-new", "sendDocument", "document"),
        (None, "sendDocument", "document"),
    ],
)
def test_the_inbox_kind_picks_the_bot_method(raw, method, field):
    assert send_method(raw) == method
    assert file_field(method) == field


def test_the_limits_are_telegrams_for_a_linked_file():
    assert MAX_BYTES["sendPhoto"] == 5 * MB
    assert MAX_BYTES["sendVideo"] == MAX_BYTES["sendAudio"] == MAX_BYTES["sendDocument"] == 20 * MB
    assert MAX_CAPTION_CHARS == 1024


def test_check_file_enforces_size_link_and_document_type():
    check_file("sendPhoto", LINK, 5 * MB)  # exactly at the limit
    check_file("sendVideo", LINK, 20 * MB)
    check_file("sendPhoto", LINK, None)  # unknown size is not refused
    check_file("sendDocument", LINK, MB, "Price List.PDF")  # case does not matter
    check_file("sendDocument", LINK, MB, "bundle.zip")
    with pytest.raises(TelegramLimitError) as e:
        check_file("sendPhoto", LINK, 5 * MB + 1)
    assert e.value.code == "media_size"
    with pytest.raises(TelegramLimitError, match="20 MB"):
        check_file("sendVideo", LINK, 21 * MB)
    with pytest.raises(TelegramLimitError) as e:
        check_file("sendPhoto", "http://plain.example/a.jpg")
    assert e.value.code == "media_url"
    with pytest.raises(TelegramLimitError) as e:
        check_file("sendDocument", LINK, MB, "offer.docx")
    assert e.value.code == "media_document_type"
    assert "offer.docx" in str(e.value)
    with pytest.raises(TelegramLimitError):
        check_file("sendDocument", LINK, MB, None)  # a name-less document is not known to be a PDF


async def test_a_photo_goes_out_as_a_photo_with_its_link():
    calls: list = []
    mid = await telegram_adapter.send(
        CREDS, _msg(media_url=LINK, meta={"media_type": "image"}), _client=_client(calls)
    )
    assert calls == [("sendPhoto", {"chat_id": "555", "photo": LINK})]
    assert mid == "101"
    assert "[media]" not in json.dumps(calls)


async def test_a_pdf_goes_out_as_a_document():
    calls: list = []
    await telegram_adapter.send(
        CREDS,
        _msg(media_url=LINK, meta={"media_type": "document", "filename": "prices.pdf"}),
        _client=_client(calls),
    )
    assert calls == [("sendDocument", {"chat_id": "555", "document": LINK})]


@pytest.mark.parametrize(("kind", "method"), [("video", "sendVideo"), ("audio", "sendAudio")])
async def test_video_and_audio_use_their_own_methods(kind, method):
    calls: list = []
    await telegram_adapter.send(
        CREDS, _msg(media_url=LINK, meta={"media_type": kind}), _client=_client(calls)
    )
    assert calls[0][0] == method


async def test_a_short_caption_rides_with_the_file_in_one_call():
    calls: list = []
    await telegram_adapter.send(
        CREDS,
        _msg(body="Our catalogue", media_url=LINK, meta={"media_type": "image"}),
        _client=_client(calls),
    )
    assert calls == [("sendPhoto", {"chat_id": "555", "photo": LINK, "caption": "Our catalogue"})]


async def test_a_caption_of_exactly_1024_characters_still_rides_with_the_file():
    calls: list = []
    await telegram_adapter.send(
        CREDS,
        _msg(body="x" * 1024, media_url=LINK, meta={"media_type": "image"}),
        _client=_client(calls),
    )
    assert len(calls) == 1 and len(calls[0][1]["caption"]) == 1024


async def test_a_longer_text_follows_the_file_as_its_own_message_and_the_file_id_is_kept():
    calls: list = []
    long = "x" * 1025
    mid = await telegram_adapter.send(
        CREDS,
        _msg(body=long, media_url=LINK, meta={"media_type": "image"}),
        _client=_client(calls),
    )
    assert [c[0] for c in calls] == ["sendPhoto", "sendMessage"]
    assert "caption" not in calls[0][1]
    assert calls[1][1] == {"chat_id": "555", "text": long}
    assert mid == "101"


async def test_buttons_go_with_the_last_call_the_customer_sees():
    markup = {"inline_keyboard": [[{"text": "Order", "callback_data": "o"}]]}
    calls: list = []
    await telegram_adapter.send(
        CREDS,
        _msg(body="hi", media_url=LINK, meta={"media_type": "image", "reply_markup": markup}),
        _client=_client(calls),
    )
    assert calls[0][1]["reply_markup"] == markup
    calls.clear()
    await telegram_adapter.send(
        CREDS,
        _msg(body="x" * 1025, media_url=LINK, meta={"media_type": "image", "reply_markup": markup}),
        _client=_client(calls),
    )
    assert "reply_markup" not in calls[0][1]
    assert calls[1][1]["reply_markup"] == markup


async def test_a_plain_text_message_is_unchanged():
    calls: list = []
    await telegram_adapter.send(CREDS, _msg(body="hello"), _client=_client(calls))
    assert calls == [("sendMessage", {"chat_id": "555", "text": "hello"})]


async def test_text_buttons_are_unchanged():
    markup = {"inline_keyboard": [[{"text": "Yes", "callback_data": "y"}]]}
    calls: list = []
    await telegram_adapter.send(
        CREDS, _msg(body="ok?", meta={"reply_markup": markup}), _client=_client(calls)
    )
    assert calls == [("sendMessage", {"chat_id": "555", "text": "ok?", "reply_markup": markup})]


async def test_an_unsupported_document_is_refused_before_any_call():
    calls: list = []
    with pytest.raises(ExternalProviderError, match=r"PDF and ZIP.*offer\.docx"):
        await telegram_adapter.send(
            CREDS,
            _msg(media_url=LINK, meta={"media_type": "document", "filename": "offer.docx"}),
            _client=_client(calls),
        )
    assert calls == []


async def test_a_photo_over_5_mb_is_refused_but_a_video_of_that_size_is_not():
    calls: list = []
    big = 6 * MB
    with pytest.raises(ExternalProviderError, match="5 MB"):
        await telegram_adapter.send(
            CREDS,
            _msg(media_url=LINK, meta={"media_type": "image", "media_size_bytes": big}),
            _client=_client(calls),
        )
    assert calls == []
    await telegram_adapter.send(
        CREDS,
        _msg(media_url=LINK, meta={"media_type": "video", "media_size_bytes": big}),
        _client=_client(calls),
    )
    assert len(calls) == 1


async def test_a_rejected_file_is_a_failure_not_a_silent_success():
    with pytest.raises(ExternalProviderError, match="telegram send failed"):
        await telegram_adapter.send(
            CREDS,
            _msg(media_url=LINK, meta={"media_type": "image"}),
            _client=_client([], ok=False),
        )


async def test_a_refused_file_is_a_definitive_failure_the_worker_does_not_retry():
    """The worker retries only what it classes `unknown`; a rule we broke can never succeed."""
    from app.workers.message_worker import _classify_send_failure

    for meta in (
        {"media_type": "image", "media_size_bytes": 6 * MB},
        {"media_type": "document", "filename": "offer.docx"},
        {"media_type": "video", "media_size_bytes": 21 * MB},
    ):
        with pytest.raises(ExternalProviderError) as e:
            await telegram_adapter.send(CREDS, _msg(media_url=LINK, meta=meta), _client=_client([]))
        assert _classify_send_failure(e.value) == "failed", str(e.value)
