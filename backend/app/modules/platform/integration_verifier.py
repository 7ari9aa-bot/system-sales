"""Server-side verification for customer-owned channel credentials.

The per-channel logic lives in `platform/channel_specs/` — ONE FILE PER CHANNEL.
This module is now a thin facade over that registry: the public API is
preserved exactly (router, meta_oauth and tests call these functions), so the
reorganization cost the codebase zero call-site churn.

Provider secrets never leave the API process. Requests use fixed provider
hosts, short timeouts and no redirects; response bodies and request URLs are
never copied into errors because Telegram embeds its bot token in the request
path.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.platform.channel_specs.base import VerifiedChannel
from app.modules.platform.channel_specs.registry import get_connection_spec


def telegram_webhook_secret_configured() -> bool:
    """Whether the server secret satisfies Telegram's webhook header contract."""
    spec = get_connection_spec("telegram")
    assert spec is not None  # registry is static
    return spec.webhook_secret_configured()


async def verify_channel_credentials(
    provider: str,
    credentials: dict[str, Any],
    config: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> VerifiedChannel:
    """Verify provider credentials and return only safe account identity data."""
    spec = get_connection_spec(provider)
    if spec is None:
        raise ValidationError("This channel provider is not supported.")
    try:
        return await spec.verify(credentials, config, client=client)
    except ValidationError:
        raise
    except ExternalProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 — a spec bug must not leak internals
        raise ExternalProviderError(
            f"{provider} verification failed unexpectedly. Try again."
        ) from exc


async def configure_telegram_webhook(
    credentials: dict[str, Any],
    webhook_url: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Register the verified bot webhook with the server-held Telegram secret.

    The secret must never be sent to the browser. Telegram copies it to the
    `X-Telegram-Bot-Api-Secret-Token` header on every delivery, which the
    webhook adapter validates before resolving a tenant.
    """
    spec = get_connection_spec("telegram")
    assert spec is not None
    parsed_url = urlparse(webhook_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise ExternalProviderError(
            "Telegram webhook setup requires a public HTTPS API URL.", retryable=False
        )
    await spec.setup_webhook(credentials, webhook_url, client=client)


def channel_field_allow_lists() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """(credential fields, config fields) per channel — derived from the specs.

    Exposed HERE so callers that already hold the verifier import (the connect
    router) never grow a second cross-module edge to reach the registry: the
    field lists used to be hand-copied in three places and drifted.
    """
    from app.modules.platform.channel_specs.registry import CONNECTION_SPECS

    credentials = {
        name: frozenset(field.key for field in spec.credential_fields)
        for name, spec in CONNECTION_SPECS.items()
    }
    config = {
        name: frozenset(field.key for field in spec.config_fields)
        for name, spec in CONNECTION_SPECS.items()
    }
    return credentials, config


def signed_webhook_providers() -> frozenset[str]:
    """Every connectable provider whose webhook ingress is signature-checked."""
    from app.modules.platform.channel_specs.registry import CONNECTION_SPECS

    return frozenset(CONNECTION_SPECS) - {"webchat"}
