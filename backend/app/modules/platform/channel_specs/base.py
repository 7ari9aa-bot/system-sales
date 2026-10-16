"""Per-channel CONNECTION specs — one file per channel, the organized way.

This package owns the CONNECT side of a channel: which credentials the store
owner pastes, how the server proves them against the provider (live call),
which config key identifies the channel account, and how the webhook gets
wired. The MESSAGE runtime (parsing/sending) stays in the sibling adapter
files — a connection spec never sends customer messages.

Contract (implement `ChannelConnectionSpec`):
    name              registry key, equals the integration `provider` value
    display_name      Arabic name for the settings UI
    description       one line the settings screen can show
    credential_fields what the owner pastes (secrets)
    config_fields     non-secret identifiers (ids, public keys)
    identity_field    the config key resolve_channel_tenant matches on
    verify()          live provider call → VerifiedChannel (identity + name)
    setup_webhook()   optional server-side webhook registration (Telegram)

Adding a channel = one new file here + one entry in registry.py + (for Meta
family channels) a thin adapter subclass. Nothing else changes: the webhook
dispatcher is generic (/webhooks/{channel}) and `resolve_channel_tenant` is
identity-generic (matches account_id/bot_id/phone_number_id/public_key).
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.errors import ExternalProviderError, ValidationError

GRAPH_BASE = "https://graph.facebook.com/v26.0"
TELEGRAM_BASE = "https://api.telegram.org"

_NUMERIC_ID = re.compile(r"^[0-9]{1,32}$")
_TELEGRAM_TOKEN = re.compile(r"^[0-9]{5,}:[A-Za-z0-9_-]{20,}$")
_TELEGRAM_SECRET = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_PUBLIC_KEY = re.compile(r"^[A-Za-z0-9_-]{24,128}$")


@dataclass(frozen=True, slots=True)
class VerifiedChannel:
    """What a successful verification yields — safe identity data only.

    `identity_config` lands in Integration.config (non-secret), and
    `display_name` is shown in the settings UI. Provider secrets NEVER land
    here: they stay in the encrypted credentials column.
    """

    identity_config: dict[str, str]
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One form field on the settings screen."""

    key: str
    label: str  # Arabic label for the UI
    secret: bool = False  # True → render as a password input
    placeholder: str = ""


def required_text(values: dict[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{key} is required")
    value = value.strip()
    if len(value) > 4096:
        raise ValidationError(f"{key} is invalid")
    return value


def numeric_id(values: dict[str, Any], key: str) -> str:
    value = required_text(values, key)
    if not _NUMERIC_ID.fullmatch(value):
        raise ValidationError(f"{key} must be a valid provider ID")
    return value


def or_generate_public_key(values: dict[str, Any]) -> str:
    """The webchat/telegram public key: keep the owner's or mint a fresh one."""
    public_key = values.get("public_key")
    if isinstance(public_key, str) and _PUBLIC_KEY.fullmatch(public_key):
        return public_key
    return secrets.token_urlsafe(32)


async def graph_get(
    client: httpx.AsyncClient,
    *,
    provider_label: str,
    url: str,
    token: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One guarded Graph API GET — the shared Meta-family verification call.

    Error messages are IDENTICAL across the Meta channels on purpose: the
    settings screen shows one honest line and the provider's raw body (which
    can embed tokens or ids) never reaches the API envelope.
    """
    try:
        response = await client.get(
            url, params=params, headers={"Authorization": f"Bearer {token}"}
        )
    except httpx.RequestError:
        # Never chain: the request URL may embed a provider token (Telegram).
        raise ExternalProviderError(
            f"Could not reach {provider_label} to verify the connection. Try again."
        ) from None
    if response.status_code == 429 or response.status_code >= 500:
        raise ExternalProviderError(
            f"{provider_label} is temporarily unavailable. Try again.", retryable=True
        )
    if response.is_error:
        raise ValidationError(
            "The provider rejected these credentials or required permissions are missing."
        )
    try:
        payload = response.json()
    except ValueError:
        # A malformed body (HTML error page, empty 302, CDN garbage) is a
        # PROVIDER failure, not a credential refusal — the original contract,
        # pinned by test_integration_verifier.py.
        raise ExternalProviderError(
            f"{provider_label} returned an invalid verification response."
        ) from None
    if not isinstance(payload, dict):
        raise ExternalProviderError(
            f"{provider_label} returned an invalid verification response."
        )
    if payload.get("error"):
        raise ValidationError(
            "The provider rejected these credentials or required permissions are missing."
        )
    return payload


class ChannelConnectionSpec(Protocol):
    """One channel's connect/verify contract — the whole point of this package."""

    name: str
    display_name: str
    description: str
    credential_fields: list[FieldSpec]
    config_fields: list[FieldSpec]
    identity_field: str  # the config key resolve_channel_tenant matches on

    async def verify(
        self,
        credentials: dict[str, Any],
        config: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> VerifiedChannel: ...

    async def setup_webhook(
        self,
        credentials: dict[str, Any],
        webhook_url: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Server-side webhook registration, when the provider supports it.

        Default: nothing to do — Meta-family channels are subscribed from the
        developer console, and the docs string tells the owner exactly where.
        """
        return None

    def webhook_secret_configured(self) -> bool:
        """Whether the SERVER half of the webhook handshake is present."""
        return True


class ConnectionSpec:
    """Concrete base — subclasses override only what differs from the default.

    Deliberately a PLAIN class, not a dataclass: a dataclass __init__ would
    assign every field default (name="") into the instance and shadow the
    subclass's class attributes — the registry keyed by spec.name would then
    be a single empty string.
    """

    name: str = ""
    display_name: str = ""
    description: str = ""
    credential_fields: tuple[FieldSpec, ...] = ()
    config_fields: tuple[FieldSpec, ...] = ()
    identity_field: str = ""
    setup_notes: str = ""  # shown under the form: where the webhook URL goes

    async def verify(
        self,
        credentials: dict[str, Any],
        config: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> VerifiedChannel:  # pragma: no cover - abstract
        raise NotImplementedError

    async def setup_webhook(
        self,
        credentials: dict[str, Any],
        webhook_url: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        return None

    def webhook_secret_configured(self) -> bool:
        return True
