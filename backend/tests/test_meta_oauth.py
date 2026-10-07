"""Meta OAuth connect flow tests — Facebook Login for Business.

The start route mints a 10-minute signed state and returns Meta's dialog
URL (settings:write holders only). The PUBLIC callback swaps the code for
a user token, exchanges it for a LONG-LIVED one, picks the messaging page
from /me/accounts (the linked IG business account for Instagram), persists
it through the same verification the manual connect uses, and subscribes
the page's webhooks. The Graph API is scripted per test.
"""

from __future__ import annotations

import httpx
from httpx import ASGITransport, AsyncClient

from app.core.secrets import decrypt_credentials_dict
from app.core.security import create_oauth_state_token, decode_token
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.platform.models import Integration

APP_ID = "1457166436269149"
APP_SECRET = "meta-app-secret-for-tests"
REDIRECT_URI = "https://api.example.com/api/v1/integrations/meta/oauth/callback"
PAGE_ID = "100948385744201"
PAGE_TOKEN = "page-access-token-value"
IG_ID = "17841400000000001"
LONG_LIVED_TOKEN = "long-lived-user-token"


def _fake_settings(*, config_id: str = "", redirect_uri: str = REDIRECT_URI, api_base: str = ""):
    """The REAL Settings with the Meta OAuth fields overridden — a bare
    namespace breaks as soon as any code touches another attribute."""
    from app.core.config import get_settings

    s = get_settings()
    s.meta_app_id = APP_ID
    s.meta_app_secret = APP_SECRET
    s.meta_oauth_redirect_uri = redirect_uri
    s.meta_oauth_config_id = config_id
    s.api_public_base_url = api_base
    return s


def _app(db, tenant_ctx, *, permission: bool = True):
    app = create_app()
    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"settings:write"} if permission else set(),
    )

    async def _override() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _override
    return app


def _graph_handler(
    calls: dict,
    *,
    user_token="user-token-value",
    fail_exchange=False,
    long_lived=False,
    accounts_error=False,
    instagram=False,
):
    """Routes the Graph calls the flow makes, in any order. The code swap
    and the long-lived exchange share the /oauth/access_token path — they
    are told apart by grant_type."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        params = dict(request.url.params)
        if "/oauth/access_token" in url:
            if params.get("grant_type") == "fb_exchange_token":
                return httpx.Response(
                    200, json={"access_token": LONG_LIVED_TOKEN, "token_type": "bearer"}
                )
            if fail_exchange:
                return httpx.Response(400, json={"error": {"message": "bad code", "code": 100}})
            body = {"access_token": user_token, "token_type": "bearer"}
            if long_lived:
                # Short-lived user tokens carry expires_in — the signal the
                # flow uses to attempt the fb_exchange_token grant.
                body["expires_in"] = 5183944
            return httpx.Response(200, json=body)
        if "/me/accounts" in url:
            if accounts_error:
                return httpx.Response(
                    200, json={"error": {"message": "Session has expired", "code": 190}}
                )
            page = {
                "id": PAGE_ID,
                "name": "Fihrist Page",
                "access_token": PAGE_TOKEN,
                "tasks": ["MESSAGING", "ANALYTICS"],
            }
            if instagram:
                page["instagram_business_account"] = {"id": IG_ID, "username": "fihrist"}
            return httpx.Response(200, json={"data": [page]})
        if f"/{PAGE_ID}/subscribed_apps" in url:
            return httpx.Response(200, json={"success": True})
        if "/me?" in url or url.rstrip("/?").endswith("/me"):
            # The messenger ownership check hits /me WITH the page token —
            # the token identifies AS the page.
            return httpx.Response(200, json={"id": PAGE_ID, "name": "Fihrist Page"})
        if f"/{IG_ID}" in url:
            # The instagram ownership verification GET (fields=id,username)
            # runs against the LINKED IG account with the page token.
            return httpx.Response(200, json={"id": IG_ID, "username": "fihrist"})
        if f"/{PAGE_ID}" in url:
            # the ownership verification GET (fields=id,name)
            return httpx.Response(200, json={"id": PAGE_ID, "name": "Fihrist Page"})
        return httpx.Response(404, json={"error": f"unexpected graph call: {url[:160]}"})

    return handler


def _patch_graph(monkeypatch, handler) -> list[str]:
    calls: list[str] = []
    real_client = httpx.AsyncClient

    def _fake_async_client(**kwargs):
        kwargs.pop("follow_redirects", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client)
    return calls


def _config_patch(monkeypatch, **kwargs):
    fake = _fake_settings(**kwargs)
    monkeypatch.setattr("app.core.config.get_settings", lambda: fake)
    return fake


async def test_start_requires_settings_write(db, tenant_ctx):
    app = _app(db, tenant_ctx, permission=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/v1/integrations/meta/oauth/start?provider=messenger")
    assert response.status_code == 403


async def test_start_refuses_providers_outside_meta_oauth(db, tenant_ctx):
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/v1/integrations/meta/oauth/start?provider=whatsapp")
    assert response.status_code in (400, 422)


async def test_start_fails_loudly_when_unconfigured(db, tenant_ctx, monkeypatch):
    _config_patch(monkeypatch, redirect_uri="", api_base="")
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/v1/integrations/meta/oauth/start?provider=messenger")
    assert response.status_code == 400
    assert "META_APP_ID" in response.json()["error"]["message"]


async def test_start_derives_the_redirect_uri_from_the_api_base_url(db, tenant_ctx, monkeypatch):
    _config_patch(monkeypatch, redirect_uri="", api_base="https://api.example.com")
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/v1/integrations/meta/oauth/start?provider=messenger")
    from urllib.parse import quote

    derived = "https://api.example.com/api/v1/integrations/meta/oauth/callback"
    assert response.status_code == 200
    assert f"redirect_uri={quote(derived, safe='')}" in response.json()["authorize_url"]


async def test_start_returns_the_meta_dialog_url(db, tenant_ctx, monkeypatch):
    _config_patch(monkeypatch)
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/v1/integrations/meta/oauth/start?provider=messenger")

    assert response.status_code == 200
    url = response.json()["authorize_url"]
    from urllib.parse import quote

    # One pinned version for the dialog (the changelog's current one).
    assert "/v26.0/dialog/oauth?" in url
    assert f"client_id={APP_ID}" in url
    # The redirect_uri rides the query URL-ENCODED — the raw assertion would
    # fail on the // and the callback registration requires the encoded form.
    assert f"redirect_uri={quote(REDIRECT_URI, safe='')}" in url
    assert "scope=pages_show_list" in url and "pages_messaging" in url
    assert "response_type=code" in url
    state = dict(pair.split("=", 1) for pair in url.split("?", 1)[1].split("&"))["state"]
    claims = decode_token(state)
    assert claims["type"] == "oauth_state"
    assert claims["tenant_id"] == str(tenant_ctx.tenant_id)
    assert claims["provider"] == "messenger"


async def test_start_requests_instagram_message_scopes(db, tenant_ctx, monkeypatch):
    _config_patch(monkeypatch)
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/v1/integrations/meta/oauth/start?provider=instagram")
    query = dict(
        pair.split("=", 1) for pair in response.json()["authorize_url"].split("?", 1)[1].split("&")
    )
    scope = query["scope"]
    # instagram_manage_messages is the REAL permission; instagram_messaging
    # does not exist and makes Meta reject the whole dialog.
    assert "instagram_manage_messages" in scope
    assert "instagram_messaging" not in scope
    assert "pages_messaging" in scope


async def test_start_uses_config_id_for_business_login(db, tenant_ctx, monkeypatch):
    _config_patch(monkeypatch, config_id="1234567890")
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/v1/integrations/meta/oauth/start?provider=instagram")
    url = response.json()["authorize_url"]
    assert "config_id=1234567890" in url
    assert "override_default_response_type=true" in url
    # The business configuration replaces the scope list on the dialog.
    assert "scope=" not in url


async def test_callback_connects_the_page_and_subscribes_its_webhook(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    handler = _graph_handler(calls)
    _patch_graph(monkeypatch, handler)

    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "messenger"},
    )
    app = _app(db, tenant_ctx)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )

    # The outcome lands back on the settings page, never a bare error page.
    assert response.status_code == 302
    assert "/settings/channels?meta_connected=" in response.headers["location"]
    assert "messenger" in response.headers["location"]

    # The page token is stored as the channel credential (encrypted at rest).
    row = (await db.execute(sa_select_integration())).scalar_one()
    assert row.provider == "messenger"
    assert row.status == "active"
    stored = decrypt_credentials_dict(row.credentials)
    assert stored["api_key"] == PAGE_TOKEN
    assert row.config["account_id"] == PAGE_ID

    # The page's webhook subscription was registered with the PAGE token.
    assert any(f"/{PAGE_ID}/subscribed_apps" in u for u in calls)


async def test_callback_exchanges_for_a_long_lived_token(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    _patch_graph(monkeypatch, _graph_handler(calls, long_lived=True))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "messenger"},
    )
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_connected=" in response.headers["location"]
    # The fb_exchange_token grant ran and the PAGE listing then used the
    # LONG-LIVED token — page tokens minted from it do not expire.
    exchange = next(u for u in calls if "fb_exchange_token" in u)
    assert "grant_type=fb_exchange_token" in exchange
    listing = next(u for u in calls if "/me/accounts" in u)
    assert f"access_token={LONG_LIVED_TOKEN}" in listing
    row = (await db.execute(sa_select_integration())).scalar_one()
    assert decrypt_credentials_dict(row.credentials)["api_key"] == PAGE_TOKEN


async def test_callback_connects_instagram_via_the_ig_account(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    _patch_graph(monkeypatch, _graph_handler(calls, instagram=True))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "instagram"},
    )
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_connected=" in response.headers["location"]
    # Webhook routing AND the gateway's send both key on the IG account id:
    # it must ride the config (routing) AND the encrypted credentials (send).
    row = (await db.execute(sa_select_integration())).scalar_one()
    assert row.provider == "instagram"
    assert row.config["account_id"] == IG_ID
    stored = decrypt_credentials_dict(row.credentials)
    assert stored["account_id"] == IG_ID
    assert stored["api_key"] == PAGE_TOKEN
    # The ownership verification ran against the IG account, not the page.
    assert any(f"/{IG_ID}?" in u for u in calls)


async def test_callback_reports_when_no_ig_account_is_linked(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    # A page WITHOUT instagram_business_account cannot carry Instagram DMs.
    _patch_graph(monkeypatch, _graph_handler(calls, instagram=False))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "instagram"},
    )
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_error=" in response.headers["location"]
    assert "Instagram" in response.headers["location"]


async def test_callback_surfaces_meta_page_listing_errors(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    _patch_graph(monkeypatch, _graph_handler(calls, accounts_error=True))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "messenger"},
    )
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    # The Meta error message rides the redirect — never swallowed into a
    # generic "no page" failure. The redirect is quote_plus-encoded, so the
    # spaces arrive as '+' (URLSearchParams on the frontend decodes both
    # forms to spaces; asserting the wire form keeps the contract exact).
    assert "Session+has+expired" in response.headers["location"]


async def test_callback_surfaces_a_rejected_code(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    _patch_graph(monkeypatch, _graph_handler(calls, fail_exchange=True))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "messenger"},
    )
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "dead-code", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_error=" in response.headers["location"]


async def test_callback_surfaces_meta_dialog_errors(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    """A dev-mode app shown to a non-tester (or a cancelled consent) comes
    back with error params instead of a code — the operator must see WHY."""
    _config_patch(monkeypatch)
    calls: list[str] = []
    _patch_graph(monkeypatch, _graph_handler(calls))
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={
                "error": "access_denied",
                "error_code": "200",
                "error_description": "Permissions have not been granted",
                "state": "whatever",
            },
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_error=access_denied" in response.headers["location"]
    assert "Permissions" in response.headers["location"]
    assert calls == [], "a dialog error must never reach the Graph API"


async def test_callback_refuses_a_tampered_state(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    _patch_graph(monkeypatch, _graph_handler(calls))
    app = _app(db, tenant_ctx)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "x", "state": "forged-state"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_error=invalid_state" in response.headers["location"]
    assert calls == [], "a forged state must never reach the Graph API"


async def test_callback_refuses_an_expired_state(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    _patch_graph(monkeypatch, _graph_handler(calls))
    app = _app(db, tenant_ctx)
    expired = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "messenger"},
        ttl_seconds=-1,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "x", "state": expired},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_error=invalid_state" in response.headers["location"]
    assert calls == []


async def test_callback_refuses_state_with_a_foreign_provider(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    _patch_graph(monkeypatch, _graph_handler(calls))
    app = _app(db, tenant_ctx)
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "whatsapp"},
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "x", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_error=invalid_provider" in response.headers["location"]
    assert calls == []


async def test_callback_reports_when_no_messaging_page_was_authorized(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    real_client = httpx.AsyncClient

    def _no_messaging_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/oauth/access_token" in url:
            return httpx.Response(200, json={"access_token": "user-token-value"})
        if "/me/accounts" in url:
            return httpx.Response(
                200,
                json={"data": [{"id": PAGE_ID, "name": "Fihrist Page", "tasks": ["ANALYTICS"]}]},
            )
        return httpx.Response(404, json={})

    def _fake_async_client(**kwargs):
        kwargs.pop("follow_redirects", None)
        return real_client(transport=httpx.MockTransport(_no_messaging_handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client)
    app = _app(db, tenant_ctx)
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "messenger"},
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_error=" in response.headers["location"]


def sa_select_integration():
    import sqlalchemy as sa

    return sa.select(Integration)
