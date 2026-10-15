"""Telegram Bot API — connection spec.

The owner pastes a bot token from @BotFather. Verification calls getMe live;
webhook registration is SERVER-side (`setWebhook` with the server-held secret)
so the secret never reaches the browser.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.platform.channel_specs.base import (
    _TELEGRAM_SECRET,
    _TELEGRAM_TOKEN,
    TELEGRAM_BASE,
    ConnectionSpec,
    FieldSpec,
    VerifiedChannel,
    or_generate_public_key,
    required_text,
)


def _bot_token(credentials: dict[str, Any]) -> str:
    token = required_text(credentials, "bot_token")
    if not _TELEGRAM_TOKEN.fullmatch(token):
        raise ValidationError("The Telegram bot token format is invalid.")
    return token


class TelegramConnectionSpec(ConnectionSpec):
    name = "telegram"
    display_name = "تيليجرام"
    description = "ربط بوت تيليجرام عبر Bot API"
    credential_fields = [
        FieldSpec(
            key="bot_token",
            label="توكن البوت (من @BotFather)",
            secret=True,
            placeholder="123456789:AA...",
        ),
    ]
    config_fields = []  # bot_id + public_key are derived server-side
    identity_field = "bot_id"
    setup_notes = (
        "الويبهوك يُسجّل تلقائياً على الخادم عند الاتصال — لا تحتاج أي خطوة يدوية. "
        "المفتاح العام يُولّد تلقائياً لربط شاشة الشات."
    )

    async def verify(
        self,
        credentials: dict[str, Any],
        config: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> VerifiedChannel:
        token = _bot_token(credentials)
        owns_client = client is None
        http = client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
        )
        try:
            try:
                response = await http.get(f"{TELEGRAM_BASE}/bot{token}/getMe")
            except httpx.RequestError:
                # The URL embeds the bot token — never chain the exception.
                raise ExternalProviderError(
                    "Could not reach Telegram to verify the connection. Try again."
                ) from None
            if response.status_code == 429 or response.status_code >= 500:
                raise ExternalProviderError(
                    "Telegram is temporarily unavailable. Try again.", retryable=True
                )
            if response.is_error:
                raise ValidationError(
                    "The provider rejected these credentials or required permissions are missing."
                )
            try:
                payload = response.json()
            except ValueError:
                raise ExternalProviderError(
                    "Telegram returned an invalid verification response."
                ) from None
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValidationError(
                    "The provider rejected these credentials or required permissions are missing."
                )
            if payload.get("ok") is not True or not isinstance(payload.get("result"), dict):
                raise ValidationError("Telegram rejected this bot token.")
            result = payload["result"]
            identity = str(result.get("id") or "")
            if not identity.isdigit():
                raise ExternalProviderError("Telegram returned an invalid bot identity.")
            return VerifiedChannel(
                {"bot_id": identity, "public_key": or_generate_public_key(config)},
                str(result.get("username") or result.get("first_name") or "") or None,
            )
        finally:
            if owns_client:
                await http.aclose()

    async def setup_webhook(
        self,
        credentials: dict[str, Any],
        webhook_url: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        from urllib.parse import urlparse

        from app.core.config import get_settings

        token = _bot_token(credentials)
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

    def webhook_secret_configured(self) -> bool:
        from app.core.config import get_settings

        secret = get_settings().telegram_webhook_secret
        return isinstance(secret, str) and bool(_TELEGRAM_SECRET.fullmatch(secret))


telegram_connection_spec = TelegramConnectionSpec()
