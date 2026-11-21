"""A Meta outage during the link must read as "try again", never as a broken configuration.

Review item A10: five Graph calls in the OAuth link flow called ``.json()`` with no status check, so
a 429 or a 503 with an HTML body surfaced as ``meta_exchange_failed:ValueError`` and the owner went
hunting for a setup mistake that did not exist.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_oauth_state_token
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

_HTML_503 = httpx.Response(503, text="<html><body>Service Unavailable</body></html>")
_HTML_429 = httpx.Response(429, text="<html>slow down</html>")


def _graph(*, broken_step: str, broken: httpx.Response):
    """A healthy Meta, except for ONE step that answers with ``broken``."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params = dict(request.url.params)
        if "/oauth/access_token" in url:
            step = "long_lived" if params.get("grant_type") == "fb_exchange_token" else "exchange"
            if step == broken_step:
                return broken
            body = {"access_token": "user-token-value", "token_type": "bearer"}
            if step == "long_lived":
                body = {"access_token": "long-lived-user-token", "expires_in": 5_183_944}
            elif broken_step == "long_lived":
                body["expires_in"] = 5_183_944
            return httpx.Response(200, json=body)
        if "/me/permissions" in url:
            if broken_step == "permissions":
                return broken
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"permission": p, "status": "granted"} for p in ALL_FACEBOOK_PERMISSIONS
                    ]
                },
            )
        if "/me/accounts" in url:
            if broken_step == "accounts":
                return broken
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
        if "/subscribed_apps" in url:
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"id": PAGE_ID, "name": "Fihrist Page"})

    return handler


async def _callback(db, tenant_ctx, monkeypatch, *, step: str, broken: httpx.Response) -> dict:
    _config_patch(monkeypatch)
    _patch_graph(monkeypatch, _graph(broken_step=step, broken=broken))
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
    return _popup_result(response)


@pytest.mark.parametrize("step", ["exchange", "accounts"])
@pytest.mark.parametrize("broken", [_HTML_503, _HTML_429], ids=["503", "429"])
async def test_a_meta_outage_reads_as_try_again(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch, step, broken
):
    result = await _callback(db, tenant_ctx, monkeypatch, step=step, broken=broken)
    error = result["error"]
    assert "ValueError" not in error and "meta_exchange_failed" not in error, error
    assert error.startswith("meta_unavailable"), error


async def test_a_non_json_success_body_is_an_outage_not_a_crash(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    junk = httpx.Response(200, text="<html>captive portal</html>")
    result = await _callback(db, tenant_ctx, monkeypatch, step="exchange", broken=junk)
    assert result["error"].startswith("meta_unavailable"), result["error"]


async def test_a_real_meta_rejection_is_still_reported_as_a_rejection(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    """The outage handling must not swallow Meta's own explanation of a bad code."""
    rejected = httpx.Response(400, json={"error": {"message": "bad code", "code": 100}})
    result = await _callback(db, tenant_ctx, monkeypatch, step="exchange", broken=rejected)
    assert "bad code" in result["error"]
    assert not result["error"].startswith("meta_unavailable")
