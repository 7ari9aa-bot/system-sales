"""What a Telegram bot may send by link, and which method carries it — one place, no network.

Taken from the Bot API's "Sending files" section and the sendPhoto / sendDocument pages (Bot API
10.4, Nov 2026). The file is handed to Telegram as a link it downloads itself, which has tighter
limits than an upload: a photo at most 5 MB, anything else at most 20 MB, and `sendDocument` by
link works only for PDF and ZIP. A file outside that is refused here, in plain words, before any
call: the alternative was a "[media]" text standing in for it.
"""

from __future__ import annotations

_MB = 1024 * 1024

#: The largest file Telegram downloads from a link, per sending method.
MAX_BYTES = {
    "sendPhoto": 5 * _MB,
    "sendVideo": 20 * _MB,
    "sendAudio": 20 * _MB,
    "sendDocument": 20 * _MB,
}

#: A caption is at most 1024 characters. A longer text is sent as its own message after the file.
MAX_CAPTION_CHARS = 1024

#: What `sendDocument` accepts by link today (Telegram: "currently only work for .PDF and .ZIP").
DOCUMENT_BY_LINK_TYPES = frozenset({"application/pdf", "application/zip"})
DOCUMENT_BY_LINK_NAMES = (".pdf", ".zip")

_METHOD = {
    "image": "sendPhoto",
    "photo": "sendPhoto",
    "video": "sendVideo",
    "audio": "sendAudio",
    "voice": "sendAudio",
    "document": "sendDocument",
    "file": "sendDocument",
}
_FIELD = {
    "sendPhoto": "photo",
    "sendVideo": "video",
    "sendAudio": "audio",
    "sendDocument": "document",
}


class TelegramLimitError(ValueError):
    """The file breaks a rule Telegram would refuse it for. Caught before any call."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def send_method(raw: str | None) -> str:
    """The Bot API method for what the inbox calls this media. Unknown kinds go as documents."""
    return _METHOD.get(str(raw or "document").lower(), "sendDocument")


def file_field(method: str) -> str:
    """The parameter that carries the link for `method` (photo, video, audio or document)."""
    return _FIELD[method]


def check_file(
    method: str,
    url: str,
    size_bytes: int | None = None,
    filename: str | None = None,
) -> None:
    """Refuse a link, size or document type Telegram would not deliver. Size only when known."""
    if method not in MAX_BYTES:
        raise TelegramLimitError("media_kind", f"Telegram cannot send with {method!r}")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise TelegramLimitError("media_url", "the file must be a public https link")
    limit = MAX_BYTES[method]
    if size_bytes is not None and size_bytes > limit:
        raise TelegramLimitError(
            "media_size",
            f"a file sent to Telegram by link is at most {limit // _MB} MB; this one is "
            f"{size_bytes / _MB:.1f} MB",
        )
    if method == "sendDocument" and not (filename or "").lower().endswith(DOCUMENT_BY_LINK_NAMES):
        raise TelegramLimitError(
            "media_document_type",
            "Telegram delivers only PDF and ZIP documents sent by link; "
            f"{filename or 'this file'} is neither. Send it as a PDF, or on another channel",
        )


# ------------------------------------------------------------- an agent's upload

from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True, slots=True)
class UploadSpec:
    mime: str
    kind: str  # the inbox kind: image | video | audio | document
    size: int
    method: str  # the Bot API method that will carry it


def _ftyp(d: bytes) -> bool:
    return len(d) >= 12 and d[4:8] == b"ftyp"


#: What Telegram delivers from a link, with the first bytes that prove each type. Only these:
#: a document sent by link must be a PDF or ZIP, so a Word or Excel file is refused at upload,
#: while the agent can still pick another file, instead of failing after "sending".
_UPLOAD_TYPES: dict[str, tuple[str, str, object]] = {
    "image/jpeg": ("image", "sendPhoto", lambda d: d[:3] == b"\xff\xd8\xff"),
    "image/png": ("image", "sendPhoto", lambda d: d[:8] == b"\x89PNG\r\n\x1a\n"),
    "image/gif": ("image", "sendPhoto", lambda d: d[:6] in (b"GIF87a", b"GIF89a")),
    "image/webp": ("image", "sendPhoto", lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP"),
    "video/mp4": ("video", "sendVideo", _ftyp),
    "audio/mpeg": (
        "audio",
        "sendAudio",
        lambda d: d[:3] == b"ID3" or d[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    ),
    "audio/mp4": ("audio", "sendAudio", _ftyp),
    "application/pdf": ("document", "sendDocument", lambda d: d[:5] == b"%PDF-"),
    "application/zip": ("document", "sendDocument", lambda d: d[:4] == b"PK\x03\x04"),
}


def check_upload(content_type: str | None, data: bytes) -> UploadSpec:
    """What an agent's upload is on Telegram, or TelegramLimitError naming why it is refused."""
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    known = _UPLOAD_TYPES.get(mime)
    if known is None:
        raise TelegramLimitError(
            "media_format",
            "Telegram delivers jpg/png/gif/webp images, mp4 video, mp3/m4a audio and pdf/zip "
            f"files sent by link; {mime or 'this file'} is not one of them",
        )
    kind, method, signature = known
    if not data:
        raise TelegramLimitError("media_empty", "the file is empty")
    if not signature(data):  # type: ignore[operator]
        raise TelegramLimitError("media_mismatch", "the file's content does not match its type")
    limit = MAX_BYTES[method]
    if len(data) > limit:
        raise TelegramLimitError(
            "media_size",
            f"a {kind} sent to Telegram is at most {limit // _MB} MB; this one is "
            f"{len(data) / _MB:.1f} MB",
        )
    return UploadSpec(mime=mime, kind=kind, size=len(data), method=method)
