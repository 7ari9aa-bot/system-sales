"""Provider credential checks stay server-side and never echo secrets."""

from __future__ import annotations

import httpx
import pytest

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.platform.integration_verifier import (
    configure_telegram_webhook,
    verify_channel_credentials,
)


@pytest.mark.parametrize(
    ("provider", "credentials", "config", "path", "payload", "identity", "name"),
    [
        (
            "whatsapp",
            {"access_token": "wa-secret"},
            {"phone_number_id": "123456789"},
            "/v26.0/123456789",
            {"id": "123456789", "verified_name": "Shop", "display_phone_number": "+1 555"},
            {"phone_number_id": "123456789"},
            "Shop",
        ),
        (
            "instagram",
            {"api_key": "ig-secret"},
            {"account_id": "234567890"},
            "/v26.0/234567890",
            {"id": "234567890", "username": "shop"},
            {"account_id": "234567890"},
            "shop",
        ),
        (
            "messenger",
            {"api_key": "page-secret"},
            {},
            "/v26.0/me",
            {"id": "345678901", "name": "Page"},
            {"account_id": "345678901"},
            "Page",
        ),
    ],
)
async def test_meta_channels_verify_fixed_graph_identity(
    provider, credentials, config, path, payload, identity, name
) -> None:  # noqa: ANN001
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graph.facebook.com"
        assert request.url.path == path
        assert request.headers["authorization"] == f"Bearer {next(iter(credentials.values()))}"
        assert "access_token" not in request.url.query.decode()
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await verify_channel_credentials(provider, credentials, config, client=client)

    assert result.identity_config == identity
    assert result.display_name == name


async def test_telegram_verification_uses_fixed_host_without_echoing_token() -> None:
    token = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.telegram.org"
        assert request.url.path == f"/bot{token}/getMe"
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={"ok": True, "result": {"id": 456789, "username": "sales_bot"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await verify_channel_credentials(
            "telegram", {"bot_token": token}, {}, client=client
        )

    assert result.identity_config["bot_id"] == "456789"
    assert len(result.identity_config["public_key"]) >= 32
    assert result.display_name == "sales_bot"


async def test_telegram_webhook_is_registered_with_server_secret(monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    token = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
    secret = "server_webhook_secret_123456"
    webhook_url = "https://api.example.test/api/v1/webhooks/telegram?tenant_key=public-key"

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(telegram_webhook_secret=secret),
    )

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.host == "api.telegram.org"
        assert request.url.path == f"/bot{token}/setWebhook"
        assert request.read().decode()
        import json

        body = json.loads(request.content)
        assert body == {
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["message", "edited_message"],
        }
        return httpx.Response(200, json={"ok": True, "result": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await configure_telegram_webhook({"bot_token": token}, webhook_url, client=client)


async def test_telegram_webhook_setup_failure_never_echoes_token_or_secret(monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    token = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
    secret = "server_webhook_secret_123456"
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(telegram_webhook_secret=secret),
    )

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": f"{token} {secret}"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ExternalProviderError) as caught:
            await configure_telegram_webhook(
                {"bot_token": token},
                "https://api.example.test/api/v1/webhooks/telegram?tenant_key=public-key",
                client=client,
            )

    assert token not in str(caught.value)
    assert secret not in str(caught.value)


async def test_rejected_credentials_return_a_scrubbed_error() -> None:
    token = "do-not-return-this-token"

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": token}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValidationError) as caught:
            await verify_channel_credentials("messenger", {"api_key": token}, {}, client=client)

    assert token not in str(caught.value)
    assert "Authorization" not in str(caught.value)


async def test_provider_identity_must_match_the_configured_account() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "999999", "username": "other"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValidationError, match="does not match"):
            await verify_channel_credentials(
                "instagram",
                {"api_key": "ig-secret"},
                {"account_id": "234567890"},
                client=client,
            )


async def test_provider_network_errors_are_retryable_and_scrubbed() -> None:
    token = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("failed to connect", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(ExternalProviderError) as caught:
            await verify_channel_credentials("telegram", {"bot_token": token}, {}, client=client)

    assert caught.value.retryable is True
    assert token not in str(caught.value)


async def test_invalid_ids_are_rejected_before_network_access() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: pytest.fail("invalid IDs must not trigger a request")
        )
    ) as client:
        with pytest.raises(ValidationError):
            await verify_channel_credentials(
                "whatsapp",
                {"access_token": "wa-secret"},
                {"phone_number_id": "https://attacker.invalid"},
                client=client,
            )


# ---------------------------------------------------------------------------
# Package 2.1 — fail-closed error contract + bounded transport.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_provider_throttling_and_outages_are_retryable_502s(status) -> None:  # noqa: ANN001
    """Fail-closed error contract: a provider that cannot answer (throttled or
    down) is an ExternalProviderError — a 502 with retryable=True on the wire —
    never a raw 500 and never a non-retryable verdict that would strand the
    operator on a transient outage."""

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ExternalProviderError) as caught:
            await verify_channel_credentials(
                "messenger", {"api_key": "page-secret"}, {}, client=client
            )

    assert caught.value.retryable is True


async def test_provider_malformed_payload_is_an_external_error_not_a_crash() -> None:
    """HTML error pages and non-object JSON (a proxy's array, a CDN interstitial)
    must fail closed as provider errors — parsing them as credentials data or
    crashing with a 500 would leak transport details into the response."""
    for body in (b"<html>gateway timeout</html>", b'["not", "an", "object"]'):

        def respond(_request: httpx.Request, body: bytes = body) -> httpx.Response:
            return httpx.Response(200, content=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(ExternalProviderError):
                await verify_channel_credentials(
                    "messenger", {"api_key": "page-secret"}, {}, client=client
                )


async def test_redirects_are_never_followed() -> None:
    """follow_redirects=False is the SSRF/tuning guard: a provider (or anything
    between us and it) answering 302 must not be chased — the verification
    fails closed instead of submitting the credential to the redirect target."""

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://attacker.example.test/catch"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ExternalProviderError):
            await verify_channel_credentials(
                "messenger", {"api_key": "page-secret"}, {}, client=client
            )


def test_the_verifier_client_is_timeout_bounded(monkeypatch) -> None:  # noqa: ANN001
    """The self-managed client (no caller-supplied one) must carry a bounded
    timeout — an unbounded provider call pins a request worker forever."""
    captured: dict = {}

    real_client = httpx.AsyncClient

    class _SpyClient(real_client):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            captured.update(kwargs)
            super().__init__(
                *args,
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(200, json={"id": "345678901", "name": "Page"})
                ),
                **kwargs,
            )

    monkeypatch.setattr("app.modules.platform.integration_verifier.httpx.AsyncClient", _SpyClient)

    import anyio

    async def _run() -> None:
        result = await verify_channel_credentials("messenger", {"api_key": "page-secret"}, {})
        assert result.identity_config == {"account_id": "345678901"}

    anyio.run(_run)

    assert captured["timeout"] == httpx.Timeout(8.0, connect=3.0)
    assert captured["follow_redirects"] is False
