"""Telegram Bot API adapter.

Tenant resolution: the webhook URL carries ?tenant_key=<public_key> (Telegram
updates contain no stable bot identifier), matched against integrations config.
Outbound: sendMessage via the Bot API.
"""

from __future__ import annotations

import httpx

from app.core.circuit_breaker import PROVIDER_TELEGRAM, get_breaker
from app.core.config import get_settings
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import (
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
    StatusUpdate,
    parse_provider_body,
)

API_BASE = "https://api.telegram.org"

# §155: Telegram update kind → canonical Message.content_type. Checked in this
# order — an `animation` update also carries a `document` field, so animation
# must win over document; a `video_note` is a round video message.
_MEDIA_CONTENT: dict[str, str] = {
    "photo": "image",
    "voice": "voice",
    "video": "video",
    "video_note": "video",
    "animation": "video",
    "audio": "file",
    "document": "file",
}


class TelegramAdapter:
    name = "telegram"

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        return None  # no handshake

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        # §176 fail-closed: an unconfigured secret rejects ALL traffic rather
        # than leaving a pre-auth injection path into any tenant.
        import hmac as _hmac

        secret = get_settings().telegram_webhook_secret
        if not secret:
            return False
        provided = headers.get("x-telegram-bot-api-secret-token", "")
        return _hmac.compare_digest(provided, secret)

    def resolve_tenant_key(self, payload: dict) -> str | None:
        query = payload.get("_query") or {}
        return query.get("tenant_key") or query.get("public_key")

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        messages: list[InboundMessage] = []
        update_message = payload.get("message") or payload.get("edited_message") or {}
        chat = update_message.get("chat", {})
        if not chat:
            return []
        sender = update_message.get("from", {})
        caption = update_message.get("caption")
        media, content_type = self._extract_media(update_message)
        reply_to = (update_message.get("reply_to_message") or {}).get("message_id")
        messages.append(
            InboundMessage(
                channel=self.name,
                channel_message_id=str(update_message.get("message_id")),
                customer_ref=str(chat.get("id")),
                customer_name=sender.get("first_name") or chat.get("title"),
                body=update_message.get("text") or caption,
                media_url=media,
                content_type=content_type,
                reply_to_message_id=str(reply_to) if reply_to is not None else None,
                raw=update_message,
            )
        )
        return messages

    def parse_status_updates(self, payload: dict) -> list[StatusUpdate]:
        return []  # Bot API has no delivery receipts

    def _extract_media(self, update_message: dict) -> tuple[str | None, str]:
        """→ (media marker, canonical content type) for the first media kind.

        The marker ("telegram:<kind>") is fetched to durable storage via
        getFile at ingest; the content type is the §155 canonical value the
        model column stores.
        """
        for kind, content_type in _MEDIA_CONTENT.items():
            if kind in update_message:
                return f"telegram:{kind}", content_type
        return None, "text"

    async def send(
        self,
        credentials: ProviderCredentials,
        message: OutboundMessage,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """_client is an injection point for tests (MockTransport)."""
        token = credentials.get("bot_token")
        if not token:
            raise ExternalProviderError("telegram integration missing bot_token")
        payload: dict = {
            "chat_id": message.customer_ref,
            "text": message.body or "[media]",
        }
        if message.meta.get("reply_markup"):
            payload["reply_markup"] = message.meta["reply_markup"]
        url = f"{API_BASE}/bot{token}/sendMessage"

        async def _post() -> str:
            """Post and return the provider message id — entirely inside the breaker."""
            if _client is not None:
                response = await _client.post(url, json=payload)
            else:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(url, json=payload)

            # A provider that REJECTS the send is a provider FAILURE, so it must be
            # raised INSIDE the breaker. Wrapping only the request meant a provider
            # answering 500 to every call was recorded as a SUCCESS and the breaker
            # never opened — the single case it exists for.
            if response.status_code >= 400:
                raise ExternalProviderError(
                    f"telegram send failed: {response.status_code} {response.text[:200]}"
                )
            # Bot API answers 200 with {"ok": false, "description": ...} for a
            # rejected send, and an intermediary can answer 200 with HTML. Both
            # must be raised here too, or they count as breaker SUCCESSES.
            data = parse_provider_body(response, "telegram send")
            if not data.get("ok"):
                raise ExternalProviderError(f"telegram send failed: {str(data)[:200]}")
            try:
                message_id = data["result"]["message_id"]
            except (KeyError, TypeError) as exc:
                raise ExternalProviderError(
                    f"telegram send: ok but no result.message_id: {str(data)[:200]}"
                ) from exc
            if not message_id:
                raise ExternalProviderError("telegram send: empty message id in response")
            return str(message_id)

        # §47: the outbound call goes through the process-wide `provider.telegram`
        # breaker, so a dead provider is backed off instead of hammered. An OPEN
        # breaker raises CircuitOpenError; deciding whether that retries, defers or
        # fails is the caller's job, not the adapter's.
        return await get_breaker(PROVIDER_TELEGRAM).call(_post)


telegram_adapter = TelegramAdapter()
