"""WhatsApp Cloud API adapter.

Platform details owned here: signature verification, payload normalization,
media expiry (fetched to durable storage at ingest), 24-hour customer service
window, template sending, rate limits, retries (via worker runtime).
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx

from app.core.circuit_breaker import PROVIDER_WHATSAPP, get_breaker
from app.core.config import get_settings
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import (
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
    StatusUpdate,
    parse_provider_body,
)

GRAPH_BASE = "https://graph.facebook.com/v21.0"

# §155: provider media type → canonical Message.content_type. The model
# supports text | image | voice | video | file | location | contact | buttons
# | list | reaction | unsupported — every surface reads THAT column, so the
# adapter (the only component that knows WhatsApp's vocabulary) must set it.
# WhatsApp has no distinct "voice note" type: voice notes arrive as `audio`.
# A sticker is a WebP image; media_type keeps the provider nuance.
_CANONICAL_MEDIA_CONTENT: dict[str, str] = {
    "image": "image",
    "audio": "voice",
    "video": "video",
    "document": "file",
    "sticker": "image",
}


class WhatsAppAdapter:
    name = "whatsapp"

    # ---------- webhook auth ----------

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        expected = get_settings().whatsapp_verify_token
        if not expected:
            # Not configured -> cannot verify -> reject (fail closed), exactly
            # like check_signature below and the Telegram adapter. Without this
            # an empty `hub.verify_token` equalled the empty default.
            return None
        provided = query_params.get("hub.verify_token") or ""
        # Constant-time compare on BYTES: compare_digest raises TypeError on
        # non-ASCII str, which would turn a hostile query string into a 500.
        if query_params.get("hub.mode") == "subscribe" and hmac.compare_digest(
            provided.encode(), expected.encode()
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
                    body, media_url, media_type, content_type = self._extract_content(msg)
                    messages.append(
                        InboundMessage(
                            channel=self.name,
                            channel_message_id=msg.get("id"),
                            customer_ref=wa_id or "",
                            customer_name=profile_name,
                            body=body,
                            media_url=media_url,
                            media_type=media_type,
                            content_type=content_type,
                            reply_to_message_id=self._reply_context(msg),
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

    def _extract_content(
        self, msg: dict
    ) -> tuple[str | None, str | None, str | None, str]:
        """Normalize one provider message.

        Returns (body, media_url, media_type, canonical content_type). The
        content type is §155's whole point: a voice note is `voice`, a document
        is `file`, a button tap is `buttons` — never degraded to plain text.
        """
        msg_type = msg.get("type")
        if msg_type == "text":
            return msg.get("text", {}).get("body"), None, None, "text"
        if msg_type in _CANONICAL_MEDIA_CONTENT:
            media = msg.get(msg_type, {})
            return (
                msg.get("caption"),
                media.get("link") or media.get("id"),
                msg_type,
                _CANONICAL_MEDIA_CONTENT[msg_type],
            )
        if msg_type == "location":
            loc = msg.get("location", {})
            return (
                f"📍 {loc.get('name') or ''} {loc.get('address') or ''}".strip(),
                None,
                None,
                "location",
            )
        if msg_type == "contacts":
            return self._contact_body(msg.get("contacts")), None, None, "contact"
        if msg_type == "button":
            # A tap on a template quick-reply button.
            return msg.get("button", {}).get("text"), None, None, "buttons"
        if msg_type == "interactive":
            interactive = msg.get("interactive", {})
            button_reply = interactive.get("button_reply")
            if button_reply is not None:
                return button_reply.get("title"), None, None, "buttons"
            list_reply = interactive.get("list_reply")
            if list_reply is not None:
                return list_reply.get("title"), None, None, "list"
            return None, None, None, "unsupported"
        if msg_type == "reaction":
            return msg.get("reaction", {}).get("emoji"), None, None, "reaction"
        # A type this adapter does not know (order, system, referral, ...): the
        # raw JSON is kept as the body for forensics, and the canonical type is
        # honest about it instead of claiming "text".
        return (json.dumps(msg)[:500] if msg else None, None, None, "unsupported")

    @staticmethod
    def _contact_body(contacts: list | None) -> str | None:
        """First shared contact as a short human-readable body (§155)."""
        first = contacts[0] if contacts else None
        if not isinstance(first, dict):
            return "[contacts]"
        name = (first.get("name") or {}).get("formatted_name")
        phones = first.get("phones") or []
        phone = (phones[0] or {}).get("phone") if phones else None
        return " ".join(part for part in (name, phone) if part) or "[contacts]"

    @staticmethod
    def _reply_context(msg: dict) -> str | None:
        """§155 threading: the provider id this message replies to.

        Every reply-shaped payload carries `context.id` (a quoted message,
        a button tap quoting the template, a reaction quoting its target).
        """
        context = msg.get("context") or {}
        return context.get("id") or (msg.get("reaction") or {}).get("message_id")

    # ---------- outbound ----------

    async def send(
        self,
        credentials: ProviderCredentials,
        message: OutboundMessage,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """_client is an injection point for tests (MockTransport).

        n8n mode: when credentials carry outbound_webhook_url, delivery is
        proxied through the n8n outbound workflow — WhatsApp tokens then live
        in n8n env only, never in our database.
        """
        n8n_url = credentials.get("outbound_webhook_url")
        if n8n_url:
            return await self._send_via_n8n(n8n_url, credentials, message, _client)

        phone_number_id = credentials.get("phone_number_id")
        token = credentials.get("access_token")
        if not phone_number_id or not token:
            raise ExternalProviderError("whatsapp integration missing credentials")

        body_payload = self._build_send_payload(message)

        async def _post() -> str:
            """Post and return the provider message id — entirely inside the breaker."""
            url = f"{GRAPH_BASE}/{phone_number_id}/messages"
            headers = {"Authorization": f"Bearer {token}"}
            if _client is not None:
                response = await _client.post(url, headers=headers, json=body_payload)
            else:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(url, headers=headers, json=body_payload)

            # A provider that REJECTS the send is a provider FAILURE, so it must be
            # raised INSIDE the breaker. Wrapping only the request meant a provider
            # answering 500 to every call was recorded as a SUCCESS and the breaker
            # never opened — the single case it exists for.
            if response.status_code >= 400:
                raise ExternalProviderError(
                    f"whatsapp send failed: {response.status_code} {response.text[:200]}"
                )
            # A 2xx is not proof of acceptance either: Graph answers 200 with an
            # `error` object, and an intermediary can answer 200 with HTML. Both
            # must be raised here too, or they count as breaker SUCCESSES.
            data = parse_provider_body(response, "whatsapp send")
            try:
                message_id = data["messages"][0]["id"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ExternalProviderError(
                    f"whatsapp send: no message id in response: {str(data)[:200]}"
                ) from exc
            if not message_id:
                raise ExternalProviderError("whatsapp send: empty message id in response")
            return str(message_id)

        # §47: the outbound call goes through the process-wide `provider.whatsapp`
        # breaker, so a dead provider is backed off instead of hammered. An OPEN
        # breaker raises CircuitOpenError; deciding whether that retries, defers or
        # fails is the caller's job, not the adapter's.
        return await get_breaker(PROVIDER_WHATSAPP).call(_post)

    async def _send_via_n8n(
        self,
        n8n_url: str,
        credentials: ProviderCredentials,
        message: OutboundMessage,
        _client: httpx.AsyncClient | None,
    ) -> str:
        """Proxy delivery through the n8n outbound workflow."""
        phone_number_id = credentials.get("phone_number_id")
        if not phone_number_id:
            raise ExternalProviderError("whatsapp n8n mode missing phone_number_id")
        body = {
            "phone_number_id": phone_number_id,
            "to": message.customer_ref,
            "payload": self._build_send_payload(message),
        }
        headers = {"Authorization": f"Bearer {credentials.get('n8n_service_token', '')}"}

        async def _post() -> str:
            if _client is not None:
                response = await _client.post(n8n_url, json=body, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(n8n_url, json=body, headers=headers)
            # Raised inside the breaker, for the same reason as the direct path.
            if response.status_code >= 400:
                raise ExternalProviderError(
                    f"whatsapp n8n send failed: {response.status_code} {response.text[:200]}"
                )
            data = parse_provider_body(response, "whatsapp n8n send")
            # n8n lastNode returns the Graph response shape; unwrap either form.
            try:
                if "messages" in data:
                    message_id = data["messages"][0]["id"]
                else:
                    message_id = data["message_id"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ExternalProviderError(
                    f"whatsapp n8n send: no message id: {str(data)[:200]}"
                ) from exc
            if not message_id:
                raise ExternalProviderError("whatsapp n8n send: empty message id")
            return str(message_id)

        # Same provider as the direct Graph path, so it spends the SAME breaker.
        return await get_breaker(PROVIDER_WHATSAPP).call(_post)

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
