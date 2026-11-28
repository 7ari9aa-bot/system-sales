from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx

from app.core.meta_tokens import token_expiry
from app.core.secrets import decrypt_credentials_dict
from app.platform.platform.models import Integration
from app.workers import meta_token_refresh as refresh


def test_token_expiry_requires_a_positive_numeric_lifetime() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert token_expiry(60, now=now) == (now + timedelta(seconds=60)).isoformat()
    assert token_expiry(None, now=now) is None
    assert token_expiry(0, now=now) is None


def test_due_only_refreshes_marked_tokens_inside_the_seven_day_window() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    creds = {"_meta": {"refreshable": True, "expires_at": (now + timedelta(days=6)).isoformat()}}
    assert refresh._due(creds, now)
    creds["_meta"]["expires_at"] = (now + timedelta(days=8)).isoformat()
    assert not refresh._due(creds, now)
    creds["_meta"]["refreshable"] = False
    assert not refresh._due(creds, now)


async def test_system_user_refresh_uses_meta_60_day_rotation_contract() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(
            200,
            json={"access_token": "rotated-system-token", "expires_in": 5_183_944},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token, expires_at = await refresh._refresh_source_token(
            client, "old-system-token", app_id="app-id", app_secret="app-secret"
        )

    assert token == "rotated-system-token"
    assert expires_at is not None
    assert calls[0]["grant_type"] == "fb_exchange_token"
    assert calls[0]["fb_exchange_token"] == "old-system-token"
    assert calls[0]["set_token_expires_in_60_days"] == "true"


async def test_refresh_uses_documented_60_days_when_meta_omits_expires_in() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"access_token": "rotated-token"})
        )
    ) as client:
        _token, expires_at = await refresh._refresh_source_token(
            client, "old-token", app_id="app-id", app_secret="app-secret"
        )
    expiry = datetime.fromisoformat(expires_at)
    assert timedelta(days=59) < expiry - datetime.now(UTC) <= timedelta(days=60)


async def test_page_token_is_reloaded_for_the_same_page() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["access_token"] == "rotated-user-token"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "different-page", "access_token": "wrong-token"},
                    {"id": "page-1", "access_token": "new-page-token"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await refresh._refresh_page_token(
            client, source_token="rotated-user-token", page_id="page-1"
        )
    assert result == "new-page-token"


async def test_refresh_integration_rotates_whatsapp_credential(monkeypatch) -> None:
    from app.platform.platform.services.secrets import IntegrationCredentialsService

    now = datetime.now(UTC)
    integration = Integration(provider="whatsapp", credentials={})
    session = SimpleNamespace(flush=lambda: None)

    async def flush():
        return None

    session.flush = flush
    credentials = {
        "access_token": "old-system-token",
        "_meta": {
            "refreshable": True,
            "expires_at": (now + timedelta(days=2)).isoformat(),
        },
    }

    async def decrypt(_session, _integration):
        return credentials.copy()

    monkeypatch.setattr(IntegrationCredentialsService, "decrypt", decrypt)
    from app.core.config import get_settings

    settings = get_settings()
    settings.meta_app_id = "app-id"
    settings.meta_app_secret = "app-secret"
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access_token": "new-system-token", "expires_in": 5_183_944}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        changed = await refresh.refresh_integration(session, integration, client)

    assert changed is True
    saved = decrypt_credentials_dict(integration.credentials)
    assert saved["access_token"] == "new-system-token"
    assert saved["_meta"]["expires_at"] is not None
