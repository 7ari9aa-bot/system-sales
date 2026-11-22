"""Disconnecting a Meta channel must also remove its webhook subscription from Meta.

It used to flip a row in our database and leave Meta delivering the Page's events to us. A Page is
one subscription shared by Messenger, Facebook and Instagram, so removing it under a channel that
is still connected would silence that channel: it is narrowed instead.
"""

from __future__ import annotations

import httpx
import pytest

from app.modules.customers import meta_unsubscribe as mu
from app.modules.customers.meta_oauth import subscribed_fields


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _recorder(status: int = 200, body: dict | None = None):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=body if body is not None else {"success": True})

    return calls, handler


# ----------------------------------------------------------------------------- Page


async def test_the_page_subscription_is_deleted_when_nothing_else_uses_it() -> None:
    calls, handler = _recorder()
    async with _client(handler) as http:
        out = await mu.unsubscribe_page(http, page_id="111", page_token="TOK", sibling_providers=[])
    [req] = calls
    assert req.method == "DELETE"
    assert req.url.path.endswith("/111/subscribed_apps")
    assert req.url.params["access_token"] == "TOK"
    assert out["state"] == mu.DONE


async def test_a_page_shared_with_a_connected_sibling_is_narrowed_not_deleted() -> None:
    calls, handler = _recorder()
    async with _client(handler) as http:
        out = await mu.unsubscribe_page(
            http, page_id="111", page_token="TOK", sibling_providers=["messenger"]
        )
    [req] = calls
    assert req.method == "POST"  # never DELETE: the sibling still needs its messages
    sent = set(req.url.params["subscribed_fields"].split(","))
    assert sent == set(subscribed_fields("messenger").split(","))
    assert "feed" not in sent  # the disconnected Facebook channel's field is dropped
    assert out["state"] == mu.KEPT
    assert out["siblings"] == ["messenger"]


async def test_two_siblings_keep_the_union_of_their_fields() -> None:
    calls, handler = _recorder()
    async with _client(handler) as http:
        await mu.unsubscribe_page(
            http, page_id="1", page_token="T", sibling_providers=["messenger", "facebook"]
        )
    sent = set(calls[0].url.params["subscribed_fields"].split(","))
    assert {"messages", "feed", "mention"} <= sent


async def test_meta_refusing_is_recorded_as_pending_not_raised() -> None:
    _, handler = _recorder(400, {"error": {"code": 200, "message": "no permission"}})
    async with _client(handler) as http:
        out = await mu.unsubscribe_page(http, page_id="1", page_token="T", sibling_providers=[])
    assert out["state"] == mu.PENDING
    assert out["reason"] == "meta_refused"
    assert out["meta"]["code"] == 200


async def test_meta_unreachable_is_recorded_as_pending_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with _client(handler) as http:
        out = await mu.unsubscribe_page(http, page_id="1", page_token="T", sibling_providers=[])
    assert out == {**out, "state": mu.PENDING, "reason": "meta_unreachable"}


@pytest.mark.parametrize(
    "error",
    [
        {"code": 190, "message": "token expired"},  # revoked/expired: nothing left to remove
        {"code": 803, "message": "object does not exist"},
        {"code": 100, "error_subcode": 33, "message": "unsupported get request"},
    ],
)
async def test_an_answer_meaning_it_is_already_gone_counts_as_done(error) -> None:
    _, handler = _recorder(400, {"error": error})
    async with _client(handler) as http:
        out = await mu.unsubscribe_page(http, page_id="1", page_token="T", sibling_providers=[])
    assert out["state"] == mu.DONE
    assert out["reason"] == "already_gone"


async def test_a_200_without_success_true_is_not_treated_as_removed() -> None:
    _, handler = _recorder(200, {"success": False})
    async with _client(handler) as http:
        out = await mu.unsubscribe_page(http, page_id="1", page_token="T", sibling_providers=[])
    assert out["state"] == mu.PENDING


async def test_the_recorded_outcome_never_contains_the_token() -> None:
    _, handler = _recorder(400, {"error": {"code": 1, "message": "boom"}})
    async with _client(handler) as http:
        out = await mu.unsubscribe_page(
            http, page_id="1", page_token="SECRET-TOKEN", sibling_providers=[]
        )
    assert "SECRET-TOKEN" not in repr(out)


# ----------------------------------------------------------------------------- WhatsApp


async def test_the_waba_subscription_is_deleted_with_a_bearer_token() -> None:
    calls, handler = _recorder()
    async with _client(handler) as http:
        out = await mu.unsubscribe_waba(http, waba_id="999", token="WTOK")
    [req] = calls
    assert req.method == "DELETE"
    assert req.url.path.endswith("/999/subscribed_apps")
    assert req.headers["authorization"] == "Bearer WTOK"
    assert "access_token" not in req.url.params  # never in the URL
    assert out["state"] == mu.DONE


async def test_a_waba_refusal_is_pending() -> None:
    _, handler = _recorder(403, {"error": {"code": 10, "message": "denied"}})
    async with _client(handler) as http:
        out = await mu.unsubscribe_waba(http, waba_id="9", token="T")
    assert out["state"] == mu.PENDING


# ----------------------------------------------------------------------------- retry gate


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, True),  # never attempted (a channel disconnected before this existed)
        ({"_meta_cleanup": {"state": "pending"}}, True),
        ({"_meta_cleanup": {"state": "done"}}, False),
        ({"_meta_cleanup": {"state": "kept"}}, False),
        ({"_meta_cleanup": {"state": "not_needed"}}, False),
        (None, True),
    ],
)
def test_only_an_unconfirmed_removal_is_retried(config, expected) -> None:
    assert mu.needs_cleanup(config) is expected
