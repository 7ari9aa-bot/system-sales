"""Instagram's documented limits and error codes, enforced before and after the call."""

from __future__ import annotations

import httpx
import pytest

from app.core.circuit_breaker import reset_breakers
from app.core.errors import ExternalProviderError
from app.core.instagram_version import INSTAGRAM_API_VERSION
from app.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.modules.conversations.gateway.instagram import InstagramAdapter, InstagramProviderError
from app.modules.conversations.gateway.instagram_limits import (
    LIMIT,
    MAX_TEXT_BYTES,
    PERMISSION,
    RECIPIENT,
    RECONNECT,
    RETRY,
    UNKNOWN,
    WINDOW,
    InstagramLimitError,
    check_media,
    check_text,
    classify_instagram_error,
    text_bytes,
)

A = InstagramAdapter()
CREDS = ProviderCredentials(config={"api_key": "tok", "account_id": "ig1"})


@pytest.fixture(autouse=True)
def _closed_breaker():
    reset_breakers()
    yield
    reset_breakers()


def _msg(**kw) -> OutboundMessage:
    import uuid

    base = dict(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="cust1",
    )
    base.update(kw)
    return OutboundMessage(**base)


# ------------------------------------------------------------------ one version


def test_every_instagram_call_uses_the_one_pinned_version() -> None:
    assert INSTAGRAM_API_VERSION == "v27.0"
    assert A._base == "https://graph.facebook.com/v27.0"


def test_the_connection_spec_verifies_on_the_same_version() -> None:
    from app.modules.platform.channel_specs.instagram import INSTAGRAM_GRAPH_BASE

    assert INSTAGRAM_GRAPH_BASE.endswith(f"/{INSTAGRAM_API_VERSION}")


# --------------------------------------------------------------------- text size


def test_the_text_limit_counts_bytes_not_characters() -> None:
    assert text_bytes("a") == 1
    assert text_bytes("ع") == 2  # an Arabic letter is two bytes in UTF-8
    check_text("a" * MAX_TEXT_BYTES)  # exactly the limit is fine
    check_text("ع" * (MAX_TEXT_BYTES // 2))
    with pytest.raises(InstagramLimitError) as e:
        check_text("a" * (MAX_TEXT_BYTES + 1))
    assert e.value.code == "text_too_long"


def test_an_arabic_message_over_500_letters_is_refused_before_any_call() -> None:
    long_arabic = "م" * 501  # 1002 bytes, though only 501 characters
    assert len(long_arabic) < MAX_TEXT_BYTES
    with pytest.raises(InstagramLimitError):
        A.build_send_payload(_msg(body=long_arabic))


def test_a_short_arabic_message_still_goes_through() -> None:
    payload = A.build_send_payload(_msg(body="أهلاً بيك، تحب تحجز؟"))
    assert payload["message"] == {"text": "أهلاً بيك، تحب تحجز؟"}


async def test_a_too_long_text_never_reaches_the_network() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"message_id": "m1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(InstagramLimitError):
        await A.send(CREDS, _msg(body="x" * 1001), _client=client)
    assert calls == []


def test_reactions_hearts_and_shares_are_not_measured_as_text() -> None:
    A.build_send_payload(_msg(body="❤️", meta={"reaction_to_provider_id": "m9"}))
    A.build_send_payload(_msg(body="x" * 5000, meta={"like_heart": True}))
    A.build_send_payload(_msg(meta={"share_media_id": "123"}))


# ------------------------------------------------------------------------ media


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://cdn.example.com/a.png", "image"),
        ("https://cdn.example.com/a.JPG?sig=1", "image"),
        ("https://cdn.example.com/a.m4a", "audio"),
        ("https://cdn.example.com/a.webm", "video"),
        ("https://cdn.example.com/a.pdf", "file"),
        ("https://cdn.example.com/signed-no-extension?x=1", "file"),
    ],
)
def test_supported_media_passes(url: str, kind: str) -> None:
    check_media(url, kind)


@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://cdn.example.com/a.gif", "image"),
        ("https://cdn.example.com/a.webp", "image"),
        ("https://cdn.example.com/a.docx", "file"),
        ("https://cdn.example.com/a.xlsx", "file"),
        ("https://cdn.example.com/a.mp3", "audio"),
        ("https://cdn.example.com/a.mkv", "video"),
    ],
)
def test_unsupported_formats_are_refused(url: str, kind: str) -> None:
    with pytest.raises(InstagramLimitError) as e:
        check_media(url, kind)
    assert e.value.code == "media_format"


def test_sizes_are_capped_per_kind() -> None:
    mb = 1024 * 1024
    check_media("https://x.example/a.png", "image", 8 * mb)
    with pytest.raises(InstagramLimitError):
        check_media("https://x.example/a.png", "image", 8 * mb + 1)
    check_media("https://x.example/a.pdf", "file", 25 * mb)
    with pytest.raises(InstagramLimitError):
        check_media("https://x.example/a.mp4", "video", 25 * mb + 1)


def test_media_must_be_a_public_https_link() -> None:
    with pytest.raises(InstagramLimitError):
        check_media("http://x.example/a.png", "image")


def test_a_word_document_is_refused_when_sending_a_file() -> None:
    with pytest.raises(InstagramLimitError):
        A.build_send_payload(
            _msg(media_url="https://x.example/offer.docx", meta={"media_type": "document"})
        )


def test_a_pdf_is_sent_as_a_file_attachment() -> None:
    payload = A.build_send_payload(
        _msg(media_url="https://x.example/offer.pdf", meta={"media_type": "document"})
    )
    assert payload["message"]["attachment"] == {
        "type": "file",
        "payload": {"url": "https://x.example/offer.pdf"},
    }


# ------------------------------------------------------------- error classification


@pytest.mark.parametrize(
    "error,kind,retryable",
    [
        ({"error": {"code": 190, "message": "expired"}}, RECONNECT, False),
        ({"error": {"code": 102}}, RECONNECT, False),
        ({"error": {"code": 10}}, PERMISSION, False),
        ({"error": {"code": 200}}, PERMISSION, False),
        ({"error": {"code": 4}}, LIMIT, True),
        ({"error": {"code": 17}}, LIMIT, True),
        ({"error": {"code": 32}}, LIMIT, True),
        ({"error": {"code": 613}}, LIMIT, True),
        ({"error": {"code": 100, "error_subcode": 2534014}}, RECIPIENT, False),
        ({"error": {"code": 10, "error_subcode": 2534022}}, WINDOW, False),
        ({"error": {"code": 9, "error_subcode": 2207042}}, LIMIT, False),
        ({"error": {"code": 2}}, RETRY, True),
    ],
)
def test_meta_error_codes_map_to_an_action(error: dict, kind: str, retryable: bool) -> None:
    failure = classify_instagram_error(error)
    assert (failure.kind, failure.retryable) == (kind, retryable)
    assert failure.message_ar


def test_the_subcode_is_more_specific_than_the_code() -> None:
    # code 10 alone is a permission problem; with subcode 2534022 it is the messaging window.
    assert classify_instagram_error({"error": {"code": 10}}).kind == PERMISSION
    both = {"error": {"code": 10, "error_subcode": 2534022}}
    assert classify_instagram_error(both).kind == WINDOW


def test_codes_are_read_from_error_text_too() -> None:
    assert classify_instagram_error("(#190) token expired").kind == RECONNECT
    assert classify_instagram_error("HTTP 503 bad gateway").kind == RETRY
    assert classify_instagram_error("HTTP 429 slow down").kind == LIMIT


def test_an_unrecognised_error_is_unknown_and_not_retried() -> None:
    failure = classify_instagram_error({"error": {"code": 987654}})
    assert failure.kind == UNKNOWN and failure.retryable is False


async def test_a_refused_send_raises_a_classified_error_that_is_still_a_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 190, "message": "Session has expired"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(InstagramProviderError) as e:
        await A.send(CREDS, _msg(body="hi"), _client=client)
    assert isinstance(e.value, ExternalProviderError)  # existing handlers keep working
    assert e.value.failure.kind == RECONNECT
    assert e.value.retryable is False


async def test_a_200_with_an_error_object_is_still_a_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": 4, "message": "rate"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(InstagramProviderError) as e:
        await A.send(CREDS, _msg(body="hi"), _client=client)
    assert e.value.failure.kind == LIMIT and e.value.retryable is True


# ----------------------------------------------------------- human agent tag


def test_a_human_agent_reply_carries_the_message_tag() -> None:
    payload = A.build_send_payload(_msg(body="hi", meta={"human_agent": True}))
    assert payload["messaging_type"] == "MESSAGE_TAG"
    assert payload["tag"] == "HUMAN_AGENT"


def test_an_ordinary_reply_carries_no_tag() -> None:
    payload = A.build_send_payload(_msg(body="hi"))
    assert "tag" not in payload and "messaging_type" not in payload
