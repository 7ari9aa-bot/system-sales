"""Batch B: the Meta link must not silently lose what the owner already had.

A5  A Page's webhook subscription REPLACES the field list. Linking Messenger on a Page that
    Facebook already linked used to drop ``feed``, so its comments stopped with no error.
A2  ``refreshable`` came from the INSTAGRAM config id for every provider: a Messenger or
    Facebook token was marked renewable by a setting that is not theirs, and an Instagram
    token was not renewable when only its own setting was missing.
A4  Meta's "this grant is dead" codes other than 190/102 (10, 200, 368, and the 190 subcodes)
    kept the channel ``active`` and retried every 12 hours, instead of asking for a reconnect.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_oauth_state_token
from app.modules.customers import meta_oauth
from app.modules.platform.models import Integration
from app.workers import meta_token_refresh as refresh
from tests.test_meta_oauth import (
    ALL_FACEBOOK_PERMISSIONS,
    PAGE_ID,
    PAGE_TOKEN,
    _app,
    _config_patch,
    _patch_graph,
    _popup_result,
)

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- A5 ---------


def _subscription_graph(*, already: str, posted: list[dict]):
    """A Meta whose Page is ALREADY subscribed to ``already`` and which, like the real one,
    replaces the list on every POST."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params = dict(request.url.params)
        if "/subscribed_apps" in url:
            if request.method == "GET":
                data = [{"id": "app", "subscribed_fields": already.split(",")}] if already else []
                return httpx.Response(200, json={"data": data})
            posted.append(params)
            return httpx.Response(200, json={"success": True})
        if "/oauth/access_token" in url:
            return httpx.Response(200, json={"access_token": "user-token-value"})
        if "/me/permissions" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"permission": p, "status": "granted"} for p in ALL_FACEBOOK_PERMISSIONS
                    ]
                },
            )
        if "/me/accounts" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": PAGE_ID,
                            "name": "Fihrist Page",
                            "access_token": PAGE_TOKEN,
                            "tasks": ["MESSAGING"],
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"id": PAGE_ID, "name": "Fihrist Page"})

    return handler


async def _link(
    db, tenant_ctx, monkeypatch, provider: str, *, already: str, **config
) -> list[dict]:
    _config_patch(monkeypatch, **config)
    posted: list[dict] = []
    _patch_graph(monkeypatch, _subscription_graph(already=already, posted=posted))
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": provider},
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert "connected" in _popup_result(response), "the link itself must succeed"
    return posted


async def test_linking_messenger_keeps_the_feed_field_facebook_already_subscribed(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    already = meta_oauth.subscribed_fields("facebook")  # includes ``feed``
    posted = await _link(db, tenant_ctx, monkeypatch, "messenger", already=already)
    sent = set(posted[-1]["subscribed_fields"].split(","))
    assert "feed" in sent, f"feed was dropped, Facebook comments would stop: {sorted(sent)}"
    assert set(meta_oauth.subscribed_fields("messenger").split(",")) <= sent


async def test_a_first_link_subscribes_exactly_the_channels_own_fields(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    posted = await _link(db, tenant_ctx, monkeypatch, "messenger", already="")
    assert set(posted[-1]["subscribed_fields"].split(",")) == set(
        meta_oauth.subscribed_fields("messenger").split(",")
    )


async def test_an_unreadable_existing_subscription_never_blocks_the_link(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    """A read of what is already there that FAILS refuses the link, and writes nothing.

    The earlier reading of this case called the read "a courtesy" and linked anyway with the
    channel's own fields. Meta replaces the whole subscribed_fields list on every POST, so
    linking "anyway" is not a courtesy: a Page Facebook already linked for its comments loses
    `feed` the moment a guessed list is written, silently, with no error anywhere. The flow now
    retries the read once and then refuses with a retryable message, so the operator tries again
    instead of quietly losing the other channel's webhooks."""
    _config_patch(monkeypatch)
    posted: list[dict] = []
    base = _subscription_graph(already="", posted=posted)

    def handler(request: httpx.Request) -> httpx.Response:
        if "/subscribed_apps" in str(request.url) and request.method == "GET":
            return httpx.Response(503, text="<html>down</html>")
        return base(request)

    _patch_graph(monkeypatch, handler)
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
    result = _popup_result(response)
    assert "connected" not in result, f"a blind write must not be linked: {result}"
    assert result["error"].startswith("meta_unavailable:")
    assert not posted, "nothing may be written when the existing fields could not be read"


# --------------------------------------------------------------------------- A2 ---------


async def _refreshable_after_link(
    db, tenant_ctx, monkeypatch, provider: str, *, expires_in, **config
) -> bool:
    _config_patch(monkeypatch, **config)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params = dict(request.url.params)
        if "/oauth/access_token" in url:
            body = {"access_token": "user-token-value"}
            if expires_in:
                body["expires_in"] = expires_in
            return httpx.Response(200, json=body)
        if "/me/permissions" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"permission": p, "status": "granted"} for p in ALL_FACEBOOK_PERMISSIONS
                    ]
                },
            )
        if "/me/accounts" in url:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": PAGE_ID,
                            "name": "P",
                            "access_token": PAGE_TOKEN,
                            "tasks": ["MESSAGING"],
                            "instagram_business_account": {"id": "17841400000000001"},
                        }
                    ]
                },
            )
        if "/subscribed_apps" in url:
            if request.method == "GET":
                return httpx.Response(200, json={"data": []})
            return httpx.Response(200, json={"success": True})
        _ = params
        if "17841400000000001" in url:
            return httpx.Response(200, json={"id": "17841400000000001", "username": "p"})
        return httpx.Response(200, json={"id": PAGE_ID, "name": "P"})

    _patch_graph(monkeypatch, handler)
    state = create_oauth_state_token(
        str(tenant_ctx.user.id),
        {"tenant_id": str(tenant_ctx.tenant_id), "provider": provider},
    )
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as c:
        response = await c.get(
            "/api/v1/integrations/meta/oauth/callback",
            params={"code": "auth-code-1", "state": state},
            follow_redirects=False,
        )
    assert "connected" in _popup_result(response)
    import sqlalchemy as sa

    row = (
        await db.execute(
            sa.select(Integration).where(
                Integration.tenant_id == tenant_ctx.tenant_id, Integration.provider == provider
            )
        )
    ).scalar_one()
    from app.modules.platform.services.secrets import IntegrationCredentialsService

    creds = await IntegrationCredentialsService.decrypt(db, row)
    return bool(creds["_meta"]["refreshable"])


@pytest.mark.parametrize("provider", ["messenger", "facebook"])
async def test_messenger_and_facebook_are_not_made_renewable_by_the_instagram_setting(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch, provider
):
    renewable = await _refreshable_after_link(
        db, tenant_ctx, monkeypatch, provider, expires_in=5_183_944, config_id="ig-config-1"
    )
    assert renewable is False, "a setting that belongs to Instagram marked this channel renewable"


async def test_instagram_is_renewable_when_its_own_config_id_is_set(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    renewable = await _refreshable_after_link(
        db, tenant_ctx, monkeypatch, "instagram", expires_in=5_183_944, config_id="ig-config-1"
    )
    assert renewable is True


# --------------------------------------------------------------------------- A4 ---------


class _Session:
    async def flush(self):
        return None


def _due_credentials() -> dict:
    return {
        "page_access_token": "old-page",
        "_meta": {
            "refreshable": True,
            "source_access_token": "old-source",
            "page_id": PAGE_ID,
            "expires_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
    }


async def _run_refresh(monkeypatch, response: httpx.Response) -> Integration:
    from app.core.config import get_settings
    from app.modules.platform.services.audit import AuditService
    from app.modules.platform.services.secrets import IntegrationCredentialsService

    integration = Integration(provider="facebook", status="active", credentials={})
    integration.tenant_id = None
    credentials = _due_credentials()

    async def decrypt(_s, _i):
        return {**credentials, "_meta": dict(credentials["_meta"])}

    async def audit(*_a, **_k):
        return None

    monkeypatch.setattr(IntegrationCredentialsService, "decrypt", decrypt)
    monkeypatch.setattr(AuditService, "write", audit)
    settings = get_settings()
    settings.meta_app_id = "app-id"
    settings.meta_app_secret = "app-secret"
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: response)) as client:
        await refresh.refresh_integration(_Session(), integration, client)
    return integration


@pytest.mark.parametrize(
    ("code", "subcode"),
    [(10, None), (200, None), (368, None), (190, 460), (190, 463), (190, 467), (190, 458)],
)
async def test_a_dead_grant_asks_for_a_reconnect_instead_of_retrying_forever(
    monkeypatch, code, subcode
):
    error = {"message": "x", "code": code}
    if subcode:
        error["error_subcode"] = subcode
    integration = await _run_refresh(monkeypatch, httpx.Response(400, json={"error": error}))
    assert integration.status == "reauth_required", (code, subcode)


@pytest.mark.parametrize(
    "response", [httpx.Response(503, text="<html>down</html>"), httpx.Response(429, text="slow")]
)
async def test_a_meta_outage_keeps_the_channel_active_and_retries(monkeypatch, response):
    integration = await _run_refresh(monkeypatch, response)
    assert integration.status == "active"


async def test_an_unknown_error_does_not_disconnect_a_working_channel(monkeypatch):
    """Only the codes Meta documents as 'the grant is gone' may take a channel down."""
    integration = await _run_refresh(
        monkeypatch, httpx.Response(400, json={"error": {"message": "?", "code": 1}})
    )
    assert integration.status == "active"
