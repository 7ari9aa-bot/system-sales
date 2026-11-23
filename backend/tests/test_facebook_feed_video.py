"""An ordinary video post on a Facebook Page's feed.

The report's Facebook section listed one missing kind of content: "نشر فيديو عادي على Feed، وليس
Reel أو Story فقط" — a plain video post. It is `POST /{page-id}/videos` with a `file_url` Meta
fetches itself, and Meta then processes the file before the post can play.

A feed video is NOT a Reel and NOT a Story, and its limits are Meta's own: 240 minutes, no 9:16
ratio, no 540x960 floor. These tests pin that difference so a feed video is never judged by the
Reel rules.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.conversations.gateway import facebook_pages as fp
from app.modules.conversations.gateway import facebook_video as fv

FIX = Path(__file__).parent / "fixtures"
CREDS = {"api_key": "page-token", "account_id": "111"}

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
FAILED = {
    "video_status": "error",
    "uploading_phase": {"status": "complete"},
    "processing_phase": {"status": "error", "error": {"message": "Resolution too low"}},
}


def _video(name: str) -> bytes:
    return (FIX / name).read_bytes()


class _Meta:
    """A Page that accepts a feed video and answers the status calls from a script."""

    def __init__(self, *, status_script=None, post_response=None):
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.status_script = list(status_script or [])
        self.post_response = post_response if post_response is not None else {"id": "vid-77"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        raw = (request.content or b"").decode("utf-8")
        body = dict(httpx.QueryParams(raw)) if raw else {}
        self.calls.append((request.method, request.url.path, body, dict(request.headers)))
        if request.method == "POST" and request.url.path.endswith("/111/videos"):
            return httpx.Response(200, json=self.post_response)
        if request.method == "GET" and request.url.path.endswith("/vid-77"):
            step = self.status_script.pop(0) if self.status_script else DONE
            return httpx.Response(200, json={"status": step})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})


async def _no_sleep(_):
    return None


def _client(meta: _Meta) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(meta.handler))


# ------------------------------------------------------------------ Meta's own limits


def test_a_wide_seventy_second_video_is_a_feed_video_but_never_a_reel():
    """The Reel rules (9:16, 540x960, 90 s) must not be applied to a normal post."""
    wide = _video("video_landscape.mp4")
    with pytest.raises(fv.FacebookVideoError):
        fv.check_reel(wide)
    assert fv.check_feed_video(wide).seconds > 0

    seventy = _video("video_70s.mp4")
    assert fv.check_feed_video(seventy).seconds == pytest.approx(70.0, abs=0.1)


def test_a_feed_video_keeps_metas_240_minute_ceiling_and_its_format_checks():
    assert fv.FEED_MAX_SECONDS == 240 * 60
    with pytest.raises(fv.FacebookVideoError) as empty:
        fv.check_feed_video(b"")
    assert empty.value.code == "video_empty"
    with pytest.raises(fv.FacebookVideoError) as pdf:
        fv.check_feed_video(b"%PDF-1.7 " + b"0" * 64)
    assert pdf.value.code == "video_format"


# ------------------------------------------------------------------ the adapter call


async def test_a_feed_video_is_posted_to_the_pages_videos_edge_and_waited_on():
    meta = _Meta(status_script=[BUSY, DONE])
    async with _client(meta) as c:
        video_id = await fp.facebook_pages.publish_feed_video(
            CREDS,
            video_url="https://files.example/v.mp4",
            description="جديد المتجر",
            title="عرض الأسبوع",
            _client=c,
            _sleep=_no_sleep,
        )
    assert video_id == "vid-77"
    post = meta.calls[0]
    assert post[0] == "POST" and post[1].endswith("/111/videos")
    assert post[2] == {
        "file_url": "https://files.example/v.mp4",
        "description": "جديد المتجر",
        "title": "عرض الأسبوع",
    }
    # Meta is asked about the processing state until it is done, and no publish call is invented.
    assert [c[0] for c in meta.calls[1:]] == ["GET", "GET"]


async def test_a_scheduled_feed_video_is_stored_unpublished_and_not_waited_on():
    meta = _Meta()
    when = int(time.time()) + 3600
    async with _client(meta) as c:
        await fp.facebook_pages.publish_feed_video(
            CREDS,
            video_url="https://files.example/v.mp4",
            schedule_at=when,
            _client=c,
            _sleep=_no_sleep,
        )
    post = meta.calls[0]
    assert post[2]["published"] == "false"
    assert post[2]["scheduled_publish_time"] == str(when)
    # Nothing is being processed yet, so no status call is made.
    assert [c[0] for c in meta.calls] == ["POST"]


async def test_a_schedule_outside_metas_window_is_refused_before_the_call():
    meta = _Meta()
    async with _client(meta) as c:
        with pytest.raises(ValueError):
            await fp.facebook_pages.publish_feed_video(
                CREDS,
                video_url="https://files.example/v.mp4",
                schedule_at=int(time.time()) + 60,
                _client=c,
            )
    assert meta.calls == []


async def test_a_video_without_an_id_is_an_error_not_a_silent_success():
    meta = _Meta(post_response={"success": True})
    async with _client(meta) as c:
        with pytest.raises(ExternalProviderError):
            await fp.facebook_pages.publish_feed_video(
                CREDS, video_url="https://files.example/v.mp4", _client=c, _sleep=_no_sleep
            )


async def test_a_video_meta_refuses_reports_metas_own_reason():
    meta = _Meta(status_script=[FAILED])
    async with _client(meta) as c:
        with pytest.raises(ExternalProviderError) as exc:
            await fp.facebook_pages.publish_feed_video(
                CREDS, video_url="https://files.example/v.mp4", _client=c, _sleep=_no_sleep
            )
    assert "Resolution too low" in str(exc.value)


# ------------------------------------------------------------------ the service layer


async def test_the_service_validates_the_file_and_reports_a_bad_one_as_validation(monkeypatch):
    from app.modules.conversations.facebook_service import FacebookService

    monkeypatch.setattr(
        FacebookService, "_with_stored_file", staticmethod(lambda *a, **k: _raise_unused())
    )
    with pytest.raises(ValidationError) as exc:
        await FacebookService.publish_video(None, None, CREDS, video=b"%PDF-1.7 junk")
    assert exc.value.details.get("reason") == "video_format"


async def _raise_unused():  # pragma: no cover - only reached if validation is skipped
    raise AssertionError("a refused file must never be stored")
