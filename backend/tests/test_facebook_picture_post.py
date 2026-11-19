"""A Facebook post can carry a picture FILE, not only a link someone else hosts.

The file waits in private storage just long enough for Facebook to fetch it through a short signed
link, and is removed afterwards whatever happens. Its type is read from its own bytes.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from app.core.errors import ConflictError, ValidationError
from app.core.middleware import (
    MAX_BODY_BYTES,
    MAX_FACEBOOK_POST_BYTES,
    BodySizeLimitMiddleware,
)
from app.modules.conversations import facebook_service as fs
from app.modules.conversations.facebook_service import (
    MAX_PICTURE_BYTES,
    FacebookService,
    picture_kind,
)
from app.modules.conversations.routers.facebook_pages import PublishRequest, _decode_picture

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
GIF = b"GIF89a" + b"0" * 64
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"0" * 32
PDF = b"%PDF-1.7 " + b"0" * 64


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (GIF, "image/gif"),
        (b"GIF87a" + b"0" * 9, "image/gif"),
        (b"BM" + b"0" * 30, "image/bmp"),
        (WEBP, "image/webp"),
        (PDF, None),
        (b"<svg xmlns='x'></svg>", None),
        (b"RIFF\x10\x00\x00\x00WAVEfmt ", None),
        (b"", None),
    ],
)
def test_the_type_comes_from_the_bytes(data, kind):
    assert picture_kind(data) == kind


def test_check_picture_refuses_empty_oversized_and_unknown_files():
    assert FacebookService.check_picture(PNG) == "image/png"
    with pytest.raises(ValidationError, match="empty"):
        FacebookService.check_picture(b"")
    with pytest.raises(ValidationError, match="4 MB"):
        FacebookService.check_picture(JPEG + b"0" * MAX_PICTURE_BYTES)
    with pytest.raises(ValidationError, match="JPEG, PNG"):
        FacebookService.check_picture(PDF)
    # exactly at the limit is fine
    assert FacebookService.check_picture(JPEG + b"0" * (MAX_PICTURE_BYTES - len(JPEG)))


class _Storage:
    def __init__(self, *, configured=True, key="social-outbox/t/abc"):
        self.configured = configured
        self.key = key
        self.stored: list = []
        self.deleted: list = []
        self.link_ttl = None

    async def store(self, media, *, prefix):
        self.stored.append((media, prefix))
        return SimpleNamespace(storage_key=self.key)

    def signed_url(self, key, *, expires_in=None):
        self.link_ttl = expires_in
        return f"https://files.example/{key}?sig=1"

    async def delete_objects(self, keys):
        self.deleted.extend(keys)
        return list(keys)


def _wire(monkeypatch, storage, *, fail_with=None):
    sent: dict = {}

    async def publish_post(credentials, **kw):
        sent.update(kw)
        if fail_with:
            raise fail_with
        return "111_222"

    async def sync(*a, **k):
        return 0

    monkeypatch.setattr(fs, "get_storage", lambda: storage)
    monkeypatch.setattr(fs.facebook_pages, "publish_post", publish_post)
    monkeypatch.setattr(FacebookService, "sync_posts", staticmethod(sync))
    return sent


async def test_the_file_goes_through_a_short_signed_link_and_is_then_removed(monkeypatch):
    storage = _Storage()
    sent = _wire(monkeypatch, storage)
    post_id = await FacebookService.publish_picture(
        None, "tenant-1", {}, picture=PNG, message="hello"
    )
    assert post_id == "111_222"
    media, prefix = storage.stored[0]
    assert media.data == PNG and media.content_type == "image/png"
    assert prefix == "social-outbox/tenant-1"
    # Facebook is handed the signed link, never the bytes, and the link is short-lived
    assert sent["photo_url"] == "https://files.example/social-outbox/t/abc?sig=1"
    assert sent["message"] == "hello"
    assert storage.link_ttl == fs.PICTURE_LINK_SECONDS <= 900
    assert storage.deleted == ["social-outbox/t/abc"]


async def test_the_file_is_removed_even_when_facebook_refuses_it(monkeypatch):
    storage = _Storage()
    _wire(monkeypatch, storage, fail_with=ValueError("Facebook said no"))
    with pytest.raises(ValidationError, match="Facebook said no"):
        await FacebookService.publish_picture(None, "t", {}, picture=JPEG)
    assert storage.deleted == ["social-outbox/t/abc"]


async def test_a_failed_cleanup_never_hides_the_result(monkeypatch):
    storage = _Storage()
    _wire(monkeypatch, storage)

    async def boom(keys):
        raise RuntimeError("bucket down")

    storage.delete_objects = boom
    assert await FacebookService.publish_picture(None, "t", {}, picture=JPEG) == "111_222"


async def test_a_bad_file_is_refused_before_anything_is_stored(monkeypatch):
    storage = _Storage()
    _wire(monkeypatch, storage)
    with pytest.raises(ValidationError):
        await FacebookService.publish_picture(None, "t", {}, picture=PDF)
    assert storage.stored == []


async def test_without_storage_the_post_is_refused_not_silently_dropped(monkeypatch):
    storage = _Storage(configured=False)
    _wire(monkeypatch, storage)
    with pytest.raises(ConflictError, match="storage"):
        await FacebookService.publish_picture(None, "t", {}, picture=JPEG)
    assert storage.stored == []


async def test_a_scheduled_picture_keeps_its_time(monkeypatch):
    storage = _Storage()
    sent = _wire(monkeypatch, storage)
    when = object()
    await FacebookService.publish_picture(None, "t", {}, picture=JPEG, schedule_at=when)
    assert sent["schedule_at"] is when


def test_the_route_decodes_plain_base64_and_browser_data_urls():
    raw = base64.b64encode(PNG).decode()
    assert _decode_picture(raw) == PNG
    assert _decode_picture(f"data:image/png;base64,{raw}") == PNG
    with pytest.raises(ValidationError, match="base64"):
        _decode_picture("not base64 !!")


def test_the_request_refuses_a_picture_bigger_than_facebook_allows():
    big = base64.b64encode(b"0" * (MAX_PICTURE_BYTES * 2)).decode()
    with pytest.raises(ValueError):
        PublishRequest(picture=big)
    ok = base64.b64encode(b"0" * MAX_PICTURE_BYTES).decode()
    assert PublishRequest(picture=ok).picture == ok


async def _status(method: str, path: str, size: int) -> int:
    sent: list[dict] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"x" * size, "more_body": False}

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"content-length", str(size).encode())],
    }
    await BodySizeLimitMiddleware(app)(scope, receive, send)
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_the_body_limit_holds_the_largest_picture_post():
    largest = (-(-MAX_PICTURE_BYTES // 3) * 4) + 63206 * 4 + 1024  # base64 + 4-byte chars of text
    assert largest <= MAX_FACEBOOK_POST_BYTES
    assert MAX_FACEBOOK_POST_BYTES > MAX_BODY_BYTES


@pytest.mark.parametrize("size_mb", [2, 5])
async def test_a_real_photo_post_is_not_refused_as_too_large(size_mb):
    assert await _status("POST", "/api/v1/facebook/posts", size_mb * 1024 * 1024) == 200


async def test_the_larger_limit_is_only_for_publishing():
    assert await _status("POST", "/api/v1/facebook/posts", MAX_FACEBOOK_POST_BYTES + 1) == 413
    for method, path in [
        ("POST", "/api/v1/facebook/posts/1_2/comments"),
        ("PATCH", "/api/v1/facebook/posts"),
        ("POST", "/api/v1/facebook/objects/1/comments"),
    ]:
        assert await _status(method, path, 2 * 1024 * 1024) == 413, path
