"""Rules for the media an agent sends to a customer (pure, no database)."""

import pytest

from app.core.errors import ValidationError
from app.modules.conversations.outbound_media import (
    CAPTION_MAX,
    MAX_BYTES,
    MB,
    check_caption,
    check_outbound_media,
    content_type_for,
    safe_filename,
)

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 64
OGG = b"OggS" + b"0" * 64
ZIPPED = b"PK\x03\x04" + b"0" * 64


def check(mime, data, name="f", **kw):
    return check_outbound_media(content_type=mime, data=data, filename=name, **kw)


@pytest.mark.parametrize(
    ("mime", "data", "kind"),
    [
        ("image/jpeg", JPEG, "image"),
        ("image/jpg", JPEG, "image"),
        ("image/png", PNG, "image"),
        ("image/webp", WEBP, "image"),
        ("video/mp4", MP4, "video"),
        ("audio/ogg", OGG, "audio"),
        ("audio/ogg; codecs=opus", OGG, "audio"),
        ("application/pdf", PDF, "document"),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ZIPPED, "document"),
        ("text/plain", b"hello", "document"),
    ],
)
def test_a_valid_file_is_classified(mime, data, kind):
    assert check(mime, data).kind == kind


@pytest.mark.parametrize(
    "mime",
    [
        "image/svg+xml",
        "text/html",
        "application/x-sh",
        "application/octet-stream",
        "image/gif",
        "application/zip",
        "",
        None,
    ],
)
def test_types_whatsapp_does_not_deliver_are_refused(mime):
    with pytest.raises(ValidationError) as e:
        check(mime, b"x" * 20)
    assert e.value.details["reason"] == "unsupported_type"


def test_the_content_must_match_the_declared_type():
    with pytest.raises(ValidationError) as e:
        check("image/png", b"<html><script>alert(1)</script></html>")
    assert e.value.details["reason"] == "content_mismatch"
    with pytest.raises(ValidationError):
        check("application/pdf", JPEG)
    with pytest.raises(ValidationError):
        check("text/plain", b"abc\x00def")


def test_an_empty_file_is_refused():
    with pytest.raises(ValidationError) as e:
        check("image/png", b"")
    assert e.value.details["reason"] == "empty"


def test_each_kind_has_its_own_size_limit():
    over_image = PNG + b"0" * (MAX_BYTES["image"] - len(PNG) + 1)
    with pytest.raises(ValidationError) as e:
        check("image/png", over_image)
    assert e.value.details["reason"] == "too_large"
    assert e.value.details["max_bytes"] == 5 * MB
    # the same size is fine as a document
    assert check("application/pdf", PDF + b"0" * (6 * MB)).kind == "document"
    # a video has a bigger allowance than an image
    assert check("video/mp4", MP4 + b"0" * (10 * MB)).kind == "video"
    with pytest.raises(ValidationError):
        check("video/mp4", MP4 + b"0" * (17 * MB))


def test_a_file_exactly_at_the_limit_is_accepted():
    assert (
        check("image/png", PNG + b"0" * (MAX_BYTES["image"] - len(PNG))).size == MAX_BYTES["image"]
    )


def test_a_sticker_must_be_a_small_webp():
    assert check("image/webp", WEBP, as_sticker=True).kind == "sticker"
    with pytest.raises(ValidationError) as e:
        check("image/png", PNG, as_sticker=True)
    assert e.value.details["reason"] == "sticker_needs_webp"
    with pytest.raises(ValidationError) as e:
        check("image/webp", WEBP + b"0" * (101 * 1024), as_sticker=True)
    assert e.value.details["reason"] == "too_large"


def test_the_stored_content_type_matches_what_inbound_uses():
    assert content_type_for("audio") == "voice"
    assert content_type_for("document") == "file"
    assert content_type_for("image") == "image"
    assert content_type_for("sticker") == "image"
    assert content_type_for("video") == "video"


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Invoice May.pdf", "Invoice May.pdf"),
        ("../../etc/passwd", "_.._etc_passwd"),
        ("a\\b:c*d?.pdf", "a_b_c_d_.pdf"),
        ("report\x00.pdf", "report_.pdf"),
        ("  .hidden  ", "hidden"),
        ("", "file"),
        (None, "file"),
        ("فاتورة.pdf", "فاتورة.pdf"),
    ],
)
def test_file_names_are_made_safe(raw, clean):
    assert safe_filename(raw) == clean


def test_a_long_name_keeps_its_extension():
    name = safe_filename("a" * 300 + ".pdf")
    assert len(name) <= 120 and name.endswith(".pdf")


def test_captions_follow_whatsapp_rules():
    assert check_caption("image", "  hi  ") == "hi"
    assert check_caption("image", "") is None
    assert check_caption("audio", "   ") is None
    for kind in ("audio", "sticker"):
        with pytest.raises(ValidationError) as e:
            check_caption(kind, "hello")
        assert e.value.details["reason"] == "caption_not_allowed"
    assert check_caption("document", "x" * CAPTION_MAX) == "x" * CAPTION_MAX
    with pytest.raises(ValidationError) as e:
        check_caption("video", "x" * (CAPTION_MAX + 1))
    assert e.value.details["reason"] == "caption_too_long"
