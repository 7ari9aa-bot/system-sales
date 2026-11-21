"""Signup also asks for the shop name, the country and the terms, and none of it is required.

An email and a password alone still make an account exactly as before. When the form sends more,
the shop gets its own name and market, the owner is offered the activity setup once, and the time
the terms were accepted is recorded. A country we do not serve is refused (422), never replaced by
a default. Google sign-in and every older caller are never sent to the setup.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticError
from sqlalchemy import select

from app.core.activity_setup import DONE, NOT_STARTED, read_state
from app.modules.identity.models import Tenant
from app.modules.identity.schemas import RegisterRequest
from app.modules.identity.service import AuthService
from app.modules.settings.service import SettingsService


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    # The route tests post to the real app; the IP rate limiter is not what is under test.
    from app.core.middleware import RateLimitMiddleware

    async def _passthrough(self, request, call_next):
        return await call_next(request)

    monkeypatch.setattr(RateLimitMiddleware, "dispatch", _passthrough)


@pytest.fixture(autouse=True)
def _signup_hook_is_wired():
    # identity stores the form's answers through a hook that activity_setup registers when the app
    # is built. Without this, the service tests below would pass because nothing is ever written.
    from app.main import create_app

    create_app()


def _email() -> str:
    return f"shop-{uuid.uuid4().hex[:8]}@test.local"


async def _register(db, **kw):
    return await AuthService.register(
        db,
        tenant_name=kw.pop("tenant_name", None),
        tenant_slug=None,
        email=_email(),
        password="strong-password-1",
        full_name=None,
        **kw,
    )


async def _terms(db, tid):
    return (await SettingsService(db, tid).resolve("business.terms_accepted_at")).value


# ── the form's fields ─────────────────────────────────────────────────────────────────────────


def test_an_email_and_a_password_alone_are_still_a_valid_signup() -> None:
    body = RegisterRequest(email="a@example.dev", password="strong-password-1")
    assert body.shop_name is None and body.country_code is None and body.terms_accepted is None


def test_the_shop_name_is_trimmed_and_a_blank_one_is_none() -> None:
    ok = RegisterRequest(
        email="a@example.dev", password="strong-password-1", shop_name="  محل نور "
    )
    blank = RegisterRequest(email="a@example.dev", password="strong-password-1", shop_name="   ")
    assert ok.shop_name == "محل نور" and blank.shop_name is None


def test_a_shop_name_over_255_is_refused() -> None:
    with pytest.raises(PydanticError):
        RegisterRequest(email="a@example.dev", password="strong-password-1", shop_name="x" * 256)


@pytest.mark.parametrize("raw,expected", [("eg", "EG"), ("EG", "EG"), (" sa", None), ("sa", "SA")])
def test_a_served_country_is_accepted_in_any_case(raw, expected) -> None:
    if expected is None:
        with pytest.raises(PydanticError):
            RegisterRequest(email="a@example.dev", password="strong-password-1", country_code=raw)
        return
    body = RegisterRequest(email="a@example.dev", password="strong-password-1", country_code=raw)
    assert body.country_code == expected


@pytest.mark.parametrize("code", ["AE", "QA", "US", "XX", "E", "EGY", "1"])
def test_a_country_we_do_not_serve_yet_is_refused_not_defaulted(code) -> None:
    # AE and QA are on the waitlist: accepting them would promise a market that is not open.
    with pytest.raises(PydanticError):
        RegisterRequest(email="a@example.dev", password="strong-password-1", country_code=code)


# ── what the service stores ───────────────────────────────────────────────────────────────────


async def test_the_old_call_makes_the_same_account_and_never_offers_the_setup(db) -> None:
    _user, tenant = await _register(db)
    row = (await db.execute(select(Tenant).where(Tenant.id == tenant.id))).scalar_one()
    assert row.country_code == "EG"
    assert await read_state(db, tenant.id) == DONE
    assert await _terms(db, tenant.id) == ""


async def test_the_form_signup_is_offered_the_setup(db) -> None:
    _user, tenant = await _register(db, offer_activity_setup=True)
    assert await read_state(db, tenant.id) == NOT_STARTED


async def test_the_country_is_stored_on_the_shop(db) -> None:
    _user, tenant = await _register(db, country_code="SA")
    row = (await db.execute(select(Tenant).where(Tenant.id == tenant.id))).scalar_one()
    assert row.country_code == "SA"


async def test_the_shop_name_becomes_the_tenant_name(db) -> None:
    _user, tenant = await _register(db, tenant_name="محل نور")
    assert tenant.name == "محل نور"


async def test_accepting_the_terms_records_when(db) -> None:
    _user, tenant = await _register(db, terms_accepted=True)
    stamp = await _terms(db, tenant.id)
    assert stamp.startswith("20") and "T" in stamp and stamp.endswith("+00:00")


@pytest.mark.parametrize("answer", [False, None])
async def test_not_accepting_or_not_answering_records_nothing_and_still_signs_up(db, answer):
    user, tenant = await _register(db, terms_accepted=answer)
    assert user.id is not None and await _terms(db, tenant.id) == ""


async def test_one_shop_signing_up_does_not_mark_another(db) -> None:
    from app.core.db import bind_tenant

    _u1, a = await _register(db, offer_activity_setup=True, terms_accepted=True)
    _u2, b = await _register(db)
    # Each signup binds its own shop and RLS then shows only that shop, so look at each in turn.
    await bind_tenant(db, b.id)
    assert await read_state(db, b.id) == DONE and await _terms(db, b.id) == ""
    await bind_tenant(db, a.id)
    assert await read_state(db, a.id) == NOT_STARTED
    assert (await _terms(db, a.id)).startswith("20")


# ── the route passes the form through, and only the route offers the setup ────────────────────


async def test_the_route_hands_the_form_to_signup_and_offers_the_setup(monkeypatch) -> None:
    from tests.test_turnstile import _client, _cloudflare, _ok

    seen: dict = {}

    async def spy(session, **kw):
        seen.update(kw)

    monkeypatch.setattr(AuthService, "register", spy)
    _cloudflare(monkeypatch, _ok)
    async with _client() as c:
        r = await c.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.dev",
                "password": "strong-password-1",
                "shop_name": "محل نور",
                "country_code": "sa",
                "terms_accepted": True,
            },
        )
    assert r.status_code == 202, r.text
    assert seen["tenant_name"] == "محل نور"
    assert seen["country_code"] == "SA" and seen["terms_accepted"] is True
    assert seen["offer_activity_setup"] is True


async def test_an_explicit_tenant_name_wins_over_the_shop_name(monkeypatch) -> None:
    from tests.test_turnstile import _client, _cloudflare, _ok

    seen: dict = {}

    async def spy(session, **kw):
        seen.update(kw)

    monkeypatch.setattr(AuthService, "register", spy)
    _cloudflare(monkeypatch, _ok)
    async with _client() as c:
        await c.post(
            "/api/v1/auth/register",
            json={
                "email": "o@example.dev",
                "password": "strong-password-1",
                "tenant_name": "الاسم الصريح",
                "shop_name": "اسم المحل",
            },
        )
    assert seen["tenant_name"] == "الاسم الصريح"


async def test_the_route_refuses_a_country_we_do_not_serve_before_any_account_work(
    monkeypatch,
) -> None:
    from tests.test_turnstile import _client, _cloudflare, _ok

    touched: list[str] = []

    async def tripwire(*a, **kw):
        touched.append("register")

    monkeypatch.setattr(AuthService, "register", tripwire)
    _cloudflare(monkeypatch, _ok)
    async with _client() as c:
        r = await c.post(
            "/api/v1/auth/register",
            json={"email": "o@example.dev", "password": "strong-password-1", "country_code": "US"},
        )
    assert r.status_code == 422
    assert touched == []


async def test_an_old_client_with_only_email_and_password_still_gets_the_neutral_202(
    monkeypatch,
) -> None:
    from tests.test_turnstile import _client, _cloudflare, _ok

    seen: dict = {}

    async def spy(session, **kw):
        seen.update(kw)

    monkeypatch.setattr(AuthService, "register", spy)
    _cloudflare(monkeypatch, _ok)
    async with _client() as c:
        r = await c.post(
            "/api/v1/auth/register",
            json={"email": "o@example.dev", "password": "strong-password-1"},
        )
    assert r.status_code == 202
    assert seen["country_code"] is None and seen["terms_accepted"] is None
    assert seen["tenant_name"] is None


def test_google_signup_never_offers_the_setup() -> None:
    # Only the form route passes offer_activity_setup=True; the Google caller must not.
    import pathlib

    src = pathlib.Path("app/modules/identity/services/auth.py").read_text(encoding="utf-8")
    google_call = src[src.index("user, tenant = await AuthService.register(") :][:600]
    assert "offer_activity_setup" not in google_call


def test_the_signup_choices_hook_is_wired_by_the_app() -> None:
    # identity does not import the settings module (that would close an import cycle), so the
    # answers are stored by a hook that activity_setup registers. If the app stops importing it,
    # a signup would silently store nothing: this fails instead.
    from app.core.tenancy import signup_choice_hooks
    from app.main import create_app

    create_app()
    assert "record_signup_choices" in [h.__name__ for h in signup_choice_hooks()]


def test_identity_does_not_import_the_settings_module() -> None:
    # Checked on the real import statements, not on the text: a parameter named
    # offer_activity_setup is fine, an import of the settings module or of activity_setup is not.
    import ast
    import pathlib

    tree = ast.parse(
        pathlib.Path("app/modules/identity/services/auth.py").read_text(encoding="utf-8")
    )
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    bad = {
        m for m in imported if m.startswith("app.modules.settings") or m.endswith("activity_setup")
    }
    assert not bad, bad


async def test_a_signup_that_is_not_the_form_is_never_offered_the_setup_even_with_terms(db) -> None:
    # Google sign-in and every older caller: no offer, whatever else was sent.
    _u, tenant = await _register(db, terms_accepted=True)
    assert await read_state(db, tenant.id) == DONE
    assert (await _terms(db, tenant.id)).startswith("20")


async def test_the_form_without_terms_is_offered_the_setup_but_records_no_terms(db) -> None:
    _u, tenant = await _register(db, offer_activity_setup=True, terms_accepted=False)
    assert await read_state(db, tenant.id) == NOT_STARTED
    assert await _terms(db, tenant.id) == ""


async def test_a_one_is_not_a_yes_to_the_terms(db) -> None:
    # Only a real True records acceptance; the hook is called directly with look-alikes.
    from app.core.activity_setup import record_signup_choices

    _u, tenant = await _register(db)
    for look_alike in (1, "true", "yes", [1], {"a": 1}):
        await record_signup_choices(
            db, tenant.id, _u.id, {"offer_activity_setup": look_alike, "terms_accepted": look_alike}
        )
    assert await _terms(db, tenant.id) == ""
    assert await read_state(db, tenant.id) == DONE
