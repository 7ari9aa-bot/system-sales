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
from app.platform.identity.models import TenantUser, User
from app.platform.identity.routers import google as google_router
from app.platform.identity.service import AuthService, GoogleMfaRequired

# ---------------------------------------------------------------- routes (no DB)


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(google_router, "_google_config", lambda: ("cid", "secret"))
    app = FastAPI()
    app.include_router(google_router.router, prefix="/api/v1")

    async def _no_session():
        yield object()

    from app.platform.identity.deps import get_db

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


# ------------------------------------------------- redirect URI (must equal Google Cloud's)


def _req(host="p01--system-sales--x.code.run", proto="https"):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("internal", 80),
            "path": "/",
            "headers": [(b"host", host.encode()), (b"x-forwarded-proto", proto.encode())],
        }
    )


def test_redirect_uri_uses_the_configured_public_origin_not_the_internal_host(monkeypatch):
    """Production: the proxy hands the app an internal Host, but Google has fihrist.world."""
    monkeypatch.setattr(
        google_router,
        "get_settings",
        lambda: SimpleNamespace(api_public_base_url="https://fihrist.world/"),
    )
    assert (
        google_router._redirect_uri(_req()) == "https://fihrist.world/api/v1/auth/google/callback"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "http://fihrist.world",
        "https://u:p@fihrist.world",
        "https://fihrist.world/x",
        "fihrist.world",
        "",
    ],
)
def test_an_unsafe_or_missing_public_origin_falls_back_to_the_request_host(monkeypatch, bad):
    monkeypatch.setattr(
        google_router, "get_settings", lambda: SimpleNamespace(api_public_base_url=bad)
    )
    assert google_router._public_base() is None
    assert google_router._redirect_uri(_req("localhost:8000", "http")) == (
        "http://localhost:8000/api/v1/auth/google/callback"
    )


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
    from app.platform.identity.models import RefreshToken

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


# ------------------------------------------- an unexpected failure must not be a bare JSON 500


class _WatchedSession:
    """Stands in for the request session and remembers whether it was rolled back."""

    def __init__(self):
        self.rolled_back = 0

    async def rollback(self):
        self.rolled_back += 1


def _client_with(session, monkeypatch):
    monkeypatch.setattr(google_router, "_google_config", lambda: ("cid", "secret"))
    app = FastAPI()
    app.include_router(google_router.router, prefix="/api/v1")

    async def _session():
        yield session

    from app.platform.identity.deps import get_db

    app.dependency_overrides[get_db] = _session
    return TestClient(app, follow_redirects=False)


def test_an_unexpected_error_sends_the_person_back_to_login_and_rolls_back(monkeypatch, caplog):
    """It used to be `{"error": {"code": "internal_error"}}` on a page with no way back."""
    _fake_google(monkeypatch, {"email": "a@b.com", "email_verified": True})
    session = _WatchedSession()

    async def broken(session, **kw):
        raise RuntimeError('relation "x" does not exist')

    monkeypatch.setattr(AuthService, "login_with_google", staticmethod(broken))
    with caplog.at_level("ERROR"):
        res = _client_with(session, monkeypatch).get(
            "/api/v1/auth/google/callback", params={"code": "c", "state": _valid_state()}
        )
    assert res.status_code == 302
    assert res.headers["location"] == "/login?error=google_failed"
    assert not res.headers.get_list("set-cookie"), "no session may be issued on a failure"
    assert session.rolled_back == 1, "get_db commits on a normal return: roll back first"
    logged = [r for r in caplog.records if r.getMessage() == "unhandled_error"]
    assert logged and logged[0].error == "RuntimeError"
    assert logged[0].exc_info, "the traceback is what an operator needs"


def test_a_failing_google_network_call_is_a_retry_not_a_server_error(monkeypatch):
    import httpx

    class _Down:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...
        async def post(self, *a, **k):
            raise httpx.ConnectTimeout("google is unreachable")

    monkeypatch.setattr(google_router.httpx, "AsyncClient", _Down)
    res = _client_with(_WatchedSession(), monkeypatch).get(
        "/api/v1/auth/google/callback", params={"code": "c", "state": _valid_state()}
    )
    assert res.status_code == 302
    assert res.headers["location"] == "/login?error=google_token_exchange"


def test_the_known_refusals_do_not_roll_back_or_change(monkeypatch):
    """The new catch-all must not swallow the cases that already had a readable code."""
    _fake_google(monkeypatch, {"email": "a@b.com", "email_verified": True})
    session = _WatchedSession()

    async def mfa(session, **kw):
        raise GoogleMfaRequired("mfa")

    monkeypatch.setattr(AuthService, "login_with_google", staticmethod(mfa))
    res = _client_with(session, monkeypatch).get(
        "/api/v1/auth/google/callback", params={"code": "c", "state": _valid_state()}
    )
    assert res.headers["location"] == "/login?error=google_mfa_required"
    assert session.rolled_back == 0


async def test_a_signup_that_fails_midway_leaves_no_half_made_workspace(db, monkeypatch):
    """The real danger of swallowing an error: `get_db` commits whatever was written so far.

    `register` has already flushed the user and tenant when the tenant-created hooks run. If a
    hook raises and the route answers normally, that half-made workspace would be committed
    with no defaults seeded. The rollback has to take it back.
    """
    from httpx import ASGITransport
    from httpx import AsyncClient as RealClient  # captured BEFORE _fake_google replaces it

    from app.core import tenancy

    email = _addr()

    async def boom(session, tenant_id):
        raise RuntimeError("an AI provisioning hook failed")

    monkeypatch.setattr(tenancy, "_tenant_created_hooks", [boom])
    _fake_google(monkeypatch, {"email": email, "email_verified": True})
    monkeypatch.setattr(google_router, "_google_config", lambda: ("cid", "secret"))
    app = FastAPI()
    app.include_router(google_router.router, prefix="/api/v1")

    async def _session():
        # What get_db does: one transaction for the request, committed on a normal return.
        async with db.begin_nested() as tx:
            yield db
            await tx.commit() if tx.is_active else None

    from app.platform.identity.deps import get_db

    app.dependency_overrides[get_db] = _session

    async with RealClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        res = await client.get(
            "/api/v1/auth/google/callback", params={"code": "c", "state": _valid_state()}
        )
    assert res.headers["location"] == "/login?error=google_failed"
    assert (await db.execute(select(User).where(User.email == email))).scalar_one_or_none() is None


# ----------------------- a RETURNING user, in a request that starts with no tenant bound


async def _forget_the_tenant(db) -> None:
    """Make the session look like the start of a fresh request.

    The test session is one long transaction, so the tenant that `register` bound earlier in the
    test would still be bound at sign-in and hide the bug. In production every request opens a new
    transaction with neither GUC set; `set_config(.., true)` is transaction-local.
    """
    await db.execute(text("SELECT set_config('app.tenant_id', '', true)"))
    await db.execute(text("SELECT set_config('app.user_id', '', true)"))


async def test_a_returning_google_user_can_sign_in_when_no_tenant_is_bound_yet(db):
    """Production 500: the audit row names the tenant, audit_logs refuses a row whose tenant is
    not the bound one, and an existing account used to sign in with only app.user_id bound.
    A new account was unaffected (register binds the tenant), so only RETURNING users failed."""
    email = _addr()
    _user, tenant = await AuthService.register(
        db,
        tenant_name="Returning",
        tenant_slug=f"ret-{uuid.uuid4().hex[:8]}",
        email=email,
        password=None,
        full_name="Ret",
        email_verified=True,
    )
    await _forget_the_tenant(db)

    pair, _got, tenant_id = await AuthService.login_with_google(
        db, email=email, email_verified=True
    )

    assert tenant_id == tenant.id and pair.access_token
    written = (
        await db.execute(
            text(
                "SELECT count(*) FROM audit_logs "
                "WHERE tenant_id = :t AND action = 'auth.google_login'"
            ),
            {"t": tenant.id},
        )
    ).scalar_one()
    assert written == 1, "the sign-in must leave its audit row"


async def test_the_test_session_really_enforces_audit_logs_rls(db):
    """Guard for the test above: if the suite ran as a BYPASSRLS role it would prove nothing."""
    bypass = (
        await db.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"))
    ).scalar_one()
    assert bypass is False, "point DATABASE_URL_APP_ADMIN at sales_app, not postgres"
    await _forget_the_tenant(db)
    with pytest.raises(Exception, match="row-level security"):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO audit_logs (id, tenant_id, action, resource_type, source) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), 'x', 'x', 'human')"
                )
            )
