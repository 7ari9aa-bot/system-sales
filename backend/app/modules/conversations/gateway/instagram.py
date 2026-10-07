"""Spec §26 / §175 Phase 3 — Instagram channel adapter.

Instagram messaging uses the Meta Graph API — the same pattern as the
WhatsApp adapter but with Instagram-specific endpoints and payload shapes.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.core.circuit_breaker import PROVIDER_INSTAGRAM, get_breaker
from app.core.config import get_settings
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import (
    ChannelAdapter,
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
    StatusUpdate,
    parse_provider_body,
)

logger = logging.getLogger(__name__)


class InstagramAdapter(ChannelAdapter):
    """Instagram messaging adapter via Meta Graph API.

    Inbound: webhook → verify X-Hub-Signature-256 → parse entry[0].messaging[0].
    Outbound: POST to Graph API /messages endpoint.
    """

    name = "instagram"  # ChannelAdapter registry key
    channel = "instagram"

    def __init__(self, *, api_version: str = "v21.0"):
        # All secrets live in settings, read per call — a constructor-injected
        # secret can only go stale (the removed per-instance `verify_webhook`
        # verified nothing for exactly that reason).
        self._base = f"https://graph.facebook.com/{api_version}"

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        """Meta webhook subscription handshake (GET hub.challenge)."""
        settings = get_settings()
        if not settings.instagram_verify_token:
            # Not configured -> cannot verify -> reject (fail closed). Same
            # hole the WhatsApp adapter closed: an empty `hub.verify_token`
            # compared equal to the empty default and answered the caller's
            # own challenge (see test_whatsapp_verify_fail_closed.py).
            return None
        if (
            query_params.get("hub.mode") == "subscribe"
            and query_params.get("hub.verify_token") == settings.instagram_verify_token
        ):
            return query_params.get("hub.challenge", "")
        return None

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        """X-Hub-Signature-256 (HMAC-SHA256) — fail closed without a secret."""
        secret = get_settings().instagram_app_secret
        if not secret:
            return False
        signature = headers.get("x-hub-signature-256", "")
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        # Compared on BYTES: a str compare_digest raises TypeError on non-ASCII
        # input, which would turn a hostile header into a 500.
        return hmac.compare_digest(signature[7:].encode(), expected.encode())

    def resolve_tenant_key(self, payload: dict) -> str | None:
        """Meta routes by the page / IG account id in entry[0].id."""
        try:
            return str(payload["entry"][0]["id"])
        except (KeyError, IndexError, TypeError):
            return None

    def parse_status_updates(self, payload: dict) -> list[StatusUpdate]:
        # Meta delivery/read receipts arrive as messaging[0].delivery|read —
        # inbound-only for now; the generic status path handles the rest.
        return []

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        """Parse a Meta webhook payload into 0..1 canonical InboundMessages.

        Instagram webhooks: entry[0].messaging[0].message.text, sender.id, etc.
        Always a list — the dispatcher and the WebhookWorker iterate it, so the
        ``None`` this used to return on an empty envelope crashed the hot path
        instead of yielding zero messages.
        """
        entries = payload.get("entry", [])
        if not entries:
            return []

        messaging = entries[0].get("messaging", [])
        if not messaging:
            return []

        event = messaging[0]
        sender = event.get("sender", {})
        recipient = event.get("recipient", {})
        message = event.get("message", {})

        if not message:
            return []

        # Handle different message types
        text = message.get("text")
        attachments = message.get("attachments", [])

        content_type = "text"
        media_url = None

        if attachments:
            att = attachments[0]
            att_type = att.get("type", "text")
            if att_type == "image":
                content_type = "image"
                media_url = att.get("payload", {}).get("url")
            elif att_type == "audio":
                content_type = "voice"
                media_url = att.get("payload", {}).get("url")
            elif att_type == "video":
                content_type = "video"
                media_url = att.get("payload", {}).get("url")
            elif att_type == "file":
                content_type = "file"
                media_url = att.get("payload", {}).get("url")
            elif text is None:
                content_type = "unsupported"

        mid = message.get("mid")

        return [InboundMessage(
            channel="instagram",
            channel_message_id=mid,
            customer_ref=str(sender.get("id", "")),
            customer_name=None,
            body=text,
            media_url=media_url,
            media_type=content_type if media_url else None,
            content_type=content_type,
            conversation_ref=str(recipient.get("id", "")),
            raw=payload,
        )]

    async def send(
        self,
        credentials: ProviderCredentials,
        message: OutboundMessage,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """Send an outbound Instagram message via Graph API.

        _client is an injection point for tests (MockTransport).
        """
        token = credentials.get("api_key")
        account_id = credentials.get("account_id")
        if not token or not account_id:
            raise ExternalProviderError("instagram integration missing api_key or account_id")
        url = f"{self._base}/{account_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "recipient": {"id": message.customer_ref},
            "message": {"text": message.body or ""},
        }
        if message.template_name:
            payload["message"] = {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": message.template_name,
                        **message.template_vars,
                    },
                }
            }

        async def _post() -> str:
            """Post and return the provider message id — entirely inside the breaker."""
            if _client is not None:
                resp = await _client.post(url, headers=headers, json=payload)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
            # A provider that REJECTS the send is a provider FAILURE, so it must
            # be raised INSIDE the breaker — checking the status outside would
            # record a rejecting provider as a SUCCESS and never open the breaker.
            data = parse_provider_body(resp, "instagram send")
            if resp.status_code not in (200, 201):
                raise ExternalProviderError(
                    f"instagram send failed: HTTP {resp.status_code} — {str(data)[:200]}"
                )
            return str(data.get("message_id", ""))

        # §47/G-13: the outbound call goes through the process-wide
        # `provider.instagram` breaker, so a dead provider is backed off instead
        # of hammered on every send and worker retry. An OPEN breaker raises
        # CircuitOpenError; deciding whether that retries or fails is the caller's
        # job, not the adapter's.
        return await get_breaker(PROVIDER_INSTAGRAM).call(_post)


instagram_adapter = InstagramAdapter()
