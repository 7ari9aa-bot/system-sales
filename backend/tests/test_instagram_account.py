"""The store's own Instagram profile, and what an identity tells about the customer."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.core.circuit_breaker import reset_breakers
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.instagram import InstagramAdapter
from app.modules.customers.routers.customers import _identity_out

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


async def test_account_asks_for_the_profile_fields_of_the_connected_account():
    seen: list = []
    reply = {
        "id": "ig1",
        "username": "shop.eg",
        "name": "Shop",
        "profile_picture_url": "https://cdn/p.jpg",
        "followers_count": 1520,
        "follows_count": 12,
        "media_count": 48,
        "biography": "Bags & shoes",
        "website": "https://shop.eg",
    }
    out = await A.get_account(CREDS, _client=_client(reply, seen=seen))
    r = seen[0]
    assert r.method == "GET" and r.url.path.endswith("/ig1")
    for field in ("username", "followers_count", "follows_count", "media_count", "biography"):
        assert field in r.url.params["fields"]
    assert r.headers["authorization"] == "Bearer tok"
    assert out == {
        "username": "shop.eg",
        "name": "Shop",
        "profile_picture_url": "https://cdn/p.jpg",
        "followers_count": 1520,
        "follows_count": 12,
        "media_count": 48,
        "biography": "Bags & shoes",
        "website": "https://shop.eg",
    }


async def test_missing_fields_are_none_not_guessed():
    out = await A.get_account(CREDS, _client=_client({"id": "ig1", "username": " "}))
    assert out == {
        "username": None,
        "name": None,
        "profile_picture_url": None,
        "followers_count": None,
        "follows_count": None,
        "media_count": None,
        "biography": None,
        "website": None,
    }


async def test_a_refusal_is_raised_not_hidden():
    with pytest.raises(ExternalProviderError):
        await A.get_account(CREDS, _client=_client({"error": {"message": "bad token"}}, status=400))


def _identity(extra):
    return SimpleNamespace(id=uuid.uuid4(), channel="instagram", external_id="123", extra=extra)


def test_identity_carries_the_instagram_profile_it_learned():
    out = _identity_out(
        _identity(
            {
                "username": "sara.a",
                "verified": True,
                "follower_count": 980,
                "follows_you": False,
                "avatar_key": "k",
            }
        )
    )
    assert out["username"] == "sara.a" and out["verified"] is True
    assert out["follower_count"] == 980 and out["follows_you"] is False
    assert "avatar_key" not in out and "you_follow" not in out


def test_identity_ignores_values_of_the_wrong_kind():
    out = _identity_out(_identity({"follower_count": True, "verified": "yes", "username": 5}))
    assert set(out) == {"id", "channel", "external_id"}


def test_identity_without_extra_is_plain():
    out = _identity_out(
        SimpleNamespace(id=uuid.uuid4(), channel="whatsapp", external_id="+20", extra=None)
    )
    assert set(out) == {"id", "channel", "external_id"}
