"""A staff user's own profile picture: screened before the bucket, signed on read.

The picture belongs to the account, not to a tenant — `users` is a global table
and one person can sit in several workspaces. Two rules follow from that: the
bytes decide what the file is (never the header alone), and the URL handed to a
browser is a short-lived read URL, not a permanent public one.

Replacing or clearing a picture leaves the old object in the bucket: nothing
today reclaims `avatars/` keys, and a delete issued inside the request would run
ahead of a transaction that can still roll back. One small object per upload is
the known cost of that choice, and it is the thing to revisit if uploads ever
become frequent enough for it to matter.
"""

from __future__ import annotations

from app.core.errors import PayloadTooLargeError, ValidationError
from app.core.storage import ObjectStorage, get_storage

MAX_AVATAR_BYTES = 5 * 1024 * 1024
READ_URL_TTL_SECONDS = 24 * 60 * 60


def _is_webp(data: bytes) -> bool:
    return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"


_SIGNATURES = {
    # The header only chooses which signature to check; the bytes decide.
    "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) > 12,
    "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
    "image/webp": _is_webp,
}


def screen(content_type: str, data: bytes) -> str:
    """Return the type this byte string really is, or refuse the upload."""
    if len(data) > MAX_AVATAR_BYTES:
        raise PayloadTooLargeError(f"an avatar must be at most {MAX_AVATAR_BYTES} bytes")
    signature = _SIGNATURES.get(content_type)
    if signature is None or not signature(data):
        raise ValidationError("the avatar must be a PNG, JPEG or WebP image")
    return content_type


def read_url(value: str | None, *, storage: ObjectStorage | None = None) -> str | None:
    """The stored key as a URL the browser can load, or None.

    None is the honest answer when storage is unavailable: the client falls back
    to the account's letters instead of showing a broken image.
    """
    if not value:
        return None
    if not value.startswith("s3://"):
        return value
    store = storage if storage is not None else get_storage()
    if not store.configured:
        return None
    try:
        return store.signed_url(value[len("s3://") :], expires_in=READ_URL_TTL_SECONDS)
    except (RuntimeError, ValueError):
        return None
