"""A post that Meta did not give an id for has not been shown to exist (A15).

`str(body.get("post_id") or body.get("id"))` answered with the text "None" when Meta's reply carried
neither key. That text then looked like a post id: it was stored against the post, shown to the
owner, and later used to comment on or delete a post that does not exist.
"""

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.applications.apparel.modules.conversations.gateway import facebook_pages as fp

CREDS = {"api_key": "tok", "account_id": "111"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [{}, {"success": True}, {"post_id": ""}, {"id": None}])
async def test_a_publish_with_no_id_in_the_answer_is_refused_not_returned_as_none(answer):
    def handler(req):
        return httpx.Response(200, json=answer)

    async with _client(handler) as c:
        with pytest.raises(ExternalProviderError, match="no id"):
            await fp.facebook_pages.publish_post(CREDS, message="hello", _client=c)


@pytest.mark.asyncio
async def test_post_id_is_preferred_over_id():
    def handler(req):
        return httpx.Response(200, json={"id": "photo-1", "post_id": "111_9"})

    async with _client(handler) as c:
        got = await fp.facebook_pages.publish_post(CREDS, message="cap", _client=c)
    assert got == "111_9"


@pytest.mark.asyncio
async def test_id_alone_is_enough():
    def handler(req):
        return httpx.Response(200, json={"id": "111_7"})

    async with _client(handler) as c:
        assert await fp.facebook_pages.publish_post(CREDS, message="x", _client=c) == "111_7"


@pytest.mark.asyncio
async def test_an_album_publish_with_no_id_is_refused_too():
    def handler(req):
        if req.url.path.endswith("/photos"):
            return httpx.Response(200, json={"id": "ph1"})
        return httpx.Response(200, json={})

    async with _client(handler) as c:
        with pytest.raises(ExternalProviderError, match="no id"):
            await fp.facebook_pages.publish_post(
                CREDS, message="album", photo_urls=["https://x/1.jpg", "https://x/2.jpg"], _client=c
            )


def test_the_helper_never_returns_the_text_none():
    for bad in ({}, {"id": None}, {"post_id": None, "id": None}, None, [], "x"):
        with pytest.raises(ExternalProviderError):
            fp._published_post_id(bad)  # type: ignore[arg-type]
    assert fp._published_post_id({"post_id": 5}) == "5"
