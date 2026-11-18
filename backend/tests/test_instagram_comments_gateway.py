"""Instagram posts, comments and private replies: the exact Graph calls we make."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.circuit_breaker import reset_breakers
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.instagram import InstagramAdapter

A = InstagramAdapter()
CREDS = {"api_key": "tok", "account_id": "ig1"}


@pytest.fixture(autouse=True)
def _closed_breaker():
    reset_breakers()
    yield
    reset_breakers()


def _client(reply: dict, status: int = 200, seen: list | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=reply)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_list_media_asks_for_the_post_fields_and_pages():
    seen: list = []
    c = _client(
        {"data": [{"id": "m1"}], "paging": {"cursors": {"after": "CUR"}, "next": "https://x"}},
        seen=seen,
    )
    out = await A.list_media(CREDS, limit=10, _client=c)
    r = seen[0]
    assert r.method == "GET" and r.url.path.endswith("/ig1/media")
    assert "caption" in r.url.params["fields"] and "comments_count" in r.url.params["fields"]
    assert r.url.params["limit"] == "10" and r.headers["authorization"] == "Bearer tok"
    assert out == {"items": [{"id": "m1"}], "next": "CUR"}


async def test_last_page_has_no_cursor():
    c = _client({"data": [], "paging": {"cursors": {"after": "CUR"}}})
    assert (await A.list_media(CREDS, _client=c))["next"] is None


async def test_list_comments_includes_replies_and_clamps_limit():
    seen: list = []
    c = _client({"data": [{"id": "c1", "replies": {"data": [{"id": "c2"}]}}]}, seen=seen)
    out = await A.list_comments(CREDS, "m1", limit=9999, _client=c)
    r = seen[0]
    assert r.url.path.endswith("/m1/comments") and "replies{" in r.url.params["fields"]
    assert r.url.params["limit"] == "100"
    assert out["items"][0]["id"] == "c1"


async def test_public_reply_posts_message_to_the_comment():
    seen: list = []
    new_id = await A.reply_to_comment(
        CREDS, "c1", "thanks!", _client=_client({"id": "c9"}, seen=seen)
    )
    r = seen[0]
    assert (
        r.method == "POST"
        and r.url.path.endswith("/c1/replies")
        and r.url.params["message"] == "thanks!"
    )
    assert new_id == "c9"


async def test_hide_unhide_delete_and_toggle_comments():
    seen: list = []
    c = _client({"success": True}, seen=seen)
    await A.set_comment_hidden(CREDS, "c1", True, _client=c)
    await A.set_comment_hidden(CREDS, "c1", False, _client=c)
    await A.delete_comment(CREDS, "c1", _client=c)
    await A.set_comments_enabled(CREDS, "m1", False, _client=c)
    assert [(r.method, r.url.path.split("/")[-1], dict(r.url.params)) for r in seen] == [
        ("POST", "c1", {"hide": "true"}),
        ("POST", "c1", {"hide": "false"}),
        ("DELETE", "c1", {}),
        ("POST", "m1", {"comment_enabled": "false"}),
    ]


async def test_private_reply_targets_the_comment_not_a_user():
    assert A.build_private_reply("c1", "hi") == {
        "recipient": {"comment_id": "c1"},
        "message": {"text": "hi"},
    }
    seen: list = []
    mid = await A.send_private_reply(
        CREDS,
        "c1",
        "hello",
        _client=_client({"recipient_id": "u", "message_id": "mid1"}, seen=seen),
    )
    assert seen[0].url.path.endswith("/ig1/messages")
    assert json.loads(seen[0].content) == {
        "recipient": {"comment_id": "c1"},
        "message": {"text": "hello"},
    }
    assert mid == "mid1"


async def test_a_rejection_is_an_error_not_a_success():
    with pytest.raises(ExternalProviderError):
        await A.reply_to_comment(
            CREDS, "c1", "x", _client=_client({"error": {"message": "no"}}, status=400)
        )
    with pytest.raises(ExternalProviderError):
        await A.delete_comment(
            CREDS, "c1", _client=_client({"error": {"code": 10}})
        )  # 200 with an error body


async def test_missing_credentials_fail_before_any_call():
    with pytest.raises(ExternalProviderError):
        await A.list_media({"api_key": "t"})
