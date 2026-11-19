"""What a Messenger Page may attach to a message, and how — one place, no network.

Taken from Meta's Messenger Platform "Saving assets" page (updated 17 Jun 2026): an attachment is
`image`, `audio`, `video` or `file`; sent by link, an image is at most 8 MB and every other type
25 MB. Nothing is saved for reuse: the file is sent in the same call (no `is_reusable`), so there
is no attachment id that expires after 90 days.
"""

from __future__ import annotations

_MB = 1024 * 1024

#: Per attachment type, the largest file Messenger fetches from a link.
MAX_BYTES = {"image": 8 * _MB, "audio": 25 * _MB, "video": 25 * _MB, "file": 25 * _MB}

# What the inbox and the upload endpoint call a kind of media -> the Send API's attachment type.
_KIND_ALIASES = {
    "image": "image",
    "photo": "image",
    "sticker": "image",
    "audio": "audio",
    "voice": "audio",
    "video": "video",
    "file": "file",
    "document": "file",
}


class MessengerLimitError(ValueError):
    """The message breaks a rule Messenger would refuse it for. Caught before any call."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def attachment_type(raw: str | None) -> str:
    """The Send API attachment type for what the inbox calls this media.

    An unknown kind is a `file`, never an `image`: Messenger answers a wrong type with an error
    (a PDF sent as an image), while a `file` always arrives and can be opened.
    """
    return _KIND_ALIASES.get(str(raw or "file").lower(), "file")


def check_attachment(url: str, kind: str, size_bytes: int | None = None) -> None:
    """Refuse a link or size Messenger would refuse. Size is checked only when known."""
    if kind not in MAX_BYTES:
        raise MessengerLimitError("media_kind", f"Messenger cannot send {kind!r} attachments")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise MessengerLimitError("media_url", "the attachment must be a public https link")
    limit = MAX_BYTES[kind]
    if size_bytes is not None and size_bytes > limit:
        raise MessengerLimitError(
            "media_size",
            f"a {kind} sent to Messenger is at most {limit // _MB} MB; this one is "
            f"{size_bytes / _MB:.1f} MB",
        )


# ------------------------------------------------------------- an agent's upload

from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True, slots=True)
class UploadSpec:
    mime: str
    kind: str  # the Send API attachment type: image | audio | video | file
    size: int


def _ftyp(d: bytes) -> bool:
    return len(d) >= 12 and d[4:8] == b"ftyp"


#: The type of each file Messenger shows as more than a bare download, with the first bytes that
#: prove it (the declared type is only a claim). Anything else is sent as a plain `file`.
_UPLOAD_KINDS: dict[str, tuple[str, object]] = {
    "image/jpeg": ("image", lambda d: d[:3] == b"\xff\xd8\xff"),
    "image/png": ("image", lambda d: d[:8] == b"\x89PNG\r\n\x1a\n"),
    "image/gif": ("image", lambda d: d[:6] in (b"GIF87a", b"GIF89a")),
    "image/webp": ("image", lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP"),
    "audio/mpeg": (
        "audio",
        lambda d: d[:3] == b"ID3" or d[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    ),
    "audio/mp4": ("audio", _ftyp),
    "audio/aac": ("audio", lambda d: d[:2] in (b"\xff\xf1", b"\xff\xf9")),
    "audio/wav": ("audio", lambda d: d[:4] == b"RIFF" and d[8:12] == b"WAVE"),
    "video/mp4": ("video", _ftyp),
    "video/quicktime": ("video", _ftyp),
    "video/webm": ("video", lambda d: d[:4] == b"\x1a\x45\xdf\xa3"),
}

#: Types a browser never lets an agent send as a document: a page or a program is not a file a
#: customer should be handed, and SVG/HTML run script when opened.
_NEVER = frozenset(
    {
        "text/html",
        "image/svg+xml",
        "application/x-msdownload",
        "application/x-sh",
        "application/x-dosexec",
        "application/javascript",
        "text/javascript",
    }
)


def check_upload(content_type: str | None, data: bytes) -> UploadSpec:
    """What an agent's upload is on Messenger, or MessengerLimitError naming why it is refused."""
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if not mime or mime in _NEVER:
        raise MessengerLimitError("media_format", f"{mime or 'this file'} cannot be sent")
    if not data:
        raise MessengerLimitError("media_empty", "the file is empty")
    known = _UPLOAD_KINDS.get(mime)
    if known is not None:
        kind, signature = known
        if not signature(data):  # type: ignore[operator]
            raise MessengerLimitError(
                "media_mismatch", "the file's content does not match its type"
            )
    else:
        kind = "file"
    limit = MAX_BYTES[kind]
    if len(data) > limit:
        raise MessengerLimitError(
            "media_size",
            f"a {kind} is at most {limit // _MB} MB on Messenger; this one is "
            f"{len(data) / _MB:.1f} MB",
        )
    return UploadSpec(mime=mime, kind=kind, size=len(data))
