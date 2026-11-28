"""Instagram posts, comments and private replies: the exact Graph calls we make."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.circuit_breaker import reset_breakers
from app.core.errors import ExternalProviderError
from app.applications.apparel.modules.conversations.gateway.instagram import InstagramAdapter

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


async def test_user_profile_asks_for_the_documented_fields():
    seen: list = []
    c = _client(
        {
            "name": "Sara A",
            "username": "sara.a",
            "profile_pic": "https://cdn/p.jpg",
            "is_verified_user": True,
            "follower_count": 120,
            "is_user_follow_business": True,
            "is_business_follow_user": False,
        },
        seen=seen,
    )
    out = await A.get_user_profile(CREDS, "igsid-9", _client=c)
    r = seen[0]
    assert r.method == "GET" and r.url.path.endswith("/igsid-9")
    for f in ("name", "username", "profile_pic", "follower_count", "is_user_follow_business"):
        assert f in r.url.params["fields"]
    assert out == {
        "name": "Sara A",
        "username": "sara.a",
        "profile_pic": "https://cdn/p.jpg",
        "verified": True,
        "follower_count": 120,
        "follows_you": True,
        "you_follow": False,
    }


async def test_a_null_name_is_none_not_an_empty_string():
    out = await A.get_user_profile(CREDS, "i", _client=_client({"username": "u", "name": None}))
    assert out["name"] is None and out["username"] == "u" and out["profile_pic"] is None


async def test_a_refused_profile_is_none_not_an_error():
    # Meta says "User consent is required" for a commenter who never messaged us.
    for status in (400, 403, 404):
        c = _client(
            {
                "error": {
                    "message": "User consent is required to access the user profile",
                    "code": 230,
                }
            },
            status=status,
        )
        assert await A.get_user_profile(CREDS, "i", _client=c) is None


async def test_a_real_outage_still_raises():
    with pytest.raises(ExternalProviderError):
        await A.get_user_profile(
            CREDS, "i", _client=_client({"error": {"message": "boom"}}, status=500)
        )


def test_each_kind_of_post_asks_only_for_its_own_metrics():
    # Instagram refuses the WHOLE request if one metric does not exist for that kind of post.
    assert "replies" in A.insight_metrics("STORY") and "saved" not in A.insight_metrics("STORY")
    assert "saved" in A.insight_metrics("REELS") and "replies" not in A.insight_metrics("REELS")
    assert (
        A.insight_metrics("CAROUSEL_ALBUM") == A.insight_metrics("IMAGE") == A.insight_metrics(None)
    )
    # `impressions` was retired for posts made after 2 July 2024
    assert all("impressions" not in A.insight_metrics(k) for k in ("IMAGE", "REELS", "STORY"))


async def test_media_insights_ask_for_lifetime_numbers_and_keep_zero_apart_from_no_data():
    seen: list = []
    c = _client(
        {
            "data": [
                {"name": "reach", "values": [{"value": 120}]},
                {"name": "likes", "values": [{"value": 0}]},
                {"name": "saved", "values": []},
            ]
        },
        seen=seen,
    )
    out = await A.get_media_insights(CREDS, "m1", "IMAGE", _client=c)
    assert seen[0].url.path.endswith("/m1/insights")
    assert seen[0].url.params["period"] == "lifetime"
    assert seen[0].url.params["metric"] == ",".join(A.insight_metrics("IMAGE"))
    assert out["reach"] == 120
    assert out["likes"] == 0  # a real zero
    assert out["saved"] is None  # present but empty: no data yet
    assert out["shares"] is None  # absent: no data yet


async def test_media_insights_with_nothing_yet_is_all_none_not_zero():
    out = await A.get_media_insights(CREDS, "m1", "REELS", _client=_client({"data": []}))
    assert set(out.values()) == {None}


async def test_ice_breakers_are_set_for_the_default_language_on_the_account():
    seen: list = []
    out = await A.set_ice_breakers(
        CREDS, [" Hours? ", "Delivery?"], _client=_client({"result": "success"}, seen=seen)
    )
    assert out == ["Hours?", "Delivery?"]
    req = seen[0]
    assert req.method == "POST" and req.url.path.endswith("/me/messenger_profile")
    assert req.url.params["platform"] == "instagram"
    body = json.loads(req.content)
    (block,) = body["ice_breakers"]
    assert block["locale"] == "default"  # Meta: a default locale is REQUIRED
    assert [c["question"] for c in block["call_to_actions"]] == ["Hours?", "Delivery?"]


async def test_setting_no_questions_removes_them_instead_of_sending_an_empty_list():
    seen: list = []
    assert (
        await A.set_ice_breakers(
            CREDS, ["  ", ""], _client=_client({"result": "success"}, seen=seen)
        )
        == []
    )
    assert seen[0].method == "DELETE"
    assert json.loads(seen[0].content) == {"fields": ["ice_breakers"]}


@pytest.mark.parametrize(
    ("questions", "why"),
    [(["a", "b", "c", "d", "e"], "at most 4"), (["Hours?", " Hours? "], "differ")],
)
async def test_too_many_or_repeated_questions_are_refused_before_any_call(questions, why):
    seen: list = []
    with pytest.raises(ValueError, match=why):
        await A.set_ice_breakers(CREDS, questions, _client=_client({}, seen=seen))
    assert seen == []


async def test_reading_ice_breakers_returns_the_default_language_only():
    reply = {
        "data": [
            {
                "ice_breakers": [
                    {"locale": "en_GB", "call_to_actions": [{"question": "Hello?"}]},
                    {
                        "locale": "default",
                        "call_to_actions": [{"question": "Hours?"}, {"question": "Delivery?"}],
                    },
                ]
            }
        ]
    }
    assert await A.get_ice_breakers(CREDS, _client=_client(reply)) == ["Hours?", "Delivery?"]
    assert await A.get_ice_breakers(CREDS, _client=_client({"data": []})) == []
