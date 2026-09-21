"""Spec §26 / §175 Phase 3 — Email channel adapter.

Inbound: email webhook → parse → normalize → canonical InboundMessage.
Outbound: OutboundMessage → send via SMTP/ESP provider.

The core never knows it is talking to an email provider — only the
ChannelAdapter interface.
"""

from __future__ import annotations

import logging

import httpx

from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import (
    ChannelAdapter,
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
    StatusUpdate,
)

logger = logging.getLogger(__name__)


class EmailAdapter(ChannelAdapter):
    """Email channel adapter — supports SendGrid/Mailgun-style webhooks.

    Inbound: receives email webhook events, normalizes to InboundMessage.
    Outbound: sends via the ESP's REST API.
    """

    channel = "email"

    def __init__(
        self,
        *,
        provider: str = "sendgrid",
        api_key: str | None = None,
        from_email: str | None = None,
        webhook_secret: str | None = None,
    ):
        self._provider = provider
        self._api_key = api_key
        self._from_email = from_email
        self._webhook_secret = webhook_secret

    async def verify_webhook(
        self, signature: str | None, body: bytes, headers: dict[str, str]
    ) -> bool:
        """Verify the ESP webhook signature."""
        if self._provider == "sendgrid":
            # SendGrid uses an API key in the Authorization header
            return headers.get("authorization", "").strip() == f"Bearer {self._webhook_secret}"
        if self._provider == "mailgun":
            # Mailgun signs with HMAC in a signature header
            import hashlib
            import hmac
            expected = hmac.new(
                key=self._webhook_secret.encode() if self._webhook_secret else b"",
                msg=body,
                digestmod=hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(signature or "", expected)
        return False

    async def parse_inbound(
        self, raw: dict, headers: dict[str, str]
    ) -> InboundMessage:
        """Parse an ESP webhook payload into a canonical InboundMessage."""
        if self._provider == "sendgrid":
            return self._parse_sendgrid(raw)
        if self._provider == "mailgun":
            return self._parse_mailgun(raw)
        raise ExternalProviderError(f"unknown email provider: {self._provider}")

    def _parse_sendgrid(self, raw: dict) -> InboundMessage:
        """Parse a SendGrid inbound parse webhook."""
        from_addr = raw.get("from", "")
        to_addr = raw.get("to", "")
        _subject = raw.get("subject", "")
        body = raw.get("text", raw.get("html", ""))
        message_id = raw.get("messageId", raw.get("message_id"))

        return InboundMessage(
            channel="email",
            channel_message_id=message_id,
            customer_ref=from_addr,
            customer_name=from_addr.split("<")[0].strip() if "<" in from_addr else from_addr,
            body=body,
            content_type="text",
            raw=raw,
            conversation_ref=to_addr,
        )

    def _parse_mailgun(self, raw: dict) -> InboundMessage:
        """Parse a Mailgun webhook payload."""
        from_addr = raw.get("sender", raw.get("from", ""))
        to_addr = raw.get("recipient", raw.get("to", ""))
        _subject = raw.get("subject", "")
        body = raw.get("body-plain", raw.get("body-html", ""))
        message_id = raw.get("Message-Id", raw.get("messageId"))

        return InboundMessage(
            channel="email",
            channel_message_id=message_id,
            customer_ref=from_addr,
            customer_name=from_addr,
            body=body,
            content_type="text",
            raw=raw,
            conversation_ref=to_addr,
        )

    async def send(
        self, message: OutboundMessage, credentials: ProviderCredentials
    ) -> StatusUpdate:
        """Send an outbound email via the ESP."""
        url = self._get_send_url()
        headers = {
            "Authorization": f"Bearer {credentials.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "personalizations": [
                {"to": [{"email": message.customer_ref}]}
            ],
            "from": {"email": self._from_email or "noreply@example.com"},
            "subject": message.meta.get("subject", "Message"),
            "content": [
                {"type": "text/plain", "value": message.body or ""},
            ],
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)

        if resp.status_code in (200, 201, 202):
            return StatusUpdate(
                message_id=message.message_id,
                provider_message_id=resp.headers.get("X-Message-Id"),
                status="sent",
            )
        raise ExternalProviderError(
            f"email send failed: HTTP {resp.status_code} — {resp.text[:200]}"
        )

    def _get_send_url(self) -> str:
        if self._provider == "sendgrid":
            return "https://api.sendgrid.com/v3/mail/send"
        if self._provider == "mailgun":
            return f"https://api.mailgun.net/v3/{self._from_email.split('@')[1]}/messages"
        raise ExternalProviderError(f"unknown email provider: {self._provider}")
