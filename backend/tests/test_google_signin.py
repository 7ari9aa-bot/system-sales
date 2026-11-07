"""Google sign-in: the redirect flow and the service gates behind it.

The route tests need no database (Google is faked, the service is stubbed). The
service tests run against the real database like the rest of the auth suite and
prove the part that used to be wrong: a brand-new Google address gets a full
workspace, and Google is not a side door around verification, MFA or a
suspended workspace.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.errors import PermissionDeniedError
from app.core.security import create_access_token, create_oauth_state_token
from app.modules.identity.models import TenantUser, User
from app.modules.identity.routers import google as google_router
from app.modules.identity.service import AuthService, GoogleMfaRequired

# ---------------------------------------------------------------- routes (no DB)


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(google_router, "_google_config", lambda: ("cid", "secret"))
    app = FastAPI()
    app.include_router(google_router.router, prefix="/api/v1")

    async def _no_session():
        yield object()

    from app.modules.identity.deps import get_db

    app.dependency_overrides[get_db] = _no_session
    return TestClient(app, follow_redirects=False)


def _state_from(location: str) -> str:
    return parse_qs(urlparse(location).query)["state"][0]


def test_authorize_redirects_to_google_with_a_signed_state(app_client):
    res = app_client.get(
        "/api/v1/auth/google/authorize", params={"returnTo": "/inbox", "visitor_id": "v_abcdefgh12"}
    )
    assert res.status_code == 302
    assert res.headers["location"].startswith("https://accounts.google.com/")
    from app.core.security import decode_token

    claims = decode_token(_state_from(res.headers["location"]))
    assert claims["type"] == "oauth_state"
    assert claims["provider"] == "google"
    assert claims["return_to"] == "/inbox"
    assert claims["visitor_id"] == "v_abcdefgh12"


@pytest.mark.parametrize(
    "raw", ["https://evil.com", "//evil.com", "/\\evil.com", "javascript:alert(1)", "/a\nb", ""]
)
def test_return_to_never_leaves_the_site(raw):
    assert google_router.safe_return_to(raw) == "/dashboard"


def test_return_to_keeps_a_normal_path():
    assert google_router.safe_return_to("/orders?tab=open") == "/orders?tab=open"


def test_a_malformed_visitor_id_is_dropped_not_stored(app_client):
    res = app_client.get("/api/v1/auth/google/authorize", params={"visitor_id": "<script>"})
    from app.core.security import decode_token

    assert decode_token(_state_from(res.headers["location"]))["visitor_id"] is None


def test_authorize_without_config_returns_to_login_with_a_reason(monkeypatch):
    monkeypatch.setattr(google_router, "_google_config", lambda: ("", ""))
    app = FastAPI()
    app.include_router(google_router.router, prefix="/api/v1")
    res = TestClient(app, follow_redirects=False).get("/api/v1/auth/google/authorize")
    assert res.headers["location"] == "/login?error=google_not_configured"


@pytest.mark.parametrize(
    "params",
    [
        {"code": "c", "state": "not-a-jwt"},
        {"code": "", "state": "x"},
        {"error": "access_denied"},
    ],
)
def test_callback_rejects_a_bad_or_missing_state(app_client, params):
    res = app_client.get("/api/v1/auth/google/callback", params=params)
    assert res.status_code == 302
    assert res.headers["location"].startswith("/login?error=google_")


def test_callback_rejects_a_token_that_is_not_a_google_state(app_client):
    for token in (
        create_access_token("u1"),  # a real access token
        create_oauth_state_token("meta", {"provider": "facebook"}),  # another provider's state
    ):
        res = app_client.get("/api/v1/auth/google/callback", params={"code": "c", "state": token})
        assert res.headers["location"] == "/login?error=google_invalid_state"


def _fake_google(monkeypatch, profile):
    class _Resp:
        def __init__(self, code, body):
            self.status_code, self._b = code, body

        def json(self):
            return self._b

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...
        async def post(self, *a, **k):
            return _Resp(200, {"access_token": "at"})

        async def get(self, *a, **k):
            return _Resp(200, profile)

    monkeypatch.setattr(google_router.httpx, "AsyncClient", _Client)


def _valid_state(**extra):
    claims = {"provider": "google", "return_to": "/inbox", "visitor_id": "v_abcdefgh12", **extra}
    return create_oauth_state_token("google", claims)


def test_callback_passes_google_proof_and_visitor_to_the_service(app_client, monkeypatch):
    _fake_google(monkeypatch, {"email": "New@Shop.com", "email_verified": True, "name": "Nora"})
    seen = {}

    async def fake_login(session, **kw):
        seen.update(kw)
        pair = SimpleNamespace(access_token="A", refresh_token="R")
        return pair, SimpleNamespace(), uuid.uuid4()

    monkeypatch.setattr(AuthService, "login_with_google", staticmethod(fake_login))
    res = app_client.get(
        "/api/v1/auth/google/callback", params={"code": "c", "state": _valid_state()}
    )
    assert res.status_code == 302
    assert res.headers["location"] == "/inbox"
    assert res.headers["cache-control"] == "no-store"
    assert seen["email"] == "New@Shop.com"
    assert seen["email_verified"] is True
    assert seen["visitor_id"] == "v_abcdefgh12"
    assert seen["full_name"] == "Nora"
    assert any("A" in c for c in res.headers.get_list("set-cookie"))


@pytest.mark.parametrize("flag", [False, None, "true", "yes"])
def test_only_an_explicit_true_counts_as_verified(app_client, monkeypatch, flag):
    profile = {"email": "a@b.com"}
    if flag is not None:
        profile["email_verified"] = flag
    _fake_google(monkeypatch, profile)
    seen = {}

    async def fake_login(session, **kw):
        seen.update(kw)
        raise PermissionDeniedError("google email is not verified")

    monkeypatch.setattr(AuthService, "login_with_google", staticmethod(fake_login))
    res = app_client.get(
        "/api/v1/auth/google/callback", params={"code": "c", "state": _valid_state()}
    )
    assert seen["email_verified"] is False
    assert res.headers["location"] == "/login?error=google_email_unverified"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (GoogleMfaRequired("mfa"), "google_mfa_required"),
        (PermissionDeniedError("account email is not verified"), "google_email_unverified"),
        (PermissionDeniedError("workspace is suspended"), "google_account_unavailable"),
        (PermissionDeniedError("account disabled"), "google_account_unavailable"),
    ],
)
def test_service_refusals_become_a_readable_login_error(app_client, monkeypatch, exc, expected):
    _fake_google(monkeypatch, {"email": "a@b.com", "email_verified": True})

    async def fake_login(session, **kw):
        raise exc

    monkeypatch.setattr(AuthService, "login_with_google", staticmethod(fake_login))
    res = app_client.get(
        "/api/v1/auth/google/callback", params={"code": "c", "state": _valid_state()}
    )
    assert res.headers["location"] == f"/login?error={expected}"
    assert not res.headers.get_list("set-cookie")


# ------------------------------------------------------------ service (real DB)


def _addr() -> str:
    return f"g-{uuid.uuid4().hex[:8]}@test.local"


async def test_a_new_google_address_gets_a_full_workspace_linked_to_the_visitor(db):
    email = _addr()
    pair, user, tenant_id = await AuthService.login_with_google(
        db, email=email, email_verified=True, full_name="Nora", visitor_id="v_abcdefgh12"
    )
    assert tenant_id is not None, "a Google signup must not be an orphan user"
    assert user.email_verified is True
    assert user.password_hash == ""
    membership = (
        await db.execute(select(TenantUser).where(TenantUser.user_id == user.id))
    ).scalar_one()
    assert membership.tenant_id == tenant_id and membership.is_default
    got = (
        await db.execute(
            text("SELECT signup_visitor_id FROM tenants WHERE id = :t"), {"t": tenant_id}
        )
    ).scalar_one()
    assert got == "v_abcdefgh12"
    assert pair.access_token and pair.refresh_token


async def test_google_session_is_recorded_so_logout_and_refresh_work(db):
    from app.modules.identity.models import RefreshToken

    _pair, user, _t = await AuthService.login_with_google(db, email=_addr(), email_verified=True)
    rows = (
        (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_an_unverified_google_address_is_refused_and_creates_nothing(db):
    email = _addr()
    with pytest.raises(PermissionDeniedError):
        await AuthService.login_with_google(db, email=email, email_verified=False)
    assert (await db.execute(select(User).where(User.email == email))).scalar_one_or_none() is None


async def test_google_signs_into_an_existing_verified_account_without_a_second_workspace(db):
    email = _addr()
    user, tenant = await AuthService.register(
        db,
        tenant_name="Existing",
        tenant_slug=f"ex-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Ex",
    )
    user.email_verified = True
    await db.flush()
    _pair, got, tenant_id = await AuthService.login_with_google(
        db, email=email.upper(), email_verified=True
    )
    assert got.id == user.id and tenant_id == tenant.id
    count = (
        (await db.execute(select(TenantUser).where(TenantUser.user_id == user.id))).scalars().all()
    )
    assert len(count) == 1


async def test_google_cannot_take_over_an_unverified_password_account(db):
    """Pre-hijack: someone registered a victim's address and never proved the mailbox."""
    email = _addr()
    await AuthService.register(
        db,
        tenant_name="Squat",
        tenant_slug=f"sq-{uuid.uuid4().hex[:8]}",
        email=email,
        password="attacker-password-1",
        full_name="Squatter",
    )
    with pytest.raises(PermissionDeniedError, match="not verified"):
        await AuthService.login_with_google(db, email=email, email_verified=True)


async def test_google_does_not_bypass_a_disabled_account(db):
    email = _addr()
    user, _t = await AuthService.register(
        db,
        tenant_name="Off",
        tenant_slug=f"off-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Off",
    )
    user.email_verified = True
    user.is_active = False
    await db.flush()
    with pytest.raises(PermissionDeniedError, match="disabled"):
        await AuthService.login_with_google(db, email=email, email_verified=True)


async def test_google_does_not_bypass_a_suspended_workspace(db):
    email = _addr()
    user, tenant = await AuthService.register(
        db,
        tenant_name="Susp",
        tenant_slug=f"su-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Susp",
    )
    user.email_verified = True
    await db.execute(
        text("UPDATE tenants SET lifecycle_state = 'suspended' WHERE id = :t"), {"t": tenant.id}
    )
    await db.flush()
    with pytest.raises(PermissionDeniedError):
        await AuthService.login_with_google(db, email=email, email_verified=True)


async def test_google_does_not_bypass_mfa(db, monkeypatch):
    email = _addr()
    user, _t = await AuthService.register(
        db,
        tenant_name="Mfa",
        tenant_slug=f"mf-{uuid.uuid4().hex[:8]}",
        email=email,
        password="strong-password-1",
        full_name="Mfa",
    )
    user.email_verified = True
    await db.flush()

    async def _mfa_on(session, *, user_id):
        return True

    monkeypatch.setattr("app.core.mfa.is_mfa_enabled", _mfa_on)
    with pytest.raises(GoogleMfaRequired):
        await AuthService.login_with_google(db, email=email, email_verified=True)
