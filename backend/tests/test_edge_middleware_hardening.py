"""Edge hardening follow-ups on the rate-limit middleware.

Three audit findings, pinned DB-free against the same FakeRedis harness the
§25 tests in test_request_integrity.py use:

1. ONLY type="access" tokens key the tenant/user tiers — a webchat VISITOR
   token is perfectly signed but must never be able to drain a victim
   tenant's budget (and a refresh/stream/oauth_state token even less). The
   cookie-authenticated path (the dashboard's HttpOnly delivery) keys the
   same access JWT, or every cookie request silently escaped those tiers.
2. The STRICT auth bucket covers credential-granting actions only; the
   session surface (me / refresh / logout) gets a lighter bucket and fails
   OPEN on a Redis outage, so routine dashboard traffic stops competing with
   a brute-force attempt — and stays up when the cache dies.
3. TRUSTED_PROXY_COUNT selects the correct X-Forwarded-For hop: the real
   client sits N entries from the RIGHT once N trusted proxies append their
   peers; shorter chains fall back to the socket peer.
"""

from __future__ import annotations

import uuid

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.core import middleware as mw
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_visitor_token,
)

# ---------------------------------------------------------------- helpers --


class _Settings:
    """Only the fields the middleware reads."""

    environment = "local"
    trusted_proxy_count = 1


def _app(client, **kwargs) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/orders")
    async def orders() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    async def login() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/auth/refresh")
    async def refresh() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/auth/me")
    async def me() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(mw.RateLimitMiddleware, client=client, enabled=True, **kwargs)
    return app


def _ip_headers(ip: str) -> dict[str, str]:
    # Two hops: the trusted proxy appended the second entry.
    return {"x-forwarded-for": f"10.0.0.1, {ip}"}


async def _get(
    app: FastAPI,
    path: str = "/api/v1/orders",
    *,
    token: str | None = None,
    cookie_token: str | None = None,
    ip: str = "8.8.8.8",
) -> AsyncClient:
    headers = _ip_headers(ip)
    if token:
        headers["authorization"] = f"Bearer {token}"
    cookies = {"access_token": cookie_token} if cookie_token else None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(path, headers=headers)


def _token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    return create_access_token(str(user_id), {"tenant_id": str(tenant_id), "role": "owner"})


# ---------------------------------------------- 1. token type + cookies ----


async def test_a_visitor_token_cannot_key_the_tenant_tier(monkeypatch) -> None:
    """The audit attack: hold a VALID visitor token for tenant T and burn T's
    §25 budget — real users then got 429s. The visitor principal must stay
    empty; the IP tiers are all it touches."""
    monkeypatch.setattr(mw, "TENANT_LIMIT", 1)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    monkeypatch.setattr("app.core.middleware.get_settings", lambda: _Settings())
    client = FakeRedis(decode_responses=True)
    app = _app(client)
    tenant_id = uuid.uuid4()

    # Real users fill the tenant budget (limit 1 → the second is denied)…
    assert (await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="9.9.9.1")).status_code == 200
    drained = await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="9.9.9.3")
    assert drained.status_code == 429
    assert drained.json()["tier"] == "tenant"

    # …but a valid visitor token for the SAME tenant keys nothing.
    visitor = create_visitor_token("session-key", str(tenant_id), widget="w")
    result = await _get(app, token=visitor, ip="9.9.9.2")
    assert result.status_code == 200
    await client.aclose()


@pytest.mark.parametrize(
    "mint",
    [
        lambda uid, tid: create_refresh_token(str(uid)),
        # stream/oauth_state types exercise the same guard through decode.
    ],
)
async def test_non_access_token_types_do_not_key_the_tenant_tier(monkeypatch, mint) -> None:
    monkeypatch.setattr(mw, "TENANT_LIMIT", 1)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    monkeypatch.setattr("app.core.middleware.get_settings", lambda: _Settings())
    client = FakeRedis(decode_responses=True)
    app = _app(client)
    tenant_id = uuid.uuid4()

    # Two real users fill the tenant budget (limit 1 → the second is denied)…
    assert (await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="9.9.9.1")).status_code == 200
    assert (await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="9.9.9.3")).status_code == 429
    # A refresh token is signed by us too — it still must not key the tier.
    refreshed = await _get(app, token=mint(uuid.uuid4(), tenant_id), ip="9.9.9.2")
    assert refreshed.status_code == 200
    await client.aclose()


async def test_cookie_sessions_key_the_tenant_tier(monkeypatch) -> None:
    """No Authorization header, only the HttpOnly access cookie — the
    dashboard's normal shape. Without the cookie fallback these requests
    bypassed the tenant/user tiers entirely."""
    monkeypatch.setattr(mw, "TENANT_LIMIT", 2)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    monkeypatch.setattr(mw, "USER_LIMIT", 1000)
    monkeypatch.setattr("app.core.middleware.get_settings", lambda: _Settings())
    client = FakeRedis(decode_responses=True)
    app = _app(client)
    tenant_id = uuid.uuid4()

    first = await _get(app, cookie_token=_token(uuid.uuid4(), tenant_id), ip="7.7.7.1")
    second = await _get(app, cookie_token=_token(uuid.uuid4(), tenant_id), ip="7.7.7.2")
    third = await _get(app, cookie_token=_token(uuid.uuid4(), tenant_id), ip="7.7.7.3")
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["tier"] == "tenant"
    await client.aclose()


async def test_a_cookie_that_is_not_an_access_token_keys_nothing(monkeypatch) -> None:
    monkeypatch.setattr(mw, "TENANT_LIMIT", 1)
    monkeypatch.setattr(mw, "ENDPOINT_LIMIT", 1000)
    monkeypatch.setattr("app.core.middleware.get_settings", lambda: _Settings())
    client = FakeRedis(decode_responses=True)
    app = _app(client)
    tenant_id = uuid.uuid4()

    # Consume the tenant budget with real access tokens (limit 1 → the
    # second is denied)…
    assert (await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="9.9.9.1")).status_code == 200
    assert (await _get(app, token=_token(uuid.uuid4(), tenant_id), ip="9.9.9.3")).status_code == 429
    # …then a VISITOR token delivered as a cookie must still pass (empty
    # principal → IP tiers only).
    visitor = create_visitor_token("session-key", str(tenant_id), widget="w")
    assert (await _get(app, cookie_token=visitor, ip="9.9.9.2")).status_code == 200
    await client.aclose()


# -------------------------------------------------- 2. auth bucket scope ---


@pytest.mark.parametrize(
    ("path", "bucket", "limit"),
    [
        ("/auth/login", "auth", mw.AUTH_LIMIT),
        ("/auth/register", "auth", mw.AUTH_LIMIT),
        ("/auth/password-reset/request", "auth", mw.AUTH_LIMIT),
        ("/auth/password-reset/confirm", "auth", mw.AUTH_LIMIT),
        ("/auth/mfa/verify", "auth", mw.AUTH_LIMIT),
        ("/auth/switch-tenant", "auth", mw.AUTH_LIMIT),
        ("/auth/me", "auth_session", mw.AUTH_SESSION_LIMIT),
        ("/auth/refresh", "auth_session", mw.AUTH_SESSION_LIMIT),
        ("/auth/logout", "auth_session", mw.AUTH_SESSION_LIMIT),
    ],
)
def test_the_strict_bucket_covers_credential_actions_only(path, bucket, limit) -> None:
    assert mw._bucket_for(f"/api/v1{path}") == (bucket, limit)


async def test_the_session_surface_fails_open_when_redis_is_down() -> None:
    class ExplodingRedis:
        async def eval(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("redis down")

    app = _app(ExplodingRedis())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post("/api/v1/auth/login", headers=_ip_headers("1.1.1.1"))
        refresh = await client.post("/api/v1/auth/refresh", headers=_ip_headers("1.1.1.1"))
        me = await client.get("/api/v1/auth/me", headers=_ip_headers("1.1.1.1"))

    assert login.status_code == 429, "credential entry stays fail-closed"
    assert refresh.status_code == 200, "session surface fails open"
    assert me.status_code == 200, "session surface fails open"


async def test_refresh_does_not_burn_the_login_budget(monkeypatch) -> None:
    monkeypatch.setattr("app.core.middleware.get_settings", lambda: _Settings())
    client = FakeRedis(decode_responses=True)
    app = _app(client)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        for _ in range(mw.AUTH_LIMIT + 2):
            assert (
                await http.post("/api/v1/auth/refresh", headers=_ip_headers("2.2.2.2"))
            ).status_code == 200

        login = await http.post("/api/v1/auth/login", headers=_ip_headers("2.2.2.2"))
    assert login.status_code == 200, "session polling must not exhaust the strict bucket"
    await client.aclose()


# --------------------------------------------- 3. trusted proxy hop selection


def _request_with_xff(value: str | None) -> Request:
    headers = [] if value is None else [(b"x-forwarded-for", value.encode())]
    return Request({"type": "http", "headers": headers, "client": ("198.51.100.9", 1234)})


def _ip_of(value: str | None, *, trusted: int) -> str:
    return mw._client_ip(_request_with_xff(value), trusted_proxy_count=trusted)


def test_one_trusted_proxy_reads_the_last_hop() -> None:
    # [attacker-injected, real-client]: the proxy appended the LAST entry.
    assert _ip_of("1.2.3.4, 203.0.113.7", trusted=1) == "203.0.113.7"


def test_two_trusted_proxies_read_one_from_the_right() -> None:
    # Cloudflare → Vercel → app: the inner proxy's edge IP is the LAST entry
    # and is shared by every user — the old mass-throttle bug.
    assert _ip_of("1.2.3.4, 203.0.113.7, 198.51.100.1", trusted=2) == "203.0.113.7"


def test_a_chain_shorter_than_the_trusted_depth_falls_back_to_the_peer() -> None:
    assert _ip_of("6.6.6.6", trusted=2) == "198.51.100.9"


def test_no_forwarded_header_falls_back_to_the_peer() -> None:
    assert _ip_of(None, trusted=1) == "198.51.100.9"


def test_trusted_proxy_count_zero_ignores_the_header_entirely() -> None:
    assert _ip_of("1.2.3.4, 203.0.113.7", trusted=0) == "198.51.100.9"


def test_the_default_comes_from_settings(monkeypatch) -> None:
    class _TwoProxies(_Settings):
        trusted_proxy_count = 2

    monkeypatch.setattr("app.core.middleware.get_settings", lambda: _TwoProxies())
    assert mw._client_ip(_request_with_xff("203.0.113.7, 198.51.100.1")) == "203.0.113.7"
