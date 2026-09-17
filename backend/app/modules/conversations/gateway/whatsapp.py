"""WhatsApp Cloud API adapter.

Platform details owned here: signature verification, payload normalization,
media expiry (fetched to durable storage at ingest), 24-hour customer service
window, template sending, rate limits, retries (via worker runtime).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import (
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
    StatusUpdate,
)

GRAPH_BASE = "https://graph.facebook.com/v21.0"

_MEDIA_TYPES = {
    "image": "image",
    "audio": "audio",
    "video": "video",
    "document": "document",
    "sticker": "sticker",
}


class WhatsAppAdapter:
    name = "whatsapp"

    # ---------- webhook auth ----------

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        settings = get_settings()
        if (
            query_params.get("hub.mode") == "subscribe"
            and query_params.get("hub.verify_token") == settings.whatsapp_verify_token
        ):
            return query_params.get("hub.challenge", "")
        return None

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        secret = get_settings().whatsapp_app_secret
        if not secret:
            # No secret configured → cannot verify; reject (fail closed).
            return False
        signature = headers.get("x-hub-signature-256", "")
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature[7:], expected)

    # ---------- tenant resolution ----------

    def resolve_tenant_key(self, payload: dict) -> str | None:
        try:
            return payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
        except (KeyError, IndexError, TypeError):
            return None

    # ---------- normalization ----------

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        messages: list[InboundMessage] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = {c.get("wa_id"): c for c in value.get("contacts", [])}
                for msg in value.get("messages", []):
                    wa_id = msg.get("from")
                    contact = contacts.get(wa_id, {})
                    profile_name = (contact.get("profile") or {}).get("name")
                    body, media_url, media_type = self._extract_content(msg)
                    messages.append(
                        InboundMessage(
                            channel=self.name,
                            channel_message_id=msg.get("id"),
                            customer_ref=wa_id or "",
                            customer_name=profile_name,
                            body=body,
                            media_url=media_url,
                            media_type=media_type,
                            raw=msg,
                        )
                    )
        return messages

    def parse_status_updates(self, payload: dict) -> list[StatusUpdate]:
        updates: list[StatusUpdate] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for status in value.get("statuses", []):
                    errors = status.get("errors") or []
                    updates.append(
                        StatusUpdate(
                            channel_message_id=status.get("id", ""),
                            status=status.get("status", ""),
                            error=errors[0].get("message") if errors else None,
                            timestamp=status.get("timestamp"),
                        )
                    )
        return updates

    def _extract_content(self, msg: dict) -> tuple[str | None, str | None, str | None]:
        msg_type = msg.get("type")
        if msg_type == "text":
            return msg.get("text", {}).get("body"), None, None
        if msg_type in _MEDIA_TYPES:
            media = msg.get(msg_type, {})
            return msg.get("caption"), media.get("link") or media.get("id"), msg_type
        if msg_type == "location":
            loc = msg.get("location", {})
            return f"📍 {loc.get('name') or ''} {loc.get('address') or ''}".strip(), None, None
        if msg_type == "contacts":
            return "[contacts]", None, None
        if msg_type == "button":
            return msg.get("button", {}).get("text"), None, None
        if msg_type == "interactive":
            interactive = msg.get("interactive", {})
            reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
            return reply.get("title"), None, None
        return json.dumps(msg)[:500] if msg else None, None, None

    # ---------- outbound ----------

    async def send(
        self,
        credentials: ProviderCredentials,
        message: OutboundMessage,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """_client is an injection point for tests (MockTransport)."""
        phone_number_id = credentials.get("phone_number_id")
        token = credentials.get("access_token")
        if not phone_number_id or not token:
            raise ExternalProviderError("whatsapp integration missing credentials")

        body_payload = self._build_send_payload(message)
        if _client is not None:
            response = await _client.post(
                f"{GRAPH_BASE}/{phone_number_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json=body_payload,
            )
        else:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{GRAPH_BASE}/{phone_number_id}/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    json=body_payload,
                )
        if response.status_code >= 400:
            raise ExternalProviderError(
                f"whatsapp send failed: {response.status_code} {response.text[:200]}"
            )
        data: dict[str, Any] = response.json()
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalProviderError("whatsapp send: no message id in response") from exc

    def _build_send_payload(self, message: OutboundMessage) -> dict:
        base = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": message.customer_ref,
        }
        if message.template_name:
            lang = message.template_vars.get("language_code", "ar")
            components = []
            params = message.template_vars.get("body_params") or []
            if params:
                components.append(
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": str(p)} for p in params],
                    }
                )
            return {
                **base,
                "type": "template",
                "template": {
                    "name": message.template_name,
                    "language": {"code": lang},
                    "components": components,
                },
            }
        if message.media_url:
            media_type = message.meta.get("media_type", "image")
            if media_type == "document":
                media_block = {
                    "link": message.media_url,
                    "filename": message.meta.get("filename", "file"),
                }
            else:
                media_block = {"link": message.media_url}
            return {
                **base,
                "type": media_type,
                media_type: media_block,
                "caption": message.body or "",
            }
        return {**base, "type": "text", "text": {"preview_url": True, "body": message.body or ""}}


whatsapp_adapter = WhatsAppAdapter()
