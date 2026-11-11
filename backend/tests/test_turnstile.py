"""Cloudflare Turnstile on the public auth routes.

Pins four promises:
  1. OFF (no secret) it changes nothing and never calls Cloudflare.
  2. ON, register / resend-verification / password-reset demand a valid token.
  3. ON, login demands one ONLY after repeated failures (desktop keeps working).
  4. It fails CLOSED: a Cloudflare outage or garbage reply refuses, never admits,
     and the refusal is the same answer for every reason (no oracle).

Cloudflare is replaced with an httpx.MockTransport; nothing here touches the
network. The settings cache is cleared around each test because the secret is
read through get_settings().
"""

from __future__ import annotations

import httpx
import pytest
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient

from app.core import turnstile
from app.core.config import get_settings
from app.core.errors import CaptchaRequiredError
from app.main import create_app

SECRET = "0x-test-secret"
_RealClient = httpx.AsyncClient


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    from app.core.middleware import RateLimitMiddleware

    async def _passthrough(self, request, call_next):
        return await call_next(request)

    monkeypatch.setattr(RateLimitMiddleware, "dispatch", _passthrough)


@pytest.fixture(autouse=True)
async def _fresh_engine():
    """Each test runs on its own event loop; the app's global engine would keep
    pooled connections bound to the previous one ("attached to a different loop")."""
    from app.core.db import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()


@pytest.fixture
def secret_on(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def secret_off(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _cloudflare(monkeypatch, handler):
    """Route turnstile's outbound call to ``handler`` and count the calls."""
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(wrapped)
        return _RealClient(*a, **kw)

    monkeypatch.setattr(turnstile.httpx, "AsyncClient", factory)
    return calls


def _ok(request):
    return httpx.Response(200, json={"success": True})


def _refuse(request):
    return httpx.Response(200, json={"success": False, "error-codes": ["invalid-input-response"]})


# ---------------------------------------------------------------- unit: verify


async def test_off_is_a_noop_and_never_calls_cloudflare(secret_off, monkeypatch):
    calls = _cloudflare(monkeypatch, _ok)
    assert turnstile.enabled() is False
    await turnstile.verify(None)
    await turnstile.verify("anything")
    assert calls == []


async def test_a_valid_token_passes_and_sends_secret_token_and_ip(secret_on, monkeypatch):
    calls = _cloudflare(monkeypatch, _ok)
    await turnstile.verify("good-token", ip="203.0.113.9")
    assert len(calls) == 1
    body = calls[0].content.decode()
    assert "secret=0x-test-secret" in body
    assert "response=good-token" in body
    assert "remoteip=203.0.113.9" in body


@pytest.mark.parametrize("token", [None, "", "x" * 2049])
async def test_missing_or_absurd_token_is_refused_without_a_network_call(
    secret_on, monkeypatch, token
):
    calls = _cloudflare(monkeypatch, _ok)
    with pytest.raises(CaptchaRequiredError):
        await turnstile.verify(token)
    assert calls == []


async def test_a_token_cloudflare_refuses_is_refused(secret_on, monkeypatch):
    _cloudflare(monkeypatch, _refuse)
    with pytest.raises(CaptchaRequiredError):
        await turnstile.verify("bad")


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, json={"success": True}),
        lambda r: httpx.Response(200, text="<html>not json</html>"),
        lambda r: httpx.Response(200, json={"success": "true"}),
        lambda r: httpx.Response(200, json={}),
    ],
    ids=["http-500", "garbage-body", "truthy-not-true", "no-success-key"],
)
async def test_odd_cloudflare_replies_never_admit(secret_on, monkeypatch, handler):
    _cloudflare(monkeypatch, handler)
    with pytest.raises(CaptchaRequiredError):
        await turnstile.verify("t")


async def test_a_cloudflare_outage_fails_closed(secret_on, monkeypatch):
    def boom(request):
        raise httpx.ConnectError("down")

    _cloudflare(monkeypatch, boom)
    with pytest.raises(CaptchaRequiredError):
        await turnstile.verify("t")


# ------------------------------------------------------------- routes (HTTP)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/auth/register", {"email": "bot@example.dev", "password": "strong-password-1"}),
        ("/api/v1/auth/resend-verification", {"email": "bot@example.dev"}),
        ("/api/v1/auth/password-reset/request", {"email": "bot@example.dev"}),
    ],
)
async def test_mail_sending_routes_demand_a_token_when_on(secret_on, monkeypatch, path, body):
    _cloudflare(monkeypatch, _refuse)
    async with _client() as c:
        r = await c.post(path, json=body)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "captcha_required"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/resend-verification",
        "/api/v1/auth/password-reset/request",
    ],
)
async def test_the_gate_runs_before_any_account_lookup(secret_on, monkeypatch, path):
    """A refused token must never reach the account lookup.

    If the check ran after the lookup, the work done (and so the time and the
    side effects) would differ between a real and an unknown address, which is
    exactly the enumeration oracle these routes are built to avoid. The service
    methods are replaced with tripwires: refusing the token has to happen first.
    """
    from app.modules.identity.service import AuthService

    touched: list[str] = []

    async def tripwire(*a, **kw):
        touched.append("lookup")

    monkeypatch.setattr(AuthService, "request_password_reset", tripwire)
    monkeypatch.setattr(AuthService, "request_email_verification", tripwire)
    _cloudflare(monkeypatch, _refuse)
    async with _client() as c:
        r = await c.post(path, json={"email": "anyone@example.dev"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "captcha_required"
    assert touched == [], "the account lookup ran before the captcha was checked"


async def test_register_gate_runs_before_any_account_work(secret_on, monkeypatch):
    from app.modules.identity.service import AuthService

    touched: list[str] = []

    async def tripwire(*a, **kw):
        touched.append("register")

    monkeypatch.setattr(AuthService, "register", tripwire)
    _cloudflare(monkeypatch, _refuse)
    async with _client() as c:
        r = await c.post(
            "/api/v1/auth/register",
            json={"email": "bot@example.dev", "password": "strong-password-1"},
        )
    assert r.json()["error"]["code"] == "captcha_required"
    assert touched == []


async def test_password_reset_with_a_good_token_gets_the_normal_neutral_202(secret_on, monkeypatch):
    _cloudflare(monkeypatch, _ok)
    async with _client() as c:
        r = await c.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "nobody@example.dev", "captcha_token": "good"},
        )
    assert r.status_code == 202


async def test_off_the_routes_behave_exactly_as_before(secret_off, monkeypatch):
    calls = _cloudflare(monkeypatch, _refuse)
    async with _client() as c:
        r = await c.post("/api/v1/auth/password-reset/request", json={"email": "n@example.dev"})
    assert r.status_code == 202
    assert calls == []


# -------------------------------------------------------------------- login


@pytest.fixture
def lockout_redis(monkeypatch):
    """One FakeRedis shared by the lockout counter for the whole test."""
    client = FakeRedis(decode_responses=True)
    import app.modules.identity.service as svc

    monkeypatch.setattr(svc, "get_redis_or_none", lambda: client)
    return client


async def _fail(c, n, email="who@example.dev", **extra):
    out = []
    for _ in range(n):
        out.append(
            await c.post("/api/v1/auth/login", json={"email": email, "password": "wrong", **extra})
        )
    return out


async def test_login_asks_for_no_token_until_failures_pile_up(
    secret_on, monkeypatch, lockout_redis
):
    calls = _cloudflare(monkeypatch, _ok)
    async with _client() as c:
        first = await _fail(c, 3)  # failures 0,1,2 at request time: never gated
    assert [r.status_code for r in first] == [403, 403, 403]
    assert all(r.json()["error"]["code"] != "captcha_required" for r in first)
    assert calls == []


async def test_after_the_threshold_login_demands_a_token(secret_on, monkeypatch, lockout_redis):
    _cloudflare(monkeypatch, _refuse)
    async with _client() as c:
        await _fail(c, 3)
        gated = await _fail(c, 1)
    assert gated[0].status_code == 400
    assert gated[0].json()["error"]["code"] == "captcha_required"


async def test_a_good_token_lets_the_attempt_through_to_the_password_check(
    secret_on, monkeypatch, lockout_redis
):
    calls = _cloudflare(monkeypatch, _ok)
    async with _client() as c:
        await _fail(c, 3)
        passed = await _fail(c, 1, captcha_token="good")
    assert len(calls) == 1
    # Past the gate it is an ordinary wrong-password answer, not a captcha one.
    assert passed[0].json()["error"]["code"] != "captcha_required"


async def test_the_gate_is_per_email_so_one_victim_does_not_gate_everyone(
    secret_on, monkeypatch, lockout_redis
):
    _cloudflare(monkeypatch, _refuse)
    async with _client() as c:
        await _fail(c, 3, email="victim@example.dev")
        other = await _fail(c, 1, email="someone-else@example.dev")
    assert other[0].json()["error"]["code"] != "captcha_required"


async def test_login_is_never_gated_while_the_feature_is_off(secret_off, lockout_redis):
    async with _client() as c:
        rs = await _fail(c, 4)
    assert all(r.json()["error"]["code"] != "captcha_required" for r in rs)


async def test_a_redis_outage_does_not_gate_login(secret_on, monkeypatch):
    import app.modules.identity.service as svc

    monkeypatch.setattr(svc, "get_redis_or_none", lambda: None)
    calls = _cloudflare(monkeypatch, _refuse)
    async with _client() as c:
        rs = await _fail(c, 5)
    assert all(r.json()["error"]["code"] != "captcha_required" for r in rs)
    assert calls == []
