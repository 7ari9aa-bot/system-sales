"""Telegram Bot API adapter.

Tenant resolution: the webhook URL carries ?tenant_key=<public_key> (Telegram
updates contain no stable bot identifier), matched against integrations config.
Outbound: sendMessage via the Bot API.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import (
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
    StatusUpdate,
)

API_BASE = "https://api.telegram.org"


class TelegramAdapter:
    name = "telegram"

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        return None  # no handshake

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        # Telegram supports a static secret token per webhook URL.
        secret = get_settings().telegram_webhook_secret
        if not secret:
            return True  # dev only; production sets the secret
        provided = headers.get("x-telegram-bot-api-secret-token", "")
        return provided == secret

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
        media = self._extract_media(update_message)
        messages.append(
            InboundMessage(
                channel=self.name,
                channel_message_id=str(update_message.get("message_id")),
                customer_ref=str(chat.get("id")),
                customer_name=sender.get("first_name") or chat.get("title"),
                body=update_message.get("text") or caption,
                media_url=media,
                raw=update_message,
            )
        )
        return messages

    def parse_status_updates(self, payload: dict) -> list[StatusUpdate]:
        return []  # Bot API has no delivery receipts

    def _extract_media(self, update_message: dict) -> str | None:
        for kind in ("photo", "document", "video", "audio"):
            if kind in update_message:
                return f"telegram:{kind}"  # file_id fetched via getFile at ingest
        return None

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
        if _client is not None:
            response = await _client.post(f"{API_BASE}/bot{token}/sendMessage", json=payload)
        else:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(f"{API_BASE}/bot{token}/sendMessage", json=payload)
        if response.status_code >= 400:
            raise ExternalProviderError(
                f"telegram send failed: {response.status_code} {response.text[:200]}"
            )
        data = response.json()
        if not data.get("ok"):
            raise ExternalProviderError(f"telegram send failed: {data}")
        return str(data["result"]["message_id"])


telegram_adapter = TelegramAdapter()
