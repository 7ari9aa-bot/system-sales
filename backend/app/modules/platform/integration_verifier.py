"""Server-side verification for customer-owned channel credentials.

Provider secrets never leave the API process. Requests use fixed provider hosts,
short timeouts and no redirects; response bodies and request URLs are never
copied into errors because Telegram embeds its bot token in the request path.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.errors import ExternalProviderError, ValidationError

# Keep Meta verification calls on a currently supported, explicitly versioned
# Graph API release. v21.0 approaches retirement in January 2027.
GRAPH_BASE = "https://graph.facebook.com/v26.0"
TELEGRAM_BASE = "https://api.telegram.org"
_NUMERIC_ID = re.compile(r"^[0-9]{1,32}$")
_TELEGRAM_TOKEN = re.compile(r"^[0-9]{5,}:[A-Za-z0-9_-]{20,}$")
_TELEGRAM_SECRET = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
_PUBLIC_KEY = re.compile(r"^[A-Za-z0-9_-]{24,128}$")


@dataclass(frozen=True, slots=True)
class VerifiedChannel:
    identity_config: dict[str, str]
    display_name: str | None = None


def telegram_webhook_secret_configured() -> bool:
    """Whether the server secret satisfies Telegram's webhook header contract."""
    from app.core.config import get_settings

    secret = get_settings().telegram_webhook_secret
    return isinstance(secret, str) and bool(_TELEGRAM_SECRET.fullmatch(secret))


def _required_text(values: dict[str, Any], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{key} is required")
    value = value.strip()
    if len(value) > 4096:
        raise ValidationError(f"{key} is invalid")
    return value


def _numeric_id(values: dict[str, Any], key: str) -> str:
    value = _required_text(values, key)
    if not _NUMERIC_ID.fullmatch(value):
        raise ValidationError(f"{key} must be a valid provider ID")
    return value


async def _json_response(
    client: httpx.AsyncClient,
    *,
    provider: str,
    url: str,
    token: str | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else None
    try:
        response = await client.get(
            url,
            params=params,
            headers=headers,
        )
    except httpx.RequestError:
        # Do not chain request exceptions: their repr may include Telegram's
        # token-bearing URL, which must not reach logs or API error envelopes.
        raise ExternalProviderError(
            f"Could not reach {provider} to verify the connection. Try again."
        ) from None

    if response.status_code == 429 or response.status_code >= 500:
        raise ExternalProviderError(
            f"{provider} is temporarily unavailable. Try again.", retryable=True
        )
    if response.is_error:
        raise ValidationError(
            "The provider rejected these credentials or required permissions are missing."
        )

    try:
        payload = response.json()
    except ValueError:
        raise ExternalProviderError(
            f"{provider} returned an invalid verification response."
        ) from None
    if not isinstance(payload, dict):
        raise ExternalProviderError(
            f"{provider} returned an invalid verification response."
        )
    if payload.get("error"):
        raise ValidationError(
            "The provider rejected these credentials or required permissions are missing."
        )
    return payload


async def verify_channel_credentials(
    provider: str,
    credentials: dict[str, Any],
    config: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> VerifiedChannel:
    """Verify provider credentials and return only safe account identity data."""
    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
    )
    try:
        if provider == "whatsapp":
            phone_number_id = _numeric_id(config, "phone_number_id")
            token = _required_text(credentials, "access_token")
            data = await _json_response(
                http,
                provider="WhatsApp",
                url=f"{GRAPH_BASE}/{phone_number_id}",
                token=token,
                params={"fields": "id,display_phone_number,verified_name"},
            )
            identity = str(data.get("id") or "")
            if identity != phone_number_id:
                raise ValidationError("The WhatsApp phone number ID does not match the token.")
            return VerifiedChannel(
                {"phone_number_id": identity},
                str(data.get("verified_name") or data.get("display_phone_number") or "") or None,
            )

        if provider == "instagram":
            account_id = _numeric_id(config, "account_id")
            token = _required_text(credentials, "api_key")
            data = await _json_response(
                http,
                provider="Instagram",
                url=f"{GRAPH_BASE}/{account_id}",
                token=token,
                params={"fields": "id,username"},
            )
            identity = str(data.get("id") or "")
            if identity != account_id:
                raise ValidationError("The Instagram account ID does not match the token.")
            display_name = str(data.get("username") or "") or None
            return VerifiedChannel({"account_id": identity}, display_name)

        if provider == "messenger":
            token = _required_text(credentials, "api_key")
            data = await _json_response(
                http,
                provider="Messenger",
                url=f"{GRAPH_BASE}/me",
                token=token,
                params={"fields": "id,name"},
            )
            identity = str(data.get("id") or "")
            if not _NUMERIC_ID.fullmatch(identity):
                raise ValidationError(
                    "This token does not identify a Messenger page or lacks page permissions."
                )
            return VerifiedChannel({"account_id": identity}, str(data.get("name") or "") or None)

        if provider == "telegram":
            token = _required_text(credentials, "bot_token")
            if not _TELEGRAM_TOKEN.fullmatch(token):
                raise ValidationError("The Telegram bot token format is invalid.")
            data = await _json_response(
                http,
                provider="Telegram",
                url=f"{TELEGRAM_BASE}/bot{token}/getMe",
            )
            if data.get("ok") is not True or not isinstance(data.get("result"), dict):
                raise ValidationError("Telegram rejected this bot token.")
            result = data["result"]
            identity = str(result.get("id") or "")
            if not _NUMERIC_ID.fullmatch(identity):
                raise ExternalProviderError("Telegram returned an invalid bot identity.")
            public_key = config.get("public_key")
            if not isinstance(public_key, str) or not _PUBLIC_KEY.fullmatch(public_key):
                public_key = secrets.token_urlsafe(32)
            return VerifiedChannel(
                {"bot_id": identity, "public_key": public_key},
                str(result.get("username") or result.get("first_name") or "") or None,
            )

        if provider == "webchat":
            public_key = config.get("public_key")
            if not isinstance(public_key, str) or not _PUBLIC_KEY.fullmatch(public_key):
                public_key = secrets.token_urlsafe(32)
            return VerifiedChannel({"public_key": public_key}, "Website chat")

        raise ValidationError("This channel provider is not supported.")
    finally:
        if owns_client:
            await http.aclose()

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
    from app.core.config import get_settings

    token = _required_text(credentials, "bot_token")
    if not _TELEGRAM_TOKEN.fullmatch(token):
        raise ValidationError("The Telegram bot token format is invalid.")

    parsed_url = urlparse(webhook_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise ExternalProviderError(
            "Telegram webhook setup requires a public HTTPS API URL.", retryable=False
        )

    secret = get_settings().telegram_webhook_secret
    if not isinstance(secret, str) or not _TELEGRAM_SECRET.fullmatch(secret):
        raise ExternalProviderError(
            "Telegram webhook security is not configured on this server.", retryable=False
        )

    owns_client = client is None
    http = client or httpx.AsyncClient(
        timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
    )
    try:
        try:
            response = await http.post(
                f"{TELEGRAM_BASE}/bot{token}/setWebhook",
                json={
                    "url": webhook_url,
                    "secret_token": secret,
                    "allowed_updates": ["message", "edited_message"],
                },
            )
        except httpx.RequestError:
            # The request URL includes the bot token. Never chain or log it.
            raise ExternalProviderError(
                "Could not configure the Telegram webhook. Try again."
            ) from None

        if response.status_code == 429 or response.status_code >= 500:
            raise ExternalProviderError(
                "Telegram is temporarily unavailable while configuring the webhook.",
                retryable=True,
            )
        if response.is_error:
            raise ExternalProviderError(
                "Telegram rejected webhook setup. Check the public HTTPS API URL and retry.",
                retryable=False,
            )
        try:
            payload = response.json()
        except ValueError:
            raise ExternalProviderError(
                "Telegram returned an invalid webhook setup response.", retryable=True
            ) from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ExternalProviderError(
                "Telegram could not activate this webhook. "
                "Check the public HTTPS API URL and retry.",
                retryable=False,
            )
    finally:
        if owns_client:
            await http.aclose()
