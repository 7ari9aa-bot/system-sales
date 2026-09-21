"""Spec §26 / §175 Phase 3 — Facebook Messenger channel adapter.

Messenger messaging uses the Meta Graph API, similar to Instagram but
with Messenger-specific webhook fields and endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

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


class MessengerAdapter(ChannelAdapter):
    """Facebook Messenger adapter via Meta Graph API.

    Inbound: webhook → verify X-Hub-Signature-256 → parse entry[0].messaging[0].
    Outbound: POST to Graph API /me/messages endpoint.
    """

    channel = "messenger"

    def __init__(
        self,
        *,
        app_secret: str | None = None,
        access_token: str | None = None,
        page_id: str | None = None,
        api_version: str = "v21.0",
    ):
        self._app_secret = app_secret
        self._access_token = access_token
        self._page_id = page_id
        self._api_version = api_version
        self._base = f"https://graph.facebook.com/{api_version}"

    async def verify_webhook(
        self, signature: str | None, body: bytes, headers: dict[str, str]
    ) -> bool:
        """Verify X-Hub-Signature-256 (HMAC-SHA256)."""
        if not self._app_secret or not signature:
            return False

        expected = "sha256=" + hmac.new(
            self._app_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    async def parse_inbound(
        self, raw: dict, headers: dict[str, str]
    ) -> InboundMessage | None:
        """Parse a Meta Messenger webhook payload."""
        entries = raw.get("entry", [])
        if not entries:
            return None

        messaging = entries[0].get("messaging", [])
        if not messaging:
            return None

        event = messaging[0]
        sender = event.get("sender", {})
        recipient = event.get("recipient", {})
        message = event.get("message", {})

        if not message:
            return None

        text = message.get("text")
        attachments = message.get("attachments", [])

        content_type = "text"
        media_url = None

        if attachments:
            att = attachments[0]
            att_type = att.get("type", "text")
            type_map = {
                "image": "image",
                "audio": "voice",
                "video": "video",
                "file": "file",
            }
            content_type = type_map.get(att_type, "unsupported")
            media_url = att.get("payload", {}).get("url")

        mid = message.get("mid")

        return InboundMessage(
            channel="messenger",
            channel_message_id=mid,
            customer_ref=str(sender.get("id", "")),
            customer_name=None,
            body=text,
            media_url=media_url,
            media_type=content_type if media_url else None,
            content_type=content_type,
            conversation_ref=str(recipient.get("id", "")),
            raw=raw,
        )

    async def send(
        self, message: OutboundMessage, credentials: ProviderCredentials
    ) -> StatusUpdate:
        """Send an outbound Messenger message via Graph API."""
        url = f"{self._base}/me/messages"
        headers = {
            "Authorization": f"Bearer {credentials.api_key}",
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

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)

        data = resp.json()
        if resp.status_code in (200, 201):
            message_id = data.get("message_id")
            return StatusUpdate(
                message_id=message.message_id,
                provider_message_id=message_id,
                status="sent",
            )
        raise ExternalProviderError(
            f"messenger send failed: HTTP {resp.status_code} — {data}"
        )
