"""What an agent may upload to send on Messenger and on Telegram, checked at upload time.

A file a channel would refuse must fail while the agent can still pick another, not after it was
"sent". The declared type is only a claim: the first bytes must agree with it.
"""

from __future__ import annotations

import inspect

import pytest

from app.modules.conversations.gateway.messenger_media import (
    MessengerLimitError,
)
from app.modules.conversations.gateway.messenger_media import (
    check_upload as messenger_upload,
)
from app.modules.conversations.gateway.telegram_media import (
    TelegramLimitError,
)
from app.modules.conversations.gateway.telegram_media import (
    check_upload as telegram_upload,
)

MB = 1024 * 1024
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
GIF = b"GIF89a" + b"0" * 20
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 20
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 20
MP3 = b"ID3" + b"0" * 20
PDF = b"%PDF-1.7\n" + b"0" * 20
ZIP = b"PK\x03\x04" + b"0" * 20
DOCX = b"PK\x03\x04" + b"0" * 20  # a docx is a zip: its bytes alone cannot tell it apart


# ------------------------------------------------------------------ Messenger


@pytest.mark.parametrize(
    ("mime", "data", "kind"),
    [
        ("image/jpeg", JPEG, "image"),
        ("image/jpg", JPEG, "image"),  # a common wrong spelling
        ("image/png", PNG, "image"),
        ("image/gif", GIF, "image"),
        ("image/webp", WEBP, "image"),
        ("audio/mpeg", MP3, "audio"),
        ("video/mp4", MP4, "video"),
        ("application/pdf", PDF, "file"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", DOCX, "file"),
        ("text/csv", b"a,b\n1,2\n", "file"),
        ("application/pdf; charset=binary", PDF, "file"),
    ],
)
def test_messenger_classifies_what_it_can_send(mime, data, kind):
    spec = messenger_upload(mime, data)
    assert spec.kind == kind and spec.size == len(data)


@pytest.mark.parametrize(
    "mime", ["text/html", "image/svg+xml", "application/x-msdownload", "application/x-sh", "", None]
)
def test_messenger_never_sends_a_page_a_script_or_a_program(mime):
    with pytest.raises(MessengerLimitError) as e:
        messenger_upload(mime, b"x")
    assert e.value.code == "media_format"


def test_messenger_checks_the_bytes_agree_with_the_declared_type():
    with pytest.raises(MessengerLimitError) as e:
        messenger_upload("image/png", JPEG)
    assert e.value.code == "media_mismatch"
    with pytest.raises(MessengerLimitError):
        messenger_upload("video/mp4", PDF)


def test_messenger_refuses_an_empty_file():
    with pytest.raises(MessengerLimitError) as e:
        messenger_upload("application/pdf", b"")
    assert e.value.code == "media_empty"


def test_messenger_limits_are_8_mb_for_an_image_and_25_for_the_rest():
    messenger_upload("image/jpeg", JPEG + b"0" * (8 * MB - len(JPEG)))  # exactly 8 MB
    with pytest.raises(MessengerLimitError, match="8 MB"):
        messenger_upload("image/jpeg", JPEG + b"0" * (8 * MB - len(JPEG) + 1))
    messenger_upload("application/pdf", PDF + b"0" * (25 * MB - len(PDF)))
    with pytest.raises(MessengerLimitError, match="25 MB"):
        messenger_upload("application/pdf", PDF + b"0" * (25 * MB - len(PDF) + 1))
    # the same 9 MB is too big as an image and fine as a video
    nine = 9 * MB
    with pytest.raises(MessengerLimitError):
        messenger_upload("image/png", PNG + b"0" * nine)
    messenger_upload("video/mp4", MP4 + b"0" * nine)


# ------------------------------------------------------------------ Telegram


@pytest.mark.parametrize(
    ("mime", "data", "kind", "method"),
    [
        ("image/jpeg", JPEG, "image", "sendPhoto"),
        ("image/jpg", JPEG, "image", "sendPhoto"),
        ("image/png", PNG, "image", "sendPhoto"),
        ("image/gif", GIF, "image", "sendPhoto"),
        ("image/webp", WEBP, "image", "sendPhoto"),
        ("video/mp4", MP4, "video", "sendVideo"),
        ("audio/mpeg", MP3, "audio", "sendAudio"),
        ("audio/mp4", MP4, "audio", "sendAudio"),
        ("application/pdf", PDF, "document", "sendDocument"),
        ("application/zip", ZIP, "document", "sendDocument"),
    ],
)
def test_telegram_classifies_what_it_can_send(mime, data, kind, method):
    spec = telegram_upload(mime, data)
    assert (spec.kind, spec.method, spec.size) == (kind, method, len(data))


@pytest.mark.parametrize(
    "mime",
    [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "text/plain",
        "video/quicktime",
        "image/svg+xml",
        "text/html",
        "",
        None,
    ],
)
def test_telegram_refuses_a_type_it_would_not_deliver_by_link(mime):
    with pytest.raises(TelegramLimitError) as e:
        telegram_upload(mime, b"x")
    assert e.value.code == "media_format"
    assert "pdf" in str(e.value).lower()  # it says what would work


def test_telegram_checks_the_bytes_agree_with_the_declared_type():
    with pytest.raises(TelegramLimitError) as e:
        telegram_upload("application/pdf", ZIP)
    assert e.value.code == "media_mismatch"
    with pytest.raises(TelegramLimitError):
        telegram_upload("image/png", JPEG)


def test_telegram_refuses_an_empty_file():
    with pytest.raises(TelegramLimitError) as e:
        telegram_upload("application/pdf", b"")
    assert e.value.code == "media_empty"


def test_telegram_limits_are_5_mb_for_a_photo_and_20_for_the_rest():
    telegram_upload("image/jpeg", JPEG + b"0" * (5 * MB - len(JPEG)))
    with pytest.raises(TelegramLimitError, match="5 MB"):
        telegram_upload("image/jpeg", JPEG + b"0" * (5 * MB - len(JPEG) + 1))
    telegram_upload("application/pdf", PDF + b"0" * (20 * MB - len(PDF)))
    with pytest.raises(TelegramLimitError, match="20 MB"):
        telegram_upload("application/pdf", PDF + b"0" * (20 * MB - len(PDF) + 1))
    six = 6 * MB
    with pytest.raises(TelegramLimitError):
        telegram_upload("image/png", PNG + b"0" * six)
    telegram_upload("video/mp4", MP4 + b"0" * six)


def test_what_upload_accepts_the_send_accepts():
    """An upload that passes must not then be refused when sent: the two share one rule set."""
    from app.modules.conversations.gateway.telegram_media import check_file

    for mime, data, name in (
        ("image/png", PNG, None),
        ("video/mp4", MP4, None),
        ("audio/mpeg", MP3, None),
        ("application/pdf", PDF, "a.pdf"),
        ("application/zip", ZIP, "a.zip"),
    ):
        spec = telegram_upload(mime, data)
        check_file(spec.method, "https://x.example/f", spec.size, name)


# ------------------------------------------------------------------ the route


def test_the_upload_route_uses_each_channels_own_check():
    """The route must call the channel's check, not WhatsApp's rules, for these two channels."""
    from app.modules.conversations.routers import inbox

    src = inspect.getsource(inbox.upload_media)
    assert "messenger_check_upload" in src and "telegram_check_upload" in src
    assert set(inbox._FILE_CHANNELS) == {"whatsapp", "instagram", "messenger", "telegram"}
