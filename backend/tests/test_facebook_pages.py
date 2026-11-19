"""Facebook Pages client vs Meta rules (Pages API: Posts, Comments, Insights)."""

import time
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway import facebook_pages as fp

CREDS = {"api_key": "tok", "account_id": "111"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _form(req: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(req.content.decode()).items()}


# ---- the window Meta allows for a scheduled post ----
def test_schedule_window_is_ten_minutes_to_thirty_days():
    now = 1_000_000
    assert fp.check_schedule(now + 601, now=now) == now + 601
    with pytest.raises(ValueError, match="10 minutes"):
        fp.check_schedule(now + 599, now=now)
    with pytest.raises(ValueError, match="30 days"):
        fp.check_schedule(now + 30 * 24 * 3600 + 5, now=now)


# ---- Meta removed these; asking for one must never leave our server ----
def test_removed_insight_metrics_are_refused_before_any_request():
    for m in ("page_fans", "page_impressions", "post_impressions_unique", "page_engaged_users"):
        with pytest.raises(ValueError, match="removed"):
            fp.check_metrics([m])
    assert not set(fp.PAGE_METRICS + fp.POST_METRICS) & fp.REMOVED_METRICS


@pytest.mark.asyncio
async def test_a_text_post_goes_to_feed_and_a_photo_to_photos():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, _form(req)))
        return httpx.Response(200, json={"id": "111_9", "post_id": "111_9"})

    async with _client(handler) as c:
        await fp.facebook_pages.publish_post(CREDS, message="hello", _client=c)
        await fp.facebook_pages.publish_post(
            CREDS, message="cap", photo_url="https://x/y.jpg", _client=c
        )
    assert seen[0][1].endswith("/111/feed") and seen[0][2] == {"message": "hello"}
    assert seen[1][1].endswith("/111/photos")
    assert seen[1][2] == {"caption": "cap", "url": "https://x/y.jpg"}  # a photo's text is `caption`


@pytest.mark.asyncio
async def test_a_scheduled_post_is_sent_unpublished_with_its_time():
    seen = []

    def handler(req):
        seen.append(_form(req))
        return httpx.Response(200, json={"id": "111_1"})

    when = int(time.time()) + 3600
    async with _client(handler) as c:
        await fp.facebook_pages.publish_post(CREDS, message="later", schedule_at=when, _client=c)
    assert seen[0]["published"] == "false" and seen[0]["scheduled_publish_time"] == str(when)
    with pytest.raises(ValueError):
        await fp.facebook_pages.publish_post(
            CREDS, message="soon", schedule_at=int(time.time()) + 60
        )


@pytest.mark.asyncio
async def test_empty_and_contradictory_posts_never_reach_meta():
    called = []

    def handler(req):
        called.append(req)
        return httpx.Response(200, json={"id": "x"})

    async with _client(handler) as c:
        for kw in ({}, {"message": "  "}, {"link": "https://a", "photo_url": "https://b"}):
            with pytest.raises(ValueError):
                await fp.facebook_pages.publish_post(CREDS, _client=c, **kw)
        with pytest.raises(ValueError, match="characters"):
            await fp.facebook_pages.publish_post(
                CREDS, message="x" * (fp.MAX_POST_CHARS + 1), _client=c
            )
    assert called == []


@pytest.mark.asyncio
async def test_comment_reply_hide_like_delete_use_the_documented_calls():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path.split("/", 2)[2], _form(req) if req.content else {}))
        return httpx.Response(200, json={"id": "c2", "success": True})

    async with _client(handler) as c:
        assert await fp.facebook_pages.comment(CREDS, "post1", "thanks", _client=c) == "c2"
        await fp.facebook_pages.set_comment_hidden(CREDS, "c1", True, _client=c)
        await fp.facebook_pages.set_comment_hidden(CREDS, "c1", False, _client=c)
        await fp.facebook_pages.like(CREDS, "c1", True, _client=c)
        await fp.facebook_pages.like(CREDS, "c1", False, _client=c)
        await fp.facebook_pages.delete_comment(CREDS, "c1", _client=c)
        await fp.facebook_pages.delete_post(CREDS, "post1", _client=c)
    assert seen[0] == ("POST", "post1/comments", {"message": "thanks"})
    assert seen[1][2] == {"is_hidden": "true"} and seen[2][2] == {"is_hidden": "false"}
    assert seen[3][:2] == ("POST", "c1/likes") and seen[4][:2] == ("DELETE", "c1/likes")
    assert seen[5][:2] == ("DELETE", "c1") and seen[6][:2] == ("DELETE", "post1")


@pytest.mark.asyncio
async def test_a_meta_refusal_surfaces_its_own_message():
    def handler(req):
        return httpx.Response(
            400, json={"error": {"message": "(#200) permission denied", "code": 200}}
        )

    async with _client(handler) as c:
        with pytest.raises(ExternalProviderError, match="permission denied"):
            await fp.facebook_pages.delete_post(CREDS, "p", _client=c)


@pytest.mark.asyncio
async def test_post_and_page_insights_request_only_current_metrics():
    seen = []

    def handler(req):
        seen.append(req.url.params["metric"])
        return httpx.Response(200, json={"data": [{"name": "x", "values": [{"value": 1}]}]})

    async with _client(handler) as c:
        await fp.facebook_pages.get_page_insights(CREDS, _client=c)
        await fp.facebook_pages.get_post_insights(CREDS, "p1", _client=c)
    for metrics in seen:
        assert not set(metrics.split(",")) & fp.REMOVED_METRICS
    assert "page_follows" in seen[0] and "post_media_view" in seen[1]


@pytest.mark.asyncio
async def test_missing_credentials_are_refused():
    with pytest.raises(ExternalProviderError):
        await fp.facebook_pages.get_page({"api_key": "t"})
