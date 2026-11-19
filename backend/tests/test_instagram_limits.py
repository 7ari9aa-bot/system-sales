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
    check_upload,
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


# ---------------------------------------------------------------- an agent's own upload

JPG = b"\xff\xd8\xff\xe0" + b"0" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
PDF = b"%PDF-1.7\n" + b"0" * 32
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 32
WAV = b"RIFF\x00\x00\x00\x00WAVE" + b"0" * 32
AAC = b"\xff\xf1" + b"0" * 32


@pytest.mark.parametrize(
    ("mime", "data", "kind"),
    [
        ("image/jpeg", JPG, "image"),
        ("image/jpg", JPG, "image"),
        ("image/png", PNG, "image"),
        ("application/pdf", PDF, "file"),
        ("video/mp4", MP4, "video"),
        ("audio/wav", WAV, "audio"),
        ("audio/aac", AAC, "audio"),
        ("audio/mp4", MP4, "audio"),
        ("image/jpeg; charset=binary", JPG, "image"),
    ],
)
def test_an_upload_instagram_accepts_is_named_by_its_send_type(mime, data, kind):
    spec = check_upload(mime, data)
    assert (spec.kind, spec.size) == (kind, len(data))


@pytest.mark.parametrize(
    ("mime", "data", "code"),
    [
        # WhatsApp takes these; Instagram does not
        ("image/webp", b"RIFF\x00\x00\x00\x00WEBP", "media_format"),
        ("audio/ogg", b"OggS" + b"0" * 20, "media_format"),
        ("audio/mpeg", b"ID3" + b"0" * 20, "media_format"),
        ("application/msword", b"\xd0\xcf\x11\xe0" + b"0" * 20, "media_format"),
        ("text/plain", b"hello", "media_format"),
        ("", JPG, "media_format"),
        ("image/jpeg", b"", "media_empty"),
        # the declared type is only a claim: the bytes must agree
        ("image/jpeg", PNG, "media_mismatch"),
        ("application/pdf", JPG, "media_mismatch"),
        ("video/mp4", b"not a video at all", "media_mismatch"),
    ],
)
def test_an_upload_instagram_would_refuse_is_refused_before_it_is_stored(mime, data, code):
    with pytest.raises(InstagramLimitError) as exc:
        check_upload(mime, data)
    assert exc.value.code == code


def test_an_upload_over_the_size_cap_names_the_cap():
    mb = 1024 * 1024
    check_upload("image/jpeg", JPG + b"0" * (8 * mb - len(JPG)))  # exactly 8 MB: fine
    with pytest.raises(InstagramLimitError, match="at most 8 MB") as exc:
        check_upload("image/jpeg", JPG + b"0" * (8 * mb))
    assert exc.value.code == "media_size"
    # video and pdf have the larger 25 MB cap, not the image one
    check_upload("application/pdf", PDF + b"0" * (9 * mb))


def test_the_size_reaches_the_gateway_so_an_oversized_file_cannot_slip_through():
    """The signed storage link has no extension, so the SIZE is the only thing that can stop it."""
    mb = 1024 * 1024
    link = "https://bucket.example/outbound-media/t/abc?X-Amz-Signature=1"
    ok = OutboundMessage(
        tenant_id=None,
        conversation_id=None,
        message_id=None,
        customer_ref="igsid-1",
        body=None,
        media_url=link,
        meta={"media_type": "image", "media_size_bytes": 2 * mb},
    )
    assert InstagramAdapter.build_send_payload(ok)["message"] == {
        "attachment": {"type": "image", "payload": {"url": link}}
    }
    big = OutboundMessage(
        tenant_id=None,
        conversation_id=None,
        message_id=None,
        customer_ref="igsid-1",
        body=None,
        media_url=link,
        meta={"media_type": "image", "media_size_bytes": 9 * mb},
    )
    with pytest.raises(InstagramLimitError, match="at most 8 MB"):
        InstagramAdapter.build_send_payload(big)
    # a PDF is sent as Instagram's "file" attachment
    pdf = OutboundMessage(
        tenant_id=None,
        conversation_id=None,
        message_id=None,
        customer_ref="igsid-1",
        body=None,
        media_url=link,
        meta={"media_type": "document", "media_size_bytes": 1000},
    )
    assert InstagramAdapter.build_send_payload(pdf)["message"]["attachment"]["type"] == "file"


def test_the_send_worker_tells_the_adapter_how_big_the_uploaded_file_is():
    from app.workers.message_worker import uploaded_media_meta

    assert uploaded_media_meta("image", {"filename": "a.jpg", "media_size_bytes": 123}) == {
        "media_type": "image",
        "filename": "a.jpg",
        "media_size_bytes": 123,
    }
    # an old upload that stored no size still sends (the size is just not checked)
    assert uploaded_media_meta(None, None) == {
        "media_type": "document",
        "filename": "file",
        "media_size_bytes": None,
    }
