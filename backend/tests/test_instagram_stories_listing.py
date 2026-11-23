"""The stories running right now, and the numbers Meta later sends about them.

The platform could publish a story but never read one back, so a story's performance had no screen
to appear on. Meta keeps a story for 24 hours, so an empty list is normal; and a story's metrics
arrive afterwards through `story_insights`, where -1 means "fewer than five".
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.conversations.gateway.instagram import InstagramAdapter
from app.modules.conversations.social_service import SocialService

CREDS = {"api_key": "tok", "account_id": "ig-1"}


def _transport(payload: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/stories")
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_live_stories_are_read_with_the_story_fields_only():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"data": [{"id": "s-1", "media_type": "IMAGE",
                                                   "media_url": "https://x/1.jpg",
                                                   "timestamp": "2026-11-23T05:00:00+0000"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await InstagramAdapter().list_stories(CREDS, _client=client)

    assert [i["id"] for i in items] == ["s-1"]
    # a story has no caption, so the request must not ask for one
    assert "caption" not in seen[0]["fields"]
    assert "media_url" in seen[0]["fields"]


@pytest.mark.asyncio
async def test_no_live_story_is_an_empty_list_not_an_error():
    async with httpx.AsyncClient(transport=_transport({"data": []})) as client:
        assert await InstagramAdapter().list_stories(CREDS, _client=client) == []


@pytest.mark.asyncio
async def test_the_service_passes_stories_through_and_drops_one_without_an_id():
    async with httpx.AsyncClient(
        transport=_transport({"data": [{"id": "s-1", "media_type": "VIDEO"}, {"media_type": "IMAGE"}]})
    ) as client:
        InstagramAdapter.list_stories.__globals__  # noqa: B018 - keeps the import honest
        import app.modules.conversations.social_service as svc

        original = svc.instagram_adapter.list_stories

        async def fake(credentials, **_):
            return await InstagramAdapter().list_stories(credentials, _client=client)

        svc.instagram_adapter.list_stories = fake
        try:
            items = await SocialService.list_stories(CREDS)
        finally:
            svc.instagram_adapter.list_stories = original

    assert [i["id"] for i in items] == ["s-1"]
    assert items[0]["media_type"] == "VIDEO"
