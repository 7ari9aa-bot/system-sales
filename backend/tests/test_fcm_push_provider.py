"""Behavioural tests for the FCM push provider adapter.

The adapter mirrors ``ResendEmailProvider``: no real key lives in the class —
it reads ``settings.fcm_server_key`` at call time, and when FCM is not
configured the send is a no-op.  These tests use a fake HTTP client to
verify the request shape and error handling without touching the network.
"""

from __future__ import annotations

import json as _json
from typing import Any

import httpx
import pytest


class FakeFCMClient:
    """Records the request and returns a canned response.

    Mirrors the ``httpx.AsyncClient`` context-manager + post interface that
    ``FCMPushProvider.send`` uses.
    """

    def __init__(
        self,
        *,
        status_code: int = 200,
        response_body: dict[str, Any] | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.response_body = response_body or {"success": 1}
        self.raise_error = raise_error
        self.requests: list[dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, headers=None, json=None, timeout=None):  # noqa: A002, ARG002
        if self.raise_error is not None:
            raise self.raise_error
        self.requests.append({"url": url, "headers": headers, "json": json})
        return httpx.Response(
            status_code=self.status_code,
            content=_json.dumps(self.response_body).encode(),
            request=httpx.Request("POST", url),
        )


class TestFCMPushProvider:
    """FCM adapter: sends when configured, no-ops when not, raises on failure."""

    @pytest.mark.asyncio
    async def test_send_when_configured(self, monkeypatch) -> None:
        from app.modules.notifications.providers import FCMPushProvider

        monkeypatch.setenv("FCM_SERVER_KEY", "test-fcm-key-123")

        from app.core.config import get_settings

        get_settings.cache_clear()
        fake = FakeFCMClient(status_code=200)
        provider = FCMPushProvider(client_factory=lambda **kw: fake)

        await provider.send(token="device-token-abc", title="Hello", body="World")

        assert len(fake.requests) == 1
        req = fake.requests[0]
        assert req["url"] == "https://fcm.googleapis.com/fcm/send"
        assert req["headers"]["Authorization"] == "key=test-fcm-key-123"
        assert req["json"]["to"] == "device-token-abc"
        assert req["json"]["notification"]["title"] == "Hello"
        assert req["json"]["notification"]["body"] == "World"
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_noop_when_not_configured(self, monkeypatch) -> None:
        from app.modules.notifications.providers import FCMPushProvider

        monkeypatch.delenv("FCM_SERVER_KEY", raising=False)

        from app.core.config import get_settings

        get_settings.cache_clear()
        fake = FakeFCMClient()
        provider = FCMPushProvider(client_factory=lambda **kw: fake)

        # No key configured → no-op, no request made.
        await provider.send(token="device-token-abc", title="Hello", body="World")
        assert len(fake.requests) == 0
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self, monkeypatch) -> None:
        from app.modules.notifications.providers import FCMPushProvider

        monkeypatch.setenv("FCM_SERVER_KEY", "test-fcm-key-123")

        from app.core.config import get_settings

        get_settings.cache_clear()
        fake = FakeFCMClient(status_code=401, response_body={"error": "InvalidApiKey"})
        provider = FCMPushProvider(client_factory=lambda **kw: fake)

        with pytest.raises(RuntimeError, match="fcm rejected delivery"):
            await provider.send(token="device-token-abc", title="Hello", body="World")
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_raises_on_network_error(self, monkeypatch) -> None:
        from app.modules.notifications.providers import FCMPushProvider

        monkeypatch.setenv("FCM_SERVER_KEY", "test-fcm-key-123")

        from app.core.config import get_settings

        get_settings.cache_clear()
        fake = FakeFCMClient(raise_error=httpx.ConnectError("connection refused"))
        provider = FCMPushProvider(client_factory=lambda **kw: fake)

        with pytest.raises(RuntimeError, match="fcm network error"):
            await provider.send(token="device-token-abc", title="Hello", body="World")
        get_settings.cache_clear()
