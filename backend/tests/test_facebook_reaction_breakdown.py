"""A post's reactions by kind (Pages API: Object Reactions edge), as Facebook's summary shows them.

Meta lets a Page READ the count of each kind (LIKE, LOVE, HAHA, WOW, SAD, ANGRY) but WRITE only a
like (POST /{id}/likes). So the screen can show the breakdown; it cannot offer the Page a heart.
"""

import httpx
import pytest

from app.modules.conversations.gateway import facebook_pages as fp

CREDS = {"api_key": "tok", "account_id": "111"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _summary(n):
    return {"summary": {"total_count": n}, "data": []}


@pytest.mark.asyncio
async def test_all_kinds_come_back_in_one_request_not_six():
    calls = []

    def handler(req):
        calls.append(req)
        fields = req.url.params["fields"]
        assert fields.count("reactions.type(") == 6  # one aliased edge per kind, one request
        return httpx.Response(
            200,
            json={
                "id": "111_9",
                "like": _summary(10),
                "love": _summary(4),
                "haha": _summary(2),
                "wow": _summary(0),
                "sad": _summary(1),
                "angry": _summary(0),
            },
        )

    async with _client(handler) as c:
        out = await fp.facebook_pages.get_reaction_breakdown(CREDS, "111_9", _client=c)
    assert len(calls) == 1
    assert out == {"LIKE": 10, "LOVE": 4, "HAHA": 2, "WOW": 0, "SAD": 1, "ANGRY": 0}


@pytest.mark.asyncio
async def test_a_kind_meta_does_not_return_counts_as_zero():
    def handler(req):
        return httpx.Response(200, json={"id": "1_2", "like": _summary(3)})

    async with _client(handler) as c:
        out = await fp.facebook_pages.get_reaction_breakdown(CREDS, "1_2", _client=c)
    assert out["LIKE"] == 3
    assert out["LOVE"] == out["HAHA"] == out["WOW"] == out["SAD"] == out["ANGRY"] == 0
    assert list(out) == ["LIKE", "LOVE", "HAHA", "WOW", "SAD", "ANGRY"]  # Facebook's order


@pytest.mark.asyncio
async def test_the_summary_is_what_is_asked_for_not_the_people():
    def handler(req):
        assert (
            req.url.params["fields"].count(".limit(0)") == 6
        )  # counts only, never a list of people
        return httpx.Response(200, json={"id": "1_2"})

    async with _client(handler) as c:
        await fp.facebook_pages.get_reaction_breakdown(CREDS, "1_2", _client=c)


# ---- the route: GET /facebook/objects/{id}/reactions ----
from app.modules.conversations.routers import facebook_pages as router  # noqa: E402


def test_the_breakdown_route_exists_and_needs_the_read_permission():
    route = next(
        r
        for r in router.router.routes
        if getattr(r, "path", "") == "/facebook/objects/{object_id}/reactions"
    )
    assert "GET" in route.methods
