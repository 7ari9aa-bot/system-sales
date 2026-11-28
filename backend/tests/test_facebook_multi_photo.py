"""A Page post with several pictures (Pages API: Posts + Photo).

Meta has no single call for it: each picture is first uploaded to /photos unpublished, which gives
a photo id, and one /feed post then lists those ids as attached_media. One picture keeps the plain
/photos route it always used.
"""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.applications.apparel.modules.conversations.gateway import facebook_pages as fp

CREDS = {"api_key": "tok", "account_id": "111"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _form(req: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(req.content.decode()).items()}


def _meta():
    """A Meta that numbers uploaded photos p1, p2, ... and records every request."""
    seen: list[tuple] = []

    def handler(req):
        form = _form(req)
        seen.append((req.method, req.url.path.rsplit("/", 2)[-2:], form))
        if req.url.path.endswith("/photos"):
            return httpx.Response(
                200, json={"id": f"p{sum(1 for s in seen if s[1][-1] == 'photos')}"}
            )
        return httpx.Response(200, json={"id": "111_77"})

    return seen, handler


@pytest.mark.asyncio
async def test_each_picture_is_uploaded_unpublished_then_one_post_lists_them():
    seen, handler = _meta()
    async with _client(handler) as c:
        out = await fp.facebook_pages.publish_post(
            CREDS, message="new shoes", photo_urls=["https://x/1.jpg", "https://x/2.jpg"], _client=c
        )
    assert out == "111_77"
    uploads = [s for s in seen if s[1][-1] == "photos"]
    assert [u[2] for u in uploads] == [
        {"url": "https://x/1.jpg", "published": "false"},
        {"url": "https://x/2.jpg", "published": "false"},
    ]
    feed = seen[-1]
    assert feed[1][-1] == "feed"
    assert feed[2]["message"] == "new shoes"
    assert json.loads(feed[2]["attached_media[0]"]) == {"media_fbid": "p1"}
    assert json.loads(feed[2]["attached_media[1]"]) == {"media_fbid": "p2"}
    assert "published" not in feed[2]


@pytest.mark.asyncio
async def test_a_scheduled_multi_photo_post_is_scheduled_on_the_feed_not_on_each_photo():
    seen, handler = _meta()
    import time

    when = int(time.time()) + 3600
    async with _client(handler) as c:
        await fp.facebook_pages.publish_post(
            CREDS, photo_urls=["https://x/1.jpg", "https://x/2.jpg"], schedule_at=when, _client=c
        )
    uploads = [s for s in seen if s[1][-1] == "photos"]
    assert all("scheduled_publish_time" not in u[2] for u in uploads)
    feed = seen[-1][2]
    assert feed["published"] == "false" and feed["scheduled_publish_time"] == str(when)


@pytest.mark.asyncio
async def test_one_picture_in_a_list_still_uses_the_single_photo_route():
    seen, handler = _meta()
    async with _client(handler) as c:
        await fp.facebook_pages.publish_post(
            CREDS, message="cap", photo_urls=["https://x/1.jpg"], _client=c
        )
    assert len(seen) == 1 and seen[0][1][-1] == "photos"
    assert seen[0][2] == {"caption": "cap", "url": "https://x/1.jpg"}


@pytest.mark.asyncio
async def test_too_many_pictures_or_a_link_alongside_never_leave_our_server():
    def handler(req):
        raise AssertionError("no request may be sent")

    many = [f"https://x/{i}.jpg" for i in range(fp.MAX_PHOTOS_PER_POST + 1)]
    async with _client(handler) as c:
        with pytest.raises(ValueError, match="at most"):
            await fp.facebook_pages.publish_post(CREDS, photo_urls=many, _client=c)
        with pytest.raises(ValueError, match="picture or a link"):
            await fp.facebook_pages.publish_post(
                CREDS,
                photo_urls=["https://x/1.jpg", "https://x/2.jpg"],
                link="https://a.co",
                _client=c,
            )
        with pytest.raises(ValueError, match="picture or a link"):
            await fp.facebook_pages.publish_post(
                CREDS, photo_url="https://x/1.jpg", photo_urls=["https://x/2.jpg"], _client=c
            )


@pytest.mark.asyncio
async def test_a_failed_upload_stops_before_any_post_is_made():
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if len(seen) == 2:
            return httpx.Response(400, json={"error": {"message": "bad image", "code": 100}})
        return httpx.Response(200, json={"id": "p1"})

    async with _client(handler) as c:
        with pytest.raises(Exception):  # noqa: B017 - the provider error type is asserted elsewhere
            await fp.facebook_pages.publish_post(
                CREDS, photo_urls=["https://x/1.jpg", "https://x/2.jpg"], _client=c
            )
    assert not any(p.endswith("/feed") for p in seen)


# ---- the service: several files held in storage just long enough for Facebook to fetch them ----
from types import SimpleNamespace  # noqa: E402

from app.core.errors import ConflictError, ValidationError  # noqa: E402
from app.applications.apparel.modules.conversations import facebook_service as fs  # noqa: E402
from app.applications.apparel.modules.conversations.facebook_service import FacebookService  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
PDF = b"%PDF-1.7 " + b"0" * 64


class _Storage:
    def __init__(self, *, configured=True, fail_on=None):
        self.configured = configured
        self.fail_on = fail_on
        self.stored: list = []
        self.deleted: list = []

    async def store(self, media, *, prefix):
        if self.fail_on is not None and len(self.stored) == self.fail_on:
            raise RuntimeError("bucket down")
        self.stored.append(media)
        return SimpleNamespace(storage_key=f"k{len(self.stored)}")

    def signed_url(self, key, *, expires_in=None):
        return f"https://files.example/{key}"

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


async def test_every_file_gets_its_own_short_link_and_all_are_removed(monkeypatch):
    storage = _Storage()
    sent = _wire(monkeypatch, storage)
    out = await FacebookService.publish_pictures(None, "t1", {}, pictures=[PNG, JPEG], message="hi")
    assert out == "111_222"
    assert sent["photo_urls"] == ["https://files.example/k1", "https://files.example/k2"]
    assert sent["message"] == "hi" and "photo_url" not in sent
    assert sorted(storage.deleted) == ["k1", "k2"]


async def test_the_files_are_removed_even_when_facebook_refuses(monkeypatch):
    storage = _Storage()
    _wire(monkeypatch, storage, fail_with=ValueError("Facebook said no"))
    with pytest.raises(ValidationError, match="Facebook said no"):
        await FacebookService.publish_pictures(None, "t", {}, pictures=[PNG, JPEG])
    assert sorted(storage.deleted) == ["k1", "k2"]


async def test_a_storage_failure_on_the_second_file_still_cleans_up_the_first(monkeypatch):
    storage = _Storage(fail_on=1)
    _wire(monkeypatch, storage)
    with pytest.raises(RuntimeError):
        await FacebookService.publish_pictures(None, "t", {}, pictures=[PNG, JPEG])
    assert storage.deleted == ["k1"]


async def test_one_bad_file_refuses_the_whole_post_before_anything_is_stored(monkeypatch):
    storage = _Storage()
    _wire(monkeypatch, storage)
    with pytest.raises(ValidationError):
        await FacebookService.publish_pictures(None, "t", {}, pictures=[PNG, PDF])
    assert storage.stored == []


async def test_too_many_files_are_refused_before_anything_is_stored(monkeypatch):
    storage = _Storage()
    _wire(monkeypatch, storage)
    with pytest.raises(ValidationError, match="at most"):
        await FacebookService.publish_pictures(None, "t", {}, pictures=[PNG] * 11)
    assert storage.stored == []


async def test_without_storage_the_post_is_refused(monkeypatch):
    _wire(monkeypatch, _Storage(configured=False))
    with pytest.raises(ConflictError, match="storage"):
        await FacebookService.publish_pictures(None, "t", {}, pictures=[PNG, JPEG])


# ---- the request: pictures ride in the JSON body as base64, so the limit must hold an album ----
from app.core.middleware import MAX_BODY_BYTES, MAX_FACEBOOK_POST_BYTES  # noqa: E402
from app.applications.apparel.modules.conversations.facebook_service import MAX_PICTURE_BYTES  # noqa: E402
from app.applications.apparel.modules.conversations.routers.facebook_pages import PublishRequest  # noqa: E402


def test_the_body_limit_holds_the_largest_album():
    one = (
        -(-MAX_PICTURE_BYTES // 3) * 4
    ) + 8  # base64 of a full picture, plus its quotes and comma
    largest = one * fp.MAX_PHOTOS_PER_POST + 63206 * 4 + 1024
    assert largest <= MAX_FACEBOOK_POST_BYTES
    assert MAX_FACEBOOK_POST_BYTES > MAX_BODY_BYTES


def test_a_request_takes_a_list_of_pictures_and_no_more_than_the_album_limit():
    ok = PublishRequest(message="hi", pictures=["QQ=="] * fp.MAX_PHOTOS_PER_POST)
    assert len(ok.pictures) == fp.MAX_PHOTOS_PER_POST
    with pytest.raises(ValueError):
        PublishRequest(pictures=["QQ=="] * (fp.MAX_PHOTOS_PER_POST + 1))
