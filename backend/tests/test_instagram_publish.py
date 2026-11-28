"""Publishing a photo or a carousel: the exact Graph calls, their order, and early refusals."""

from __future__ import annotations

import httpx
import pytest

from app.core.circuit_breaker import reset_breakers
from app.core.errors import ExternalProviderError
from app.applications.apparel.modules.conversations.gateway.instagram import InstagramAdapter

A = InstagramAdapter()
CREDS = {"api_key": "tok", "account_id": "ig1"}
IMG = "https://cdn.example.com/{}.jpg"


@pytest.fixture(autouse=True)
def _fast_and_closed(monkeypatch):
    reset_breakers()
    monkeypatch.setattr(InstagramAdapter, "PUBLISH_POLL_SECONDS", 0)
    yield
    reset_breakers()


def _fake(statuses: dict[str, list[str]] | None = None, fail_on: str | None = None):
    """A tiny Instagram: records every call, hands out ids, reports each container's status."""
    calls: list[tuple[str, str, dict]] = []
    n = {"i": 0}
    polls: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.lstrip("/").split("/", 1)[-1]
        params = dict(request.url.params)
        calls.append((request.method, path, params))
        if fail_on and fail_on in path:
            return httpx.Response(400, json={"error": {"message": "nope"}})
        if request.method == "GET":
            seq = (statuses or {}).get(path, ["FINISHED"])
            k = polls.get(path, 0)
            polls[path] = k + 1
            return httpx.Response(200, json={"status_code": seq[min(k, len(seq) - 1)]})
        n["i"] += 1
        return httpx.Response(200, json={"id": f"id{n['i']}"})

    return calls, httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_one_picture_is_a_container_then_a_publish() -> None:
    calls, c = _fake()
    media_id = await A.publish_post(CREDS, [IMG.format(1)], "hello", _client=c)
    assert [(m, p) for m, p, _ in calls] == [
        ("POST", "ig1/media"),
        ("GET", "id1"),
        ("POST", "ig1/media_publish"),
    ]
    assert calls[0][2] == {"image_url": IMG.format(1), "caption": "hello"}
    assert calls[2][2] == {"creation_id": "id1"}
    assert media_id == "id2"


async def test_a_carousel_builds_children_then_the_parent_then_publishes() -> None:
    calls, c = _fake()
    media_id = await A.publish_post(CREDS, [IMG.format(i) for i in range(3)], "set", _client=c)
    posts = [(p, q) for m, p, q in calls if m == "POST"]
    # three children first, each flagged as a carousel item, in the order given
    assert [q.get("image_url") for _, q in posts[:3]] == [IMG.format(i) for i in range(3)]
    assert all(q["is_carousel_item"] == "true" for _, q in posts[:3])
    # then the parent, naming the children in order, carrying the caption
    assert posts[3][1] == {"media_type": "CAROUSEL", "children": "id1,id2,id3", "caption": "set"}
    # and only then the publish, of the parent
    assert posts[4] == ("ig1/media_publish", {"creation_id": "id4"})
    assert media_id == "id5"


async def test_it_waits_for_instagram_to_finish_before_publishing() -> None:
    calls, c = _fake({"id1": ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]})
    await A.publish_post(CREDS, [IMG.format(1)], None, _client=c)
    names = [(m, p) for m, p, _ in calls]
    assert names.count(("GET", "id1")) == 3
    assert names.index(("POST", "ig1/media_publish")) > max(
        i for i, x in enumerate(names) if x == ("GET", "id1")
    )


async def test_a_picture_instagram_rejects_is_never_published() -> None:
    calls, c = _fake({"id1": ["ERROR"]})
    with pytest.raises(ExternalProviderError, match="refused the picture"):
        await A.publish_post(CREDS, [IMG.format(1)], None, _client=c)
    assert not any(p.endswith("media_publish") for _, p, _ in calls)


async def test_giving_up_waiting_is_an_error_not_a_hang() -> None:
    calls, c = _fake({"id1": ["IN_PROGRESS"]})
    with pytest.raises(ExternalProviderError, match="too long"):
        await A.publish_post(CREDS, [IMG.format(1)], None, _client=c)
    assert not any(p.endswith("media_publish") for _, p, _ in calls)
    assert sum(1 for m, _, _ in calls if m == "GET") == InstagramAdapter.PUBLISH_POLL_TRIES


async def test_a_failed_publish_call_is_reported() -> None:
    _, c = _fake(fail_on="media_publish")
    with pytest.raises(ExternalProviderError):
        await A.publish_post(CREDS, [IMG.format(1)], None, _client=c)


async def test_no_caption_means_no_caption_field() -> None:
    calls, c = _fake()
    await A.publish_post(CREDS, [IMG.format(1)], "", _client=c)
    assert "caption" not in calls[0][2]


@pytest.mark.parametrize(
    ("urls", "caption", "why"),
    [
        ([], None, "at least one"),
        ([IMG.format(i) for i in range(11)], None, "at most 10"),
        (["http://plain/x.jpg"], None, "public https"),
        (["javascript:alert(1)"], None, "public https"),
        (["/local/path.jpg"], None, "public https"),
        ([IMG.format(1)], "x" * 2201, "2,200"),
    ],
)
async def test_what_instagram_would_refuse_is_refused_before_any_call(urls, caption, why) -> None:
    calls, c = _fake()
    with pytest.raises(ValueError, match=why):
        await A.publish_post(CREDS, urls, caption, _client=c)
    assert calls == []


async def test_ten_pictures_and_a_2200_character_caption_are_fine() -> None:
    calls, c = _fake()
    await A.publish_post(CREDS, [IMG.format(i) for i in range(10)], "x" * 2200, _client=c)
    assert sum(1 for m, p, _ in calls if m == "POST" and p == "ig1/media") == 11
