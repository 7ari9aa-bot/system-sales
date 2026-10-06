"""Meta OAuth connect flow tests — Facebook Login for Business.

The start route mints a 10-minute signed state and returns Meta's dialog
URL (settings:write holders only). The PUBLIC callback swaps the code for
a user token, picks the first messaging-capable page from /me/accounts,
persists it through the same verification the manual connect uses, and
subscribes the page's webhooks. The Graph API is scripted per test.
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
REDIRECT_URI = "https://api-production-81629.up.railway.app/api/v1/integrations/meta/oauth/callback"
PAGE_ID = "100948385744201"
PAGE_TOKEN = "page-access-token-value"


def _fake_settings():
    """The REAL Settings with the Meta OAuth fields overridden — a bare
    namespace breaks as soon as any code touches another attribute."""
    from app.core.config import get_settings

    s = get_settings()
    s.meta_app_id = APP_ID
    s.meta_app_secret = APP_SECRET
    s.meta_oauth_redirect_uri = REDIRECT_URI
    return s


def _app(db, tenant_ctx, *, permission: bool = True):
    app = create_app()
    ctx = TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"settings:write"} if permission else set(),
    )

    async def _override() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _override
    return app


def _graph_handler(calls: dict, *, user_token="user-token-value", fail_exchange=False):
    """Routes the three Graph calls the flow makes, in any order."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "/oauth/access_token" in url:
            if fail_exchange:
                return httpx.Response(400, json={"error": {"message": "bad code"}})
            return httpx.Response(200, json={"access_token": user_token})
        if "/me/accounts" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": PAGE_ID,
                            "name": "Fihrist Page",
                            "access_token": PAGE_TOKEN,
                            "tasks": ["MESSAGING", "ANALYTICS"],
                        }
                    ]
                },
            )
        if f"/{PAGE_ID}/subscribed_apps" in url:
            return httpx.Response(200, json={"success": True})
        if "/me/accounts" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": PAGE_ID,
                            "name": "Fihrist Page",
                            "access_token": PAGE_TOKEN,
                            "tasks": ["MESSAGING", "ANALYTICS"],
                        }
                    ]
                },
            )
        if "/me?" in url or url.rstrip("/?").endswith("/me"):
            # The messenger ownership check hits /me WITH the page token —
            # the token identifies AS the page.
            return httpx.Response(200, json={"id": PAGE_ID, "name": "Fihrist Page"})
        if f"/{PAGE_ID}" in url:
            # the ownership verification GET (fields=id,name)
            return httpx.Response(200, json={"id": PAGE_ID, "name": "Fihrist Page"})
        return httpx.Response(
            404, json={"error": f"unexpected graph call: {url[:160]}"}
        )

    return handler


def _patch_graph(monkeypatch, handler) -> list[str]:
    calls: list[str] = []
    real_client = httpx.AsyncClient

    def _fake_async_client(**kwargs):
        kwargs.pop("follow_redirects", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client)
    return calls


def _config_patch(monkeypatch):
    fake = _fake_settings()
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


async def test_start_returns_the_meta_dialog_url(db, tenant_ctx, monkeypatch):
    _config_patch(monkeypatch)
    app = _app(db, tenant_ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/api/v1/integrations/meta/oauth/start?provider=messenger")

    assert response.status_code == 200
    url = response.json()["authorize_url"]
    from urllib.parse import quote

    assert f"client_id={APP_ID}" in url
    # The redirect_uri rides the query URL-ENCODED — the raw assertion would
    # fail on the // and the callback registration requires the encoded form.
    assert f"redirect_uri={quote(REDIRECT_URI, safe='')}" in url
    assert "scope=pages_show_list" in url and "pages_messaging" in url
    state = url.split("state=")[1].split("&")[0]
    claims = decode_token(state)
    assert claims["type"] == "oauth_state"
    assert claims["tenant_id"] == str(tenant_ctx.tenant_id)
    assert claims["provider"] == "messenger"


async def test_callback_connects_the_page_and_subscribes_its_webhook(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    _config_patch(monkeypatch)
    calls: list[str] = []
    handler = _graph_handler(calls)
    _patch_graph(monkeypatch, handler)
    print("GRAPH_CALLS_SO_FAR:", calls)

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
    row = (
        await db.execute(sa_select_integration())
    ).scalar_one()
    assert row.provider == "messenger"
    assert row.status == "active"
    stored = decrypt_credentials_dict(row.credentials)
    assert stored["api_key"] == PAGE_TOKEN
    assert row.config["account_id"] == PAGE_ID

    # The page's webhook subscription was registered with the PAGE token.
    assert any(f"/{PAGE_ID}/subscribed_apps" in u for u in calls)


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
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "dead-code", "state": state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "meta_error=" in response.headers["location"]


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



