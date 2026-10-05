"""HttpOnly cookie auth tests (auth-hardening wave) — dual delivery, CSRF gate.

The pair is delivered BOTH ways by design: the body (desktop/Bearer flow,
untouched) and HttpOnly cookies (the dashboard's XSS-hardened path). These
tests pin the cookie matrix, cookie-path authentication, the CSRF
double-submit gate, and the matching-path logout clearing. Every test keeps
its client inside ONE `async with` — httpx clients do not survive a loop.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import bind_tenant
from app.main import create_app
from app.modules.identity import cookies as auth_cookies


async def _register(db, sessions_on_test_connection, slug_suffix: str) -> tuple[str, str]:
    """A real tenant + owner through the service; returns (email, password)."""
    from app.modules.identity.service import AuthService

    email = f"cookie-{slug_suffix}@example.dev"
    password = "strong-password-1"
    _user, tenant = await AuthService.register(
        db,
        tenant_name="Cookie Tenant",
        tenant_slug=f"cookie-{slug_suffix}",
        email=email,
        password=password,
        full_name="Cookie Owner",
    )
    # register already binds the owner's tenant_users row — adding another
    # would collide on the membership PK. The commit releases the savepoint
    # so the login route's own session (any connection) sees the owner; the
    # conftest teardown rolls the OUTER transaction back, discarding it all.
    await bind_tenant(db, tenant.id)
    await db.commit()
    return email, password


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """These tests exercise the COOKIE CONTRACT, not the rate limiter.

    Every login/register here counts against the shared auth-tier bucket
    (10/60s per IP), so nine cookie tests would 429 each other long before
    the assertions ran. The limiter keeps its own dedicated suite.
    """
    from app.core.middleware import RateLimitMiddleware

    async def _passthrough(self, request, call_next):
        return await call_next(request)

    monkeypatch.setattr(RateLimitMiddleware, "dispatch", _passthrough)


def _set_cookie_headers(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def _set_cookie_for(response, name: str) -> str:
    """The raw Set-Cookie header for one cookie name."""
    for header in _set_cookie_headers(response):
        if header.startswith(f"{name}="):
            return header
    raise KeyError(f"no Set-Cookie for {name}")


async def test_login_delivers_the_pair_as_cookies_and_body(db, app_sessions_on_test_connection):
    email, password = await _register(db, app_sessions_on_test_connection, uuid.uuid4().hex[:8])
    client = _client()
    async with client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 200

    body = response.json()
    assert {"access_token", "refresh_token"} <= set(body)

    access = _set_cookie_for(response, auth_cookies.ACCESS_COOKIE)
    refresh = _set_cookie_for(response, auth_cookies.REFRESH_COOKIE)
    csrf = _set_cookie_for(response, auth_cookies.CSRF_COOKIE)

    assert "httponly" in access.lower() and "httponly" in refresh.lower()
    assert "httponly" not in csrf.lower()  # double-submit: JS must read it
    assert f"path={auth_cookies.ACCESS_COOKIE_PATH}" in access.lower()
    assert f"path={auth_cookies.REFRESH_COOKIE_PATH}" in refresh.lower()
    assert f"path={auth_cookies.CSRF_COOKIE_PATH}" in csrf.lower()  # "/" — readable everywhere
    # local = Lax (SameSite=None without Secure is dropped by browsers);
    # https deployments flip to None via the same auto flag.
    assert "samesite=lax" in refresh.lower()
    # local runs plain http, so the AUTO secure flag stays off here
    assert "secure" not in access.lower()


async def test_cookie_session_authenticates_without_any_header(db, app_sessions_on_test_connection):
    email, password = await _register(db, app_sessions_on_test_connection, uuid.uuid4().hex[:8])
    client = _client()
    async with client:
        await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email


async def test_logout_clears_with_the_same_paths(db, app_sessions_on_test_connection):
    email, password = await _register(db, app_sessions_on_test_connection, uuid.uuid4().hex[:8])
    client = _client()
    async with client:
        await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        logout = await client.post("/api/v1/auth/logout", json={})
    assert logout.status_code == 204
    access = _set_cookie_for(logout, auth_cookies.ACCESS_COOKIE)
    refresh = _set_cookie_for(logout, auth_cookies.REFRESH_COOKIE)
    # a mismatched path is how delete_cookie silently does nothing — pinned.
    assert f"path={auth_cookies.ACCESS_COOKIE_PATH}" in access.lower()
    assert f"path={auth_cookies.REFRESH_COOKIE_PATH}" in refresh.lower()
    assert access.split(";")[0].split("=", 1)[1].strip('"') == ""  # emptied


async def test_bearer_flow_still_works_without_cookies_or_csrf(db, app_sessions_on_test_connection):
    email, password = await _register(db, app_sessions_on_test_connection, uuid.uuid4().hex[:8])
    client = _client()
    async with client:
        pair = (
            await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        ).json()
        # Desktop shape: Bearer header on a cookie-less client.
        bare = AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")
        async with bare:
            me = await bare.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {pair['access_token']}"},
            )
    assert me.status_code == 200
    assert me.json()["email"] == email


async def test_refresh_accepts_the_cookie_when_the_body_is_empty(
    db, app_sessions_on_test_connection
):
    email, password = await _register(db, app_sessions_on_test_connection, uuid.uuid4().hex[:8])
    client = _client()
    async with client:
        await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        refreshed = await client.post("/api/v1/auth/refresh", json={})
    assert refreshed.status_code == 200
    assert {"access_token", "refresh_token"} <= set(refreshed.json())


async def test_cookie_post_without_the_csrf_header_is_refused(db, app_sessions_on_test_connection):
    email, password = await _register(db, app_sessions_on_test_connection, uuid.uuid4().hex[:8])
    client = _client()
    async with client:
        await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        attempt = await client.post(
            "/api/v1/auth/switch-tenant",
            json={"tenant_id": str(uuid.uuid4()), "refresh_token": None},
        )
    assert attempt.status_code == 403
    assert "csrf" in attempt.json()["error"]["message"].lower()


async def test_cookie_post_with_the_matching_header_passes_the_gate(
    db, app_sessions_on_test_connection
):
    email, password = await _register(db, app_sessions_on_test_connection, uuid.uuid4().hex[:8])
    client = _client()
    async with client:
        login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        # read the CSRF value from the login response's Set-Cookie header —
        # the same string the frontend JS would read from document.cookie.
        csrf_pair = _set_cookie_for(login, auth_cookies.CSRF_COOKIE).split(";", 1)[0]
        csrf = csrf_pair.split("=", 1)[1]
        # a throwaway tenant id: the point is passing the CSRF gate — any
        # non-403 verdict proves the request got past authentication.
        attempt = await client.post(
            "/api/v1/auth/switch-tenant",
            json={"tenant_id": str(uuid.uuid4()), "refresh_token": None},
            headers={"X-CSRF-Token": csrf},
        )
    # the CSRF gate passed: any remaining 403 is the HANDLER's own verdict —
    # here "not a member of this tenant" for a random tenant id — never the
    # csrf refusal, which is distinguishable by its message.
    assert attempt.status_code != 403 or "csrf" not in attempt.text.lower()
    assert "csrf" not in attempt.text.lower()


async def test_cookie_post_with_a_mismatched_header_is_refused(
    db, app_sessions_on_test_connection
):
    email, password = await _register(db, app_sessions_on_test_connection, uuid.uuid4().hex[:8])
    client = _client()
    async with client:
        await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        attempt = await client.post(
            "/api/v1/auth/switch-tenant",
            json={"tenant_id": str(uuid.uuid4()), "refresh_token": None},
            headers={"X-CSRF-Token": "forged-value"},
        )
    assert attempt.status_code == 403


async def test_revoked_auth_version_kills_the_cookie_session(db, app_sessions_on_test_connection):
    from sqlalchemy import update

    from app.modules.identity.models import User

    email, password = await _register(db, app_sessions_on_test_connection, uuid.uuid4().hex[:8])
    client = _client()
    async with client:
        await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        # a password reset bumps auth_version — the cookie JWT carries the
        # stale value and the gate must refuse it exactly like Bearer.
        await db.execute(
            update(User).where(User.email == email).values(auth_version=User.auth_version + 1)
        )
        me = await client.get("/api/v1/auth/me")
    assert me.status_code == 403
