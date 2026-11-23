"""Linking one channel on a Page must never take another channel's subscription away.

Meta REPLACES the whole `subscribed_fields` list on every POST. Connecting Messenger on a Page
Facebook already subscribed for `feed` has to write chat AND feed, and the list it keeps must be
OUR app's, not another app's, and must be certain, not guessed.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ExternalProviderError
from app.modules.customers import meta_oauth

PAGE = "page-1"
OURS = "111"


class _Http:
    """Answers GET subscribed_apps with `rows` (or a failure), records every POST."""

    def __init__(self, rows=None, *, get_status=200, get_error=None):
        self.rows = rows
        self.get_status = get_status
        self.get_error = get_error
        self.posts: list[dict] = []

    async def get(self, url, params=None):
        if self.get_error:
            raise self.get_error
        body = {"data": self.rows} if self.rows is not None else {}
        return httpx.Response(self.get_status, json=body, request=httpx.Request("GET", url))

    async def post(self, url, params=None):
        self.posts.append(dict(params or {}))
        return httpx.Response(200, json={"success": True}, request=httpx.Request("POST", url))


def _app_id(monkeypatch, value):
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: type("S", (), {"meta_app_id": value})()
    )


@pytest.fixture(autouse=True)
def _our_app(monkeypatch):
    _app_id(monkeypatch, OURS)


def _row(app_id, *fields):
    return {"id": app_id, "subscribed_fields": list(fields)}


def _written(http):
    [post] = http.posts
    return set(post["subscribed_fields"].split(","))


async def test_connecting_messenger_keeps_the_facebook_feed_subscription():
    http = _Http([_row(OURS, "feed", "mention")])
    await meta_oauth._subscribe_page_to_app(
        http, page_id=PAGE, page_token="t", provider="messenger"
    )
    written = _written(http)
    assert {"feed", "mention"} <= written and "messages" in written


async def test_another_apps_fields_are_never_copied_into_ours():
    http = _Http([_row("999", "leadgen", "videos"), _row(OURS, "feed")])
    await meta_oauth._subscribe_page_to_app(
        http, page_id=PAGE, page_token="t", provider="messenger"
    )
    written = _written(http)
    assert "feed" in written
    assert not ({"leadgen", "videos"} & written)


async def test_a_failed_read_does_not_overwrite_what_may_already_be_there():
    """If we cannot see the current list we must not write a narrower one over it."""
    for http in (
        _Http(get_status=500),
        _Http(get_error=httpx.ConnectError("down")),
    ):
        with pytest.raises(ExternalProviderError) as raised:
            await meta_oauth._subscribe_page_to_app(
                http, page_id=PAGE, page_token="t", provider="messenger"
            )
        assert getattr(raised.value, "retryable", False) is True
        assert http.posts == []  # nothing was written


async def test_an_empty_but_successful_read_is_a_first_connection_and_writes_normally():
    http = _Http([])
    await meta_oauth._subscribe_page_to_app(
        http, page_id=PAGE, page_token="t", provider="messenger"
    )
    assert "messages" in _written(http)


async def test_an_unreadable_answer_is_not_treated_as_empty():
    class _Garbled(_Http):
        async def get(self, url, params=None):
            return httpx.Response(200, content=b"not json", request=httpx.Request("GET", url))

    http = _Garbled()
    with pytest.raises(ExternalProviderError):
        await meta_oauth._subscribe_page_to_app(
            http, page_id=PAGE, page_token="t", provider="messenger"
        )
    assert http.posts == []


async def test_no_app_id_configured_never_guesses_which_row_is_ours(monkeypatch):
    _app_id(monkeypatch, "")
    http = _Http([_row("999", "leadgen")])
    await meta_oauth._subscribe_page_to_app(
        http, page_id=PAGE, page_token="t", provider="messenger"
    )
    assert "leadgen" not in _written(http)
