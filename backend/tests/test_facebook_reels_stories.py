"""Reels and Stories for a Facebook Page, against Meta's own rules.

Sources: "Reels Publishing API" and "Facebook Stories API" (developers.facebook.com). The video
fixtures are real mp4 files made by ffmpeg; their size and length were checked with ffprobe.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.errors import ConflictError, ExternalProviderError, ValidationError
from app.core.middleware import (
    MAX_BODY_BYTES,
    MAX_FACEBOOK_VIDEO_UPLOAD_BYTES,
    BodySizeLimitMiddleware,
)
from app.applications.apparel.modules.conversations import facebook_service as fs
from app.applications.apparel.modules.conversations.facebook_service import FacebookService
from app.applications.apparel.modules.conversations.gateway import facebook_pages as fp
from app.applications.apparel.modules.conversations.gateway import facebook_video as fv

FIX = Path(__file__).parent / "fixtures"
CREDS = {"api_key": "page-token", "account_id": "111"}
MB = 1024 * 1024


def _video(name: str) -> bytes:
    return (FIX / name).read_bytes()


REEL = _video("reel_540x960_5s.mp4")
PHONE = _video("reel_rotated_phone.mp4")
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
TIFF = b"II*\x00" + b"0" * 64


# ------------------------------------------------------------------ reading the file


def test_the_reader_gives_the_size_and_length_ffprobe_gave():
    info = fv.read_mp4(REEL)
    assert (info.width, info.height, round(info.seconds, 1)) == (540, 960, 5.0)
    assert fv.read_mp4(_video("video_70s.mp4")).seconds == pytest.approx(70.0, abs=0.1)
    assert (fv.read_mp4(_video("video_360x640.mp4")).width, 360) == (360, 360)


def test_a_phone_video_stored_sideways_is_read_the_way_it_plays():
    """A phone stores 1920x1080 and tags it turned a quarter; it plays as 1080x1920."""
    info = fv.read_mp4(PHONE)
    assert (info.width, info.height) == (1080, 1920)
    fv.check_reel(PHONE)  # without the turn it would be refused as wide


def test_a_file_that_is_not_an_mp4_or_is_cut_short_is_refused_with_a_reason():
    with pytest.raises(fv.FacebookVideoError) as e:
        fv.read_mp4(b"%PDF-1.7 " + b"0" * 64)
    assert e.value.code == "video_format"
    with pytest.raises(fv.FacebookVideoError) as e:
        fv.read_mp4(b"")
    assert e.value.code == "video_format"
    # the header (moov) is what a cut-off upload loses
    cut = REEL[: REEL.index(b"moov") - 4]
    with pytest.raises(fv.FacebookVideoError) as e:
        fv.read_mp4(cut)
    assert e.value.code == "video_unreadable"


def test_garbage_after_a_valid_start_never_crashes_the_reader():
    for tail in (b"\xff" * 200, b"\x00" * 200, b"moov" + b"\xff" * 50):
        try:
            fv.read_mp4(REEL[:32] + tail)
        except fv.FacebookVideoError:
            pass


# ------------------------------------------------------------------ Meta's rules


def test_a_good_reel_and_story_are_accepted():
    assert fv.check_reel(REEL).seconds == pytest.approx(5.0, abs=0.1)
    assert fv.check_video_story(REEL).height == 960


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("video_landscape.mp4", "video_ratio"),  # wide, not 9:16
        ("video_360x640.mp4", "video_resolution"),  # under 540 x 960
        ("video_2s.mp4", "video_short"),  # under 3 seconds
    ],
)
def test_what_meta_refuses_is_refused_here_first(fixture, code):
    with pytest.raises(fv.FacebookVideoError) as e:
        fv.check_reel(_video(fixture))
    assert e.value.code == code


def test_a_story_is_at_most_60_seconds_but_a_reel_may_be_90():
    seventy = _video("video_70s.mp4")
    assert fv.check_reel(seventy).seconds > 60  # fine as a Reel
    with pytest.raises(fv.FacebookVideoError) as e:
        fv.check_video_story(seventy)
    assert e.value.code == "video_long"
    assert "60" in str(e.value)


def test_an_empty_video_is_refused():
    with pytest.raises(fv.FacebookVideoError) as e:
        fv.check_reel(b"")
    assert e.value.code == "video_empty"


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (TIFF, "image/tiff"),
        (b"BM" + b"0" * 30, "image/bmp"),
    ],
)
def test_a_photo_story_takes_what_meta_lists(data, kind):
    assert fv.check_story_photo(data) == kind


def test_a_photo_story_refuses_webp_pdf_empty_and_over_10_mb():
    for bad, code in (
        (b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"0" * 32, "photo_format"),  # Meta does not list WEBP
        (b"%PDF-1.7 " + b"0" * 30, "photo_format"),
        (b"", "photo_empty"),
        (JPEG + b"0" * (10 * MB), "photo_size"),
    ):
        with pytest.raises(fv.FacebookVideoError) as e:
            fv.check_story_photo(bad)
        assert e.value.code == code
    fv.check_story_photo(JPEG + b"0" * (10 * MB - len(JPEG)))  # exactly 10 MB is fine


# ------------------------------------------------------------------ the calls to Meta


def _form(req: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(req.content.decode()).items()}


class _Meta:
    """A Meta that follows the documented order and records every call."""

    def __init__(self, *, status_script=None, upload_ok=True):
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.status_script = list(status_script or [])
        self.upload_ok = upload_ok

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        form = _form(req) if req.method == "POST" and "rupload" not in str(req.url) else {}
        self.calls.append((req.method, str(req.url.host) + path, form, dict(req.headers)))
        if "rupload.facebook.com" in str(req.url):
            return httpx.Response(200, json={"success": self.upload_ok})
        if (
            path.endswith(("/video_reels", "/video_stories"))
            and form.get("upload_phase") == "start"
        ):
            vid = "9001"
            return httpx.Response(
                200, json={"video_id": vid, "upload_url": f"{fp.UPLOAD_HOST}/v27.0/{vid}"}
            )
        if req.method == "GET" and path.endswith("/9001"):
            step = self.status_script.pop(0) if self.status_script else DONE
            return httpx.Response(200, json={"status": step})
        if path.endswith("/photos"):
            return httpx.Response(200, json={"id": "photo-7"})
        if path.endswith("/photo_stories"):
            return httpx.Response(200, json={"success": True, "post_id": "story-photo-1"})
        if path.endswith("/video_stories"):
            return httpx.Response(200, json={"success": True, "post_id": "story-video-1"})
        if path.endswith("/video_reels"):
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"error": {"message": f"unexpected {req.method} {path}"}})


DONE = {
    "video_status": "ready",
    "uploading_phase": {"status": "complete"},
    "processing_phase": {"status": "complete"},
}
BUSY = {
    "video_status": "processing",
    "uploading_phase": {"status": "complete"},
    "processing_phase": {"status": "in_progress"},
}


async def _no_sleep(_):
    return None


def _client(meta: _Meta):
    return httpx.AsyncClient(transport=httpx.MockTransport(meta.handler))


async def test_a_reel_follows_meta_start_then_upload_then_wait_then_publish():
    meta = _Meta(status_script=[BUSY, BUSY, DONE])
    async with _client(meta) as c:
        vid = await fp.facebook_pages.publish_reel(
            CREDS,
            video_url="https://files.example/v.mp4",
            description="Hello #sale",
            _client=c,
            _sleep=_no_sleep,
        )
    assert vid == "9001"
    first = meta.calls[0]
    assert first[0] == "POST" and first[1].startswith("graph.facebook.com/")
    assert first[1].endswith("/111/video_reels")
    assert meta.calls[0][2] == {"upload_phase": "start"}
    # the file is handed over to Meta's upload host with the page token and the link, no bytes
    upload = meta.calls[1]
    assert upload[1].startswith("rupload.facebook.com/video-upload/")
    assert upload[3]["authorization"] == "OAuth page-token"
    assert upload[3]["file_url"] == "https://files.example/v.mp4"
    # status is asked until it is done, THEN the Reel is published
    statuses = [c for c in meta.calls if c[0] == "GET"]
    assert len(statuses) == 3
    final = meta.calls[-1]
    assert final[1].endswith("/111/video_reels")
    assert final[2] == {
        "upload_phase": "finish",
        "video_state": "PUBLISHED",
        "description": "Hello #sale",
        "video_id": "9001",
    }


async def test_a_scheduled_reel_is_sent_as_scheduled_with_its_time():
    meta = _Meta()
    when = int(time.time()) + 3600
    async with _client(meta) as c:
        await fp.facebook_pages.publish_reel(
            CREDS, video_url="https://f/v.mp4", schedule_at=when, _client=c, _sleep=_no_sleep
        )
    final = meta.calls[-1][2]
    assert final["video_state"] == "SCHEDULED" and final["scheduled_publish_time"] == str(when)


@pytest.mark.parametrize(("offset", "match"), [(300, "10 minutes"), (30 * 24 * 3600, "29 days")])
async def test_a_reel_time_outside_meta_window_is_refused_before_any_call(offset, match):
    meta = _Meta()
    async with _client(meta) as c:
        with pytest.raises(ValueError, match=match):
            await fp.facebook_pages.publish_reel(
                CREDS, video_url="https://f/v.mp4", schedule_at=int(time.time()) + offset, _client=c
            )
    assert meta.calls == []  # not even the upload session was opened


async def test_meta_processing_error_is_passed_on_in_its_own_words():
    meta = _Meta(
        status_script=[
            {
                "video_status": "processing",
                "uploading_phase": {"status": "complete"},
                "processing_phase": {
                    "status": "not_started",
                    "error": {
                        "message": "Resolution too low. Video must have a minimum resolution of 540p."  # noqa: E501
                    },
                },
            }
        ]
    )
    async with _client(meta) as c:
        with pytest.raises(ExternalProviderError, match="Resolution too low"):
            await fp.facebook_pages.publish_reel(
                CREDS, video_url="https://f/v.mp4", _client=c, _sleep=_no_sleep
            )
    # nothing was published
    assert not any(
        p.endswith("/111/video_reels") and f.get("upload_phase") == "finish"
        for _, p, f, _ in meta.calls
    )


async def test_a_video_meta_never_finishes_processing_gives_up_instead_of_waiting_forever():
    meta = _Meta(status_script=[BUSY] * 500)
    slept = []

    async def sleep(s):
        slept.append(s)

    async with _client(meta) as c:
        with pytest.raises(ExternalProviderError, match="still processing"):
            await fp.facebook_pages.publish_reel(
                CREDS, video_url="https://f/v.mp4", _client=c, _sleep=sleep
            )
    assert sum(slept) == fp.PROCESSING_TIMEOUT_SECONDS


@pytest.mark.parametrize("state", ["error", "upload_failed", "expired"])
async def test_a_dead_video_status_stops_the_wait(state):
    meta = _Meta(status_script=[{"video_status": state}])
    async with _client(meta) as c:
        with pytest.raises(ExternalProviderError, match=state):
            await fp.facebook_pages.publish_reel(
                CREDS, video_url="https://f/v.mp4", _client=c, _sleep=_no_sleep
            )


async def test_the_token_is_never_sent_to_an_address_meta_did_not_name():
    class Evil(_Meta):
        def handler(self, req):
            if req.method == "POST" and _form(req).get("upload_phase") == "start":
                return httpx.Response(
                    200, json={"video_id": "9001", "upload_url": "https://evil.example/steal"}
                )
            return super().handler(req)

    meta = Evil()
    async with _client(meta) as c:
        with pytest.raises(ExternalProviderError, match="unexpected upload address"):
            await fp.facebook_pages.publish_reel(
                CREDS, video_url="https://f/v.mp4", _client=c, _sleep=_no_sleep
            )
    assert not any("evil.example" in p for _, p, _, _ in meta.calls)


async def test_an_upload_meta_refuses_is_an_error_not_a_silent_success():
    meta = _Meta(upload_ok=False)
    async with _client(meta) as c:
        with pytest.raises(ExternalProviderError, match="upload failed"):
            await fp.facebook_pages.publish_reel(
                CREDS, video_url="https://f/v.mp4", _client=c, _sleep=_no_sleep
            )


async def test_a_video_story_follows_the_same_steps_and_returns_the_story_id():
    meta = _Meta()
    async with _client(meta) as c:
        sid = await fp.facebook_pages.publish_video_story(
            CREDS, video_url="https://f/v.mp4", _client=c, _sleep=_no_sleep
        )
    assert sid == "story-video-1"
    assert meta.calls[0][1].endswith("/111/video_stories")
    assert meta.calls[-1][1].endswith("/111/video_stories")
    assert meta.calls[-1][2] == {"video_id": "9001", "upload_phase": "finish"}


async def test_a_photo_story_uploads_the_picture_unpublished_then_makes_it_a_story():
    meta = _Meta()
    async with _client(meta) as c:
        sid = await fp.facebook_pages.publish_photo_story(
            CREDS, photo_url="https://f/p.jpg", _client=c
        )
    assert sid == "story-photo-1"
    (_, p1, f1, _), (_, p2, f2, _) = meta.calls
    assert p1.endswith("/111/photos") and f1 == {"url": "https://f/p.jpg", "published": "false"}
    assert p2.endswith("/111/photo_stories") and f2 == {"photo_id": "photo-7"}


async def test_the_lists_read_the_reels_and_stories_edges():
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if req.url.path.endswith("/video_reels"):
            return httpx.Response(
                200,
                json={"data": [{"id": "r1"}], "paging": {"cursors": {"after": "c"}, "next": "x"}},
            )
        return httpx.Response(200, json={"data": [{"post_id": "s1", "status": "PUBLISHED"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        reels = await fp.facebook_pages.list_reels(CREDS, _client=c)
        stories = await fp.facebook_pages.list_stories(CREDS, _client=c)
    assert reels == {"items": [{"id": "r1"}], "next": "c"}
    assert stories == [{"post_id": "s1", "status": "PUBLISHED"}]
    assert seen[0].endswith("/111/video_reels") and seen[1].endswith("/111/stories")


# ------------------------------------------------------------------ the service


class _Storage:
    def __init__(self, *, configured=True):
        self.configured = configured
        self.stored, self.deleted, self.ttl = [], [], None

    async def store(self, media, *, prefix):
        self.stored.append((media, prefix))
        return SimpleNamespace(storage_key="social-outbox/t/vid")

    def signed_url(self, key, *, expires_in=None):
        self.ttl = expires_in
        return f"https://files.example/{key}?sig=1"

    async def delete_objects(self, keys):
        self.deleted.extend(keys)


def _wire(monkeypatch, storage, *, fail=None, budget=None):
    sent = {}

    async def reel(credentials, **kw):
        sent["reel"] = kw
        if fail:
            raise fail
        return "9001"

    async def vstory(credentials, **kw):
        sent["vstory"] = kw
        return "sv1"

    async def pstory(credentials, **kw):
        sent["pstory"] = kw
        return "sp1"

    monkeypatch.setattr(fs, "get_storage", lambda: storage)
    monkeypatch.setattr(fs.facebook_pages, "publish_reel", reel)
    monkeypatch.setattr(fs.facebook_pages, "publish_video_story", vstory)
    monkeypatch.setattr(fs.facebook_pages, "publish_photo_story", pstory)

    async def allow(*a, **k):
        if budget:
            raise budget

    monkeypatch.setattr(FacebookService, "_reel_budget", staticmethod(allow))
    return sent


async def test_a_reel_goes_through_a_signed_link_and_the_file_is_then_removed(monkeypatch):
    storage = _Storage()
    sent = _wire(monkeypatch, storage)
    out = await FacebookService.publish_reel(None, "tenant-1", CREDS, video=REEL, description="hi")
    assert out == "9001"
    media, prefix = storage.stored[0]
    assert media.data == REEL and media.content_type == "video/mp4"
    assert prefix == "social-outbox/tenant-1"
    assert sent["reel"]["video_url"] == "https://files.example/social-outbox/t/vid?sig=1"
    assert sent["reel"]["description"] == "hi"
    assert storage.ttl == fs.VIDEO_LINK_SECONDS
    assert storage.deleted == ["social-outbox/t/vid"]


async def test_the_file_is_removed_even_when_facebook_refuses_the_reel(monkeypatch):
    storage = _Storage()
    _wire(monkeypatch, storage, fail=ExternalProviderError("facebook said no"))
    with pytest.raises(ExternalProviderError):
        await FacebookService.publish_reel(None, "t", CREDS, video=REEL)
    assert storage.deleted == ["social-outbox/t/vid"]


async def test_a_value_error_from_the_client_becomes_a_validation_error(monkeypatch):
    storage = _Storage()
    _wire(monkeypatch, storage, fail=ValueError("a scheduled Reel must go live within 29 days"))
    with pytest.raises(ValidationError, match="29 days"):
        await FacebookService.publish_reel(None, "t", CREDS, video=REEL)
    assert storage.deleted  # still cleaned up


@pytest.mark.parametrize(
    ("fixture", "reason"),
    [
        ("video_landscape.mp4", "video_ratio"),
        ("video_360x640.mp4", "video_resolution"),
        ("video_2s.mp4", "video_short"),
    ],
)
async def test_a_bad_video_is_refused_before_anything_is_stored(monkeypatch, fixture, reason):
    storage = _Storage()
    _wire(monkeypatch, storage)
    with pytest.raises(ValidationError) as e:
        await FacebookService.publish_reel(None, "t", CREDS, video=_video(fixture))
    assert e.value.details["reason"] == reason
    assert storage.stored == []


async def test_without_storage_nothing_is_dropped_silently(monkeypatch):
    _wire(monkeypatch, _Storage(configured=False))
    with pytest.raises(ConflictError, match="storage"):
        await FacebookService.publish_reel(None, "t", CREDS, video=REEL)


async def test_the_31st_reel_in_a_day_is_refused_with_the_wait_and_nothing_is_stored(monkeypatch):
    storage = _Storage()
    _wire(monkeypatch, storage, budget=ConflictError("Facebook allows 30 Reels a day for a Page"))
    with pytest.raises(ConflictError, match="30 Reels"):
        await FacebookService.publish_reel(None, "t", CREDS, video=REEL)
    assert storage.stored == []


async def test_the_daily_reel_budget_is_30_per_page_and_counts_each_page_apart(monkeypatch):
    from app.core import ratelimit, redis

    created = []

    class Limiter:
        def __init__(self, client, *, limit, window_seconds, prefix):
            created.append((limit, window_seconds, prefix))

        async def allow(self, key):
            created.append(key)
            return SimpleNamespace(allowed=key.endswith(":full"), retry_after_seconds=7300)

    monkeypatch.setattr(ratelimit, "RateLimiter", Limiter)
    monkeypatch.setattr(redis, "get_redis_or_none", lambda: object())
    await FacebookService._reel_budget("t1", "full")
    assert created[0] == (30, 24 * 3600, "fb-reels") and created[1] == "t1:full"
    with pytest.raises(ConflictError, match=r"2 hours"):
        await FacebookService._reel_budget("t1", "other")


async def test_without_redis_the_reel_is_not_blocked(monkeypatch):
    from app.core import redis

    monkeypatch.setattr(redis, "get_redis_or_none", lambda: None)
    await FacebookService._reel_budget("t", "p")  # Meta enforces the same limit itself


async def test_a_story_is_exactly_one_video_or_one_picture(monkeypatch):
    storage = _Storage()
    sent = _wire(monkeypatch, storage)
    assert await FacebookService.publish_story(None, "t", CREDS, video=REEL) == "sv1"
    assert sent["vstory"]["video_url"].startswith("https://files.example/")
    assert await FacebookService.publish_story(None, "t", CREDS, photo=PNG) == "sp1"
    assert storage.stored[-1][0].content_type == "image/png"
    for both_or_none in ({}, {"video": REEL, "photo": PNG}):
        with pytest.raises(ValidationError, match="one video or one picture"):
            await FacebookService.publish_story(None, "t", CREDS, **both_or_none)


async def test_a_story_longer_than_a_minute_is_refused_but_the_same_file_is_a_fine_reel(
    monkeypatch,
):
    storage = _Storage()
    _wire(monkeypatch, storage)
    seventy = _video("video_70s.mp4")
    with pytest.raises(ValidationError) as e:
        await FacebookService.publish_story(None, "t", CREDS, video=seventy)
    assert e.value.details["reason"] == "video_long"
    assert storage.stored == []
    assert await FacebookService.publish_reel(None, "t", CREDS, video=seventy) == "9001"


# ------------------------------------------------------------------ the route's body limit


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


def test_the_upload_limit_is_the_service_limit():
    assert MAX_FACEBOOK_VIDEO_UPLOAD_BYTES == fv.MAX_VIDEO_BYTES


@pytest.mark.parametrize("path", ["/api/v1/facebook/reels", "/api/v1/facebook/stories"])
async def test_a_real_video_is_not_refused_as_too_large_but_one_over_the_limit_is(path):
    assert await _status("POST", path, 8 * MB) == 200  # under the 1 MiB default it was a 413
    assert await _status("POST", path, MAX_FACEBOOK_VIDEO_UPLOAD_BYTES + 1) == 413


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/facebook/reels/9001/collaborators"),
        ("GET", "/api/v1/facebook/reels"),
        ("POST", "/api/v1/facebook/comments"),
    ],
)
async def test_no_other_facebook_route_gets_the_larger_body(method, path):
    assert await _status(method, path, MAX_BODY_BYTES + 1) == 413


def test_the_two_routes_exist_and_read_the_raw_file():
    from app.applications.apparel.modules.conversations.routers import facebook_pages as r

    routes = {(m, x.path) for x in r.router.routes for m in x.methods}
    for want in (
        ("POST", "/facebook/reels"),
        ("POST", "/facebook/stories"),
        ("GET", "/facebook/reels"),
        ("GET", "/facebook/stories"),
    ):
        assert want in routes
