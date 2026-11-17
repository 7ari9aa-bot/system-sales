"""Media an agent sends TO a customer (the mirror of inbound ``media.py``).

The upload endpoint stores the bytes first and returns a ``media_id``; the send
request then names that id. Splitting the two keeps the message request a small
JSON body, lets the agent see an upload fail before anything is sent, and means
a message never points at a file that is not durably stored.

Everything here is pure (no database, no network) so the rules are tested alone.
The limits are WhatsApp Cloud API's own: a file above them is accepted by our
bucket but rejected by Meta, which the agent would learn only after "sending".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.errors import ValidationError

MB = 1024 * 1024

# WhatsApp Cloud API ceilings per kind (documented by Meta). Documents are
# allowed up to 100 MB by Meta; we stop at our storage cap (25 MB) instead.
MAX_BYTES = {
    "image": 5 * MB,
    "sticker": 100 * 1024,  # a static WebP sticker; an animated one is 500 KB
    "audio": 16 * MB,
    "video": 16 * MB,
    "document": 25 * MB,
}
ABSOLUTE_MAX_BYTES = max(MAX_BYTES.values())

# Only the types WhatsApp itself delivers. Anything else (SVG, HTML, executables,
# archives) is refused even though our bucket would store it.
_KIND_BY_MIME = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "audio/aac": "audio",
    "audio/mp4": "audio",
    "audio/mpeg": "audio",
    "audio/amr": "audio",
    "audio/ogg": "audio",
    "video/mp4": "video",
    "video/3gpp": "video",
    "application/pdf": "document",
    "text/plain": "document",
    "application/msword": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.ms-powerpoint": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
}


def _riff_webp(d: bytes) -> bool:
    return len(d) >= 12 and d[:4] == b"RIFF" and d[8:12] == b"WEBP"


def _ftyp(d: bytes) -> bool:
    return len(d) >= 12 and d[4:8] == b"ftyp"


def _ogg_opus(d: bytes) -> bool:
    return d[:4] == b"OggS"


# What the first bytes of each type must look like. The declared Content-Type is
# the sender's claim; this is the check that it is true.
_SIGNATURE = {
    "image/jpeg": lambda d: d[:3] == b"\xff\xd8\xff",
    "image/png": lambda d: d[:8] == b"\x89PNG\r\n\x1a\n",
    "image/webp": _riff_webp,
    "audio/aac": lambda d: d[:2] in (b"\xff\xf1", b"\xff\xf9"),
    "audio/mp4": _ftyp,
    "audio/mpeg": lambda d: d[:3] == b"ID3" or d[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    "audio/amr": lambda d: d[:5] == b"#!AMR",
    "audio/ogg": _ogg_opus,
    "video/mp4": _ftyp,
    "video/3gpp": _ftyp,
    "application/pdf": lambda d: d[:5] == b"%PDF-",
    "application/msword": lambda d: d[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    "application/vnd.ms-excel": lambda d: d[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    "application/vnd.ms-powerpoint": lambda d: d[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    # OOXML files are zip containers.
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": lambda d: (
        d[:2] == b"PK"
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": lambda d: d[:2] == b"PK",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": lambda d: (
        d[:2] == b"PK"
    ),
    # Plain text has no signature; it is checked for NUL bytes instead.
    "text/plain": lambda d: b"\x00" not in d[:4096],
}

# A caption exists only for these kinds; Meta rejects one on audio.
CAPTION_KINDS = frozenset({"image", "video", "document"})
CAPTION_MAX = 1024  # Meta's caption limit (a text body allows 4096)

_FILENAME_BAD = re.compile(r"[\x00-\x1f\x7f/\\:*?\"<>|]+")


@dataclass(frozen=True)
class OutboundMediaSpec:
    mime: str
    kind: str  # image | sticker | audio | video | document
    size: int
    filename: str


def normalize_mime(value: str | None) -> str:
    mime = (value or "").split(";")[0].strip().lower()
    return "image/jpeg" if mime == "image/jpg" else mime


def safe_filename(value: str | None, *, fallback: str = "file") -> str:
    """A file name safe to show and to send: no path, no control characters, bounded."""
    name = _FILENAME_BAD.sub("_", (value or "").strip()).strip(" .")
    name = name[-120:]
    return name or fallback


def check_outbound_media(
    *, content_type: str | None, data: bytes, filename: str | None, as_sticker: bool = False
) -> OutboundMediaSpec:
    """Validate an agent's upload and say what it is. Raises ``ValidationError``.

    ``as_sticker`` is the agent's intent (a WebP can be a photo or a sticker);
    only a WebP can be one.
    """
    mime = normalize_mime(content_type)
    kind = _KIND_BY_MIME.get(mime)
    if kind is None:
        raise ValidationError(
            f"{mime or 'this file type'} cannot be sent on WhatsApp",
            details={"reason": "unsupported_type", "content_type": mime},
        )
    if not data:
        raise ValidationError("the file is empty", details={"reason": "empty"})
    if not _SIGNATURE[mime](data):
        raise ValidationError(
            "the file's content does not match its type",
            details={"reason": "content_mismatch", "content_type": mime},
        )
    if as_sticker:
        if mime != "image/webp":
            raise ValidationError(
                "a sticker must be a WebP image", details={"reason": "sticker_needs_webp"}
            )
        kind = "sticker"
    limit = MAX_BYTES[kind]
    if len(data) > limit:
        raise ValidationError(
            f"a {kind} can be at most {limit // 1024} KB on WhatsApp"
            if limit < MB
            else f"a {kind} can be at most {limit // MB} MB on WhatsApp",
            details={"reason": "too_large", "kind": kind, "max_bytes": limit, "size": len(data)},
        )
    return OutboundMediaSpec(mime=mime, kind=kind, size=len(data), filename=safe_filename(filename))


def content_type_for(kind: str) -> str:
    """The canonical ``messages.content_type`` for a kind (matches inbound's §155 vocabulary)."""
    return {
        "image": "image",
        "sticker": "image",
        "audio": "voice",
        "video": "video",
        "document": "file",
    }[kind]


def whatsapp_media_type(kind: str) -> str:
    """The Cloud API ``type`` field for a kind."""
    return kind  # image | sticker | audio | video | document


def check_caption(kind: str, caption: str | None) -> str | None:
    """A caption is allowed on images, videos and documents only, up to 1024 characters."""
    text = (caption or "").strip()
    if not text:
        return None
    if kind not in CAPTION_KINDS:
        raise ValidationError(
            f"a {kind} cannot have a caption on WhatsApp", details={"reason": "caption_not_allowed"}
        )
    if len(text) > CAPTION_MAX:
        raise ValidationError(
            f"a caption can be at most {CAPTION_MAX} characters",
            details={"reason": "caption_too_long", "max": CAPTION_MAX},
        )
    return text
