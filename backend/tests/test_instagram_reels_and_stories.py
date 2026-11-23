"""Publishing a Reel and a Story: the two container types Instagram has and we did not use.

The adapter's own comment said "Reels are deliberately not here yet", so a merchant could publish a
photo or a carousel and nothing else. Both are the same three steps Instagram documents — create a
container, wait for its status, publish it — with `media_type=REELS` / `STORIES`.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ValidationError
from app.modules.conversations.gateway.instagram import InstagramAdapter
from app.modules.conversations.social_service import SocialService

CREDS = {"api_key": "tok", "account_id": "ig-1"}


def _transport(calls: list[dict], status: str = "FINISHED") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "params": dict(request.url.params),
            }
        )
        path = request.url.path
        if path.endswith("/media") and request.method == "POST":
            return httpx.Response(200, json={"id": "container-1"})
        if "container-1" in path and request.method == "GET":
            return httpx.Response(200, json={"status_code": status})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "media-9"})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_a_reel_container_asks_instagram_for_a_reel():
    calls: list[dict] = []
    async with httpx.AsyncClient(transport=_transport(calls)) as client:
        media_id = await InstagramAdapter().publish_reel(
            CREDS, "https://cdn.example/reel.mp4", "أول ريل", _client=client
        )

    assert media_id == "media-9"
    created = next(c for c in calls if c["method"] == "POST" and c["path"].endswith("/media"))
    assert created["params"]["media_type"] == "REELS"
    assert created["params"]["video_url"] == "https://cdn.example/reel.mp4"
    assert created["params"]["share_to_feed"] == "true"


@pytest.mark.asyncio
async def test_a_reel_can_stay_off_the_grid():
    calls: list[dict] = []
    async with httpx.AsyncClient(transport=_transport(calls)) as client:
        await InstagramAdapter().publish_reel(
            CREDS, "https://cdn.example/reel.mp4", None, share_to_feed=False, _client=client
        )

    created = next(c for c in calls if c["method"] == "POST" and c["path"].endswith("/media"))
    assert created["params"]["share_to_feed"] == "false"
    assert "caption" not in created["params"]


@pytest.mark.asyncio
async def test_a_story_container_asks_instagram_for_a_story():
    calls: list[dict] = []
    async with httpx.AsyncClient(transport=_transport(calls)) as client:
        media_id = await InstagramAdapter().publish_story(
            CREDS, "https://cdn.example/s.jpg", _client=client
        )

    assert media_id == "media-9"
    created = next(c for c in calls if c["method"] == "POST" and c["path"].endswith("/media"))
    assert created["params"]["media_type"] == "STORIES"
    assert created["params"]["image_url"] == "https://cdn.example/s.jpg"
    assert "caption" not in created["params"]


@pytest.mark.asyncio
async def test_a_video_story_uses_video_url():
    calls: list[dict] = []
    async with httpx.AsyncClient(transport=_transport(calls)) as client:
        await InstagramAdapter().publish_story(
            CREDS, "https://cdn.example/s.mp4", is_video=True, _client=client
        )

    created = next(c for c in calls if c["method"] == "POST" and c["path"].endswith("/media"))
    assert created["params"]["video_url"] == "https://cdn.example/s.mp4"
    assert "image_url" not in created["params"]


@pytest.mark.asyncio
async def test_a_container_instagram_rejected_surfaces_its_status():
    """A silent failure would leave the merchant thinking the Reel went out."""
    calls: list[dict] = []
    async with httpx.AsyncClient(transport=_transport(calls, status="ERROR")) as client:
        with pytest.raises(Exception) as caught:
            await InstagramAdapter().publish_reel(
                CREDS, "https://cdn.example/reel.mp4", None, _client=client
            )

    assert "ERROR" in str(caught.value)


@pytest.mark.asyncio
async def test_a_reel_needs_a_public_https_video():
    with pytest.raises(ValueError):
        await InstagramAdapter().publish_reel(CREDS, "/local/file.mp4", None)


# ------------------------------------------------------------- what we refuse locally


def test_a_file_that_is_not_mp4_is_refused_before_it_is_stored():
    with pytest.raises(ValidationError):
        SocialService.check_video(b"\xff\xd8\xff" + b"0" * 100)


def test_an_mp4_is_accepted():
    SocialService.check_video(b"\x00\x00\x00\x18ftypmp42" + b"0" * 100)


def test_a_video_over_the_limit_is_refused():
    with pytest.raises(ValidationError):
        SocialService.check_video(b"\x00\x00\x00\x18ftypmp42" + b"0" * (100 * 1024 * 1024))
