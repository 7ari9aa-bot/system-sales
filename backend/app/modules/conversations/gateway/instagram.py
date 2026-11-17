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
    InboundComment,
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
    StatusUpdate,
    parse_meta_comment_changes,
    parse_provider_body,
)

logger = logging.getLogger(__name__)

# Stored as the body of a reaction row that withdraws the sender's earlier reaction.
REACTION_REMOVED = "\u2205"


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
        """Read receipts: ``messaging_seen`` names the last message the customer saw.

        Instagram sends no per-message delivery receipt, only "seen up to this
        message". The id is the provider message id of that last message.
        """
        out: list[StatusUpdate] = []
        for entry in payload.get("entry", []) or []:
            for event in entry.get("messaging", []) or []:
                read = event.get("read")
                if not isinstance(read, dict):
                    continue
                mid = read.get("mid")
                if mid:
                    out.append(
                        StatusUpdate(
                            channel_message_id=str(mid),
                            status="read",
                            timestamp=event.get("timestamp"),
                        )
                    )
        return out

    def parse_comments(self, payload: dict) -> list[InboundComment]:
        """Instagram post comments arrive on field "comments" in the same
        signed envelope — the shared Meta change parser handles both."""
        return parse_meta_comment_changes(payload)

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        """Parse a Meta webhook payload into canonical InboundMessages.

        Handles every inbound shape the Instagram Messaging webhook documents:
        text, image / video / audio / file, shared posts and reels, story
        replies and mentions, stickers (a "like" heart), reactions, edits and
        unsends. Echoes (messages the business sent from the Instagram app
        itself) are skipped: they are not customer messages.
        """
        out: list[InboundMessage] = []
        for entry in payload.get("entry", []) or []:
            for event in entry.get("messaging", []) or []:
                parsed = self._parse_event(event, payload)
                if parsed is not None:
                    out.append(parsed)
        return out

    def _parse_event(self, event: dict, payload: dict) -> InboundMessage | None:
        sender = event.get("sender") or {}
        recipient = event.get("recipient") or {}

        reaction = event.get("reaction")
        if isinstance(reaction, dict):
            return self._parse_reaction(event, reaction, sender, recipient, payload)

        message = event.get("message")
        if not isinstance(message, dict) or not message:
            return None
        if message.get("is_echo"):
            return None

        mid = message.get("mid")
        text = message.get("text")
        reply_to = (message.get("reply_to") or {}).get("mid")
        body, media_url, media_type, content_type = text, None, None, "text"
        extra: dict[str, Any] = {}

        if message.get("is_deleted"):
            # An unsend: the row is kept, the body is cleared by the caller.
            content_type = "deleted"
            body = None
        else:
            attachments = message.get("attachments") or []
            if attachments:
                body, media_url, media_type, content_type, extra = self._parse_attachment(
                    attachments[0], text, message
                )
            elif (message.get("reply_to") or {}).get("story"):
                extra["story_reply"] = message["reply_to"]["story"]

        if reply_to:
            extra["reply_to_provider_id"] = reply_to
        raw = payload if not extra else {**payload, "_ig": extra}

        return InboundMessage(
            channel="instagram",
            channel_message_id=mid,
            customer_ref=str(sender.get("id", "")),
            customer_name=None,
            body=body,
            media_url=media_url,
            media_type=media_type,
            content_type=content_type,
            reply_to_message_id=reply_to,
            conversation_ref=str(recipient.get("id", "")),
            raw=raw,
        )

    @staticmethod
    def _parse_attachment(
        att: dict, text: str | None, message: dict
    ) -> tuple[str | None, str | None, str | None, str, dict[str, Any]]:
        """-> (body, media_url, media_type, canonical content_type, extra)."""
        att_type = att.get("type", "")
        pl = att.get("payload") or {}
        url = pl.get("url")
        if att_type == "image":
            # A sticker is an image whose payload carries a sticker id (the "like" heart).
            if pl.get("sticker_id"):
                return text, url, "image", "sticker", {"sticker_id": pl["sticker_id"]}
            return text, url, "image", "image", {}
        if att_type == "audio":
            return text, url, "audio", "voice", {}
        if att_type == "video":
            return text, url, "video", "video", {}
        if att_type == "file":
            return text, url, "file", "file", {}
        if att_type == "like_heart":
            return "\u2764\ufe0f", None, None, "sticker", {}
        if att_type in ("share", "ig_post", "ig_reel", "reel"):
            return (
                text or pl.get("title"),
                url,
                None,
                "share",
                {"share": {"url": url, "title": pl.get("title"), "kind": att_type}},
            )
        if att_type == "story_mention":
            return text, url, None, "story_mention", {"story_mention": {"url": url}}
        if att_type == "reel_reply" or att_type == "story_reply":
            return text, url, None, "story_reply", {"story_reply": {"url": url}}
        return text, None, None, ("text" if text else "unsupported"), {}

    @staticmethod
    def _parse_reaction(
        event: dict, reaction: dict, sender: dict, recipient: dict, payload: dict
    ) -> InboundMessage | None:
        target = reaction.get("mid")
        if not target:
            return None
        action = reaction.get("action")
        emoji = (reaction.get("emoji") or "").strip()
        if action == "unreact" or not emoji:
            emoji = REACTION_REMOVED
        return InboundMessage(
            channel="instagram",
            channel_message_id=None,
            customer_ref=str(sender.get("id", "")),
            body=emoji,
            content_type="reaction",
            reply_to_message_id=str(target),
            conversation_ref=str(recipient.get("id", "")),
            raw=payload,
        )

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
