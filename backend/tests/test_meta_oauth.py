"""Meta OAuth connect flow tests — Facebook Login for Business.

The start route mints a 10-minute signed state and returns Meta's dialog
URL (settings:write holders only). The PUBLIC callback swaps the code for
a user token, exchanges it for a LONG-LIVED one, picks the messaging page
from /me/accounts (the linked IG business account for Instagram), persists
it through the same verification the manual connect uses, and subscribes
the page's webhooks. The Graph API is scripted per test.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.errors import ExternalProviderError
from app.core.secrets import decrypt_credentials_dict
from app.core.security import create_oauth_state_token, decode_token
from app.main import create_app
from app.modules.customers import meta_oauth
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.platform.models import Integration

APP_ID = "1457166436269149"
APP_SECRET = "meta-app-secret-for-tests"
REDIRECT_URI = "https://api.example.com/api/v1/integrations/meta/oauth/callback"
PAGE_ID = "100948385744201"
PAGE_TOKEN = "page-access-token-value"
IG_ID = "17841400000000001"
LONG_LIVED_TOKEN = "long-lived-user-token"
ALL_FACEBOOK_PERMISSIONS = [
    "pages_show_list",
    "pages_messaging",
    "pages_manage_posts",
    "pages_manage_engagement",
    "pages_read_user_content",
    "read_insights",
]


def _fake_settings(*, config_id: str = "", redirect_uri: str = REDIRECT_URI, api_base: str = ""):
    """The REAL Settings with the Meta OAuth fields overridden — a bare
    namespace breaks as soon as any code touches another attribute."""
    from app.core.config import get_settings

    s = get_settings()
    s.meta_app_id = APP_ID
    s.meta_app_secret = APP_SECRET
    s.meta_oauth_redirect_uri = redirect_uri
    s.meta_instagram_config_id = config_id
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
    granted=None,
    permissions_error=False,
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
                    200,
                    json={
                        "access_token": LONG_LIVED_TOKEN,
                        "token_type": "bearer",
                        "expires_in": 5_183_944,
                    },
                )
            if fail_exchange:
                return httpx.Response(400, json={"error": {"message": "bad code", "code": 100}})
            body = {"access_token": user_token, "token_type": "bearer"}
            if long_lived:
                # Short-lived user tokens carry expires_in — the signal the
                # flow uses to attempt the fb_exchange_token grant.
                body["expires_in"] = 5183944
            return httpx.Response(200, json=body)
        if "/me/permissions" in url:
            if permissions_error:
                return httpx.Response(
                    200, json={"error": {"message": "Session has expired", "code": 190}}
                )
            names = ALL_FACEBOOK_PERMISSIONS if granted is None else granted
            return httpx.Response(
                200, json={"data": [{"permission": n, "status": "granted"} for n in names]}
            )
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


async def test_page_webhook_subscription_must_be_explicitly_accepted() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"success": True}))
    ) as client:
        await meta_oauth._subscribe_page_to_app(client, page_id=PAGE_ID, page_token=PAGE_TOKEN)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"error": {"message": "denied"}})
        )
    ) as client:
        with pytest.raises(ExternalProviderError, match="webhook subscription"):
            await meta_oauth._subscribe_page_to_app(client, page_id=PAGE_ID, page_token=PAGE_TOKEN)


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


def _popup_result(response) -> dict:
    """The outcome the callback posts back to the opener window.

    The callback no longer redirects: it answers with a small self-closing page whose script carries
    ``var msg = {...}`` (what ``window.opener.postMessage`` delivers). That JSON is the contract the
    settings screen reads, so the tests read it instead of a ``Location`` header.
    """
    assert response.status_code == 200, response.text[:200]
    assert response.headers["content-type"].startswith("text/html")
    found = re.search(r"var msg = (\{.*?\});", response.text)
    assert found, "the popup page must carry the result for the opener window"
    msg = json.loads(found.group(1))
    assert msg["type"] == "META_OAUTH_RESULT"
    return msg


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
    assert "/v27.0/dialog/oauth?" in url
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


@pytest.mark.parametrize("provider", ["facebook", "messenger"])
async def test_instagram_config_never_replaces_other_channels_scopes(
    db, tenant_ctx, monkeypatch, provider
):
    """Instagram's configuration id must not narrow Facebook or Messenger:
    they keep requesting their own scope lists (incl. the Page post scopes)."""
    _config_patch(monkeypatch, config_id="2761697214337369")
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get(f"/api/v1/integrations/meta/oauth/start?provider={provider}")
    url = response.json()["authorize_url"]
    assert "config_id" not in url
    assert "override_default_response_type" not in url
    assert "scope=" in url
    if provider == "facebook":
        assert "pages_manage_posts" in url


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
    result = _popup_result(response)
    assert result["connected"].startswith("messenger:")

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
    assert "connected" in _popup_result(response)
    # The fb_exchange_token grant ran and the PAGE listing then used the
    # LONG-LIVED token — page tokens minted from it do not expire.
    exchange = next(u for u in calls if "fb_exchange_token" in u)
    assert "grant_type=fb_exchange_token" in exchange
    listing = next(u for u in calls if "/me/accounts" in u)
    assert f"access_token={LONG_LIVED_TOKEN}" in listing
    row = (await db.execute(sa_select_integration())).scalar_one()
    assert decrypt_credentials_dict(row.credentials)["api_key"] == PAGE_TOKEN


async def test_business_login_uses_expiring_system_user_refresh_contract(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch, config_id="business-login-config")
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

    assert "connected" in _popup_result(response)
    exchange = next(u for u in calls if "fb_exchange_token" in u)
    assert "set_token_expires_in_60_days=true" in exchange
    row = (await db.execute(sa_select_integration())).scalar_one()
    stored = decrypt_credentials_dict(row.credentials)
    assert stored["_meta"]["refreshable"] is True
    assert stored["_meta"]["source_access_token"] == LONG_LIVED_TOKEN
    assert stored["_meta"]["page_id"] == PAGE_ID
    assert stored["_meta"]["expires_at"]


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
    assert "connected" in _popup_result(response)
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
    result = _popup_result(response)
    # the failure is tagged with the provider and names the missing professional Instagram account
    assert result["error"].startswith("instagram:")
    assert "إنستجرام" in result["error"]


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
    # The Meta error message rides the popup result, never swallowed into a generic failure.
    assert "Session has expired" in _popup_result(response)["error"]


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
    assert "error" in _popup_result(response)


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
    result = _popup_result(response)
    assert result["error"].startswith("access_denied:")
    assert "Permissions" in result["error"]
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
    assert _popup_result(response)["error"] == "invalid_state"
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
    assert _popup_result(response)["error"] == "invalid_state"
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
    assert _popup_result(response)["error"] == "invalid_provider"
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
    assert "error" in _popup_result(response)


def sa_select_integration():
    import sqlalchemy as sa

    return sa.select(Integration)


async def _facebook_callback(db, tenant_ctx, monkeypatch, **graph):
    _config_patch(monkeypatch)
    calls: list[str] = []
    _patch_graph(monkeypatch, _graph_handler(calls, **graph))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "facebook"},
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    return _popup_result(response), calls


async def test_facebook_connect_records_the_permissions_meta_granted(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    result, _calls = await _facebook_callback(db, tenant_ctx, monkeypatch)
    assert result["connected"].startswith("facebook:")
    row = (await db.execute(sa_select_integration())).scalar_one()
    assert set(row.config["_connection"]["granted_scopes"]) == set(ALL_FACEBOOK_PERMISSIONS)


async def test_facebook_connect_is_refused_when_one_permission_was_unticked(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    # The Meta dialog lets the owner untick a single permission and carry on. Connecting anyway
    # would show a green channel that fails on its first post, so it is refused and named.
    granted = [n for n in ALL_FACEBOOK_PERMISSIONS if n != "pages_manage_posts"]
    result, _calls = await _facebook_callback(db, tenant_ctx, monkeypatch, granted=granted)
    assert "connected" not in result
    assert "pages_manage_posts" in result["error"]
    assert (await db.execute(sa_select_integration())).scalar_one_or_none() is None


async def test_facebook_connect_is_refused_when_the_permissions_cannot_be_read(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    result, _calls = await _facebook_callback(db, tenant_ctx, monkeypatch, permissions_error=True)
    assert "connected" not in result
    assert (await db.execute(sa_select_integration())).scalar_one_or_none() is None


async def test_messenger_connect_does_not_need_the_page_permissions(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    # A chat-only store grants no posting rights and must still connect.
    _config_patch(monkeypatch)
    _patch_graph(monkeypatch, _graph_handler([], granted=["pages_messaging"]))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": "messenger"},
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert _popup_result(response)["connected"].startswith("messenger:")


async def test_a_refused_page_subscription_fails_the_connect() -> None:
    """A Page Meta will not deliver webhooks for must not be stored as connected."""
    from app.core.errors import ExternalProviderError
    from app.modules.customers.meta_oauth import _subscribe_page_to_app

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "(#200) Permissions error"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as http:
        with pytest.raises(ExternalProviderError):
            await _subscribe_page_to_app(http, page_id="1", page_token="t", provider="facebook")


async def test_a_subscription_that_does_not_say_success_fails_the_connect() -> None:
    from app.core.errors import ExternalProviderError
    from app.modules.customers.meta_oauth import _subscribe_page_to_app

    def odd(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(odd)) as http:
        with pytest.raises(ExternalProviderError):
            await _subscribe_page_to_app(http, page_id="1", page_token="t", provider="messenger")


async def test_a_unreachable_meta_during_subscription_is_a_retryable_failure() -> None:
    from app.core.errors import ExternalProviderError
    from app.modules.customers.meta_oauth import _subscribe_page_to_app

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as http:
        with pytest.raises(ExternalProviderError):
            await _subscribe_page_to_app(http, page_id="1", page_token="t", provider="instagram")


@pytest.mark.parametrize(
    ("provider", "field"),
    [("facebook", "feed"), ("instagram", "comments"), ("messenger", "messages")],
)
async def test_the_subscription_asks_for_the_channels_own_fields(provider, field) -> None:
    from app.modules.customers.meta_oauth import _subscribe_page_to_app

    seen: dict[str, str] = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(ok)) as http:
        await _subscribe_page_to_app(http, page_id="1", page_token="tok", provider=provider)
    assert field in seen["subscribed_fields"].split(",")
    assert seen["access_token"] == "tok"
