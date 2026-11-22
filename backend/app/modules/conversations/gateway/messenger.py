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

from app.core.circuit_breaker import PROVIDER_MESSENGER, get_breaker
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
from app.modules.conversations.gateway.messenger_media import (
    MessengerLimitError,
    attachment_type,
    check_attachment,
)

logger = logging.getLogger(__name__)


class MessengerAdapter(ChannelAdapter):
    """Facebook Messenger adapter via Meta Graph API.

    Inbound: webhook → verify X-Hub-Signature-256 → parse entry[0].messaging[0].
    Outbound: POST to Graph API /me/messages endpoint.
    """

    name = "messenger"  # ChannelAdapter registry key
    channel = "messenger"

    def __init__(self, *, api_version: str = "v27.0"):
        # All secrets live in settings, read per call — a constructor-injected
        # secret can only go stale (the removed per-instance `verify_webhook`
        # verified nothing for exactly that reason).
        self._base = f"https://graph.facebook.com/{api_version}"

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        """Meta webhook subscription handshake (GET hub.challenge)."""
        # The verify token is THIS channel's own. Another channel's token (WhatsApp's) is not a
        # credential for a Page subscription, so it is never accepted here.
        expected = get_settings().messenger_verify_token
        if not expected:
            return None
        if (
            query_params.get("hub.mode") == "subscribe"
            and query_params.get("hub.verify_token") == expected
        ):
            return query_params.get("hub.challenge", "")
        return None

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        """X-Hub-Signature-256 (HMAC-SHA256) — fail closed without a secret."""
        # One Meta app signs all of its webhooks, so its app secret is a legitimate fallback.
        settings = get_settings()
        secret = settings.messenger_app_secret or getattr(settings, "meta_app_secret", "")
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

    def partition_payloads(self, payload: dict) -> list[tuple[str | None, dict]]:
        """Keep each page's events under the tenant that owns that page."""
        grouped: dict[str, list[dict]] = {}
        for entry in payload.get("entry", []) or []:
            account_id = str(entry.get("id") or "").strip()
            if account_id:
                grouped.setdefault(account_id, []).append(entry)
        return [
            (
                account_id,
                {
                    **{key: value for key, value in payload.items() if key != "entry"},
                    "entry": entries,
                },
            )
            for account_id, entries in grouped.items()
        ]

    def split_by_account(self, payload: dict) -> list[dict]:
        """One envelope per Page, which is how the webhook router asks adapters to split.

        The router resolves the store from the FIRST envelope's key, so without this a delivery
        naming two Pages is filed entirely under the first Page's store. `partition_payloads`
        already does the grouping; a delivery for one Page (the usual case), or with no usable
        entry at all, is returned untouched.
        """
        parts = self.partition_payloads(payload)
        if len(parts) <= 1:
            return [payload]
        return [part for _key, part in parts]

    def parse_status_updates(self, payload: dict) -> list[StatusUpdate]:
        # Meta delivery/read receipts arrive as messaging[0].delivery|read —
        # inbound-only for now; the generic status path handles the rest.
        return []

    def parse_comments(self, payload: dict) -> list[InboundComment]:
        """Public page/post comments ride the SAME signed webhook envelope —
        field "feed" (item=comment). Facebook Page inherits this verbatim."""
        return parse_meta_comment_changes(payload)

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        """Parse a Meta Messenger webhook payload into 0..1 messages.

        Always a list — the dispatcher and the WebhookWorker iterate it, so the
        ``None`` this used to return on an empty envelope crashed the hot path
        instead of yielding zero messages.
        """
        entries = payload.get("entry", []) or []
        messages: list[InboundMessage] = []
        for entry in entries:
            for event in entry.get("messaging", []) or []:
                messages.extend(self._parse_message_event(event, payload))
        return messages

    def _parse_message_event(self, event: dict, payload: dict) -> list[InboundMessage]:
        sender = event.get("sender", {})
        recipient = event.get("recipient", {})
        message = event.get("message", {})

        if not message:
            return []

        # An echo is the Page's own outgoing message coming back on the `message_echoes` field.
        # Without this guard the store's reply is stored as an INBOUND customer message, so the
        # agent's own words appear in the thread as if the customer had written them.
        if message.get("is_echo"):
            return []

        text = message.get("text")
        attachments = message.get("attachments", [])
        # A quote rides the message as the mid of the message being answered.
        reply_to = (message.get("reply_to") or {}).get("mid")

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

        return [
            InboundMessage(
                channel=self.channel,
                channel_message_id=mid,
                customer_ref=str(sender.get("id", "")),
                customer_name=None,
                body=text,
                media_url=media_url,
                media_type=content_type if media_url else None,
                content_type=content_type,
                reply_to_message_id=reply_to,
                conversation_ref=str(recipient.get("id", "")),
                raw=payload,
            )
        ]

    async def get_user_profile(
        self,
        credentials: ProviderCredentials,
        psid: str,
        _client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any] | None:
        """The customer's name and photo by their page-scoped id, or None when Meta refuses.

        A Messenger webhook names the sender only by a PSID, so without this read every thread
        in the inbox is a number. A refusal is normal and is not an error: someone who has not
        messaged the page has not consented, and the caller simply keeps the number.
        """
        token = credentials.get("api_key") or credentials.get("page_access_token")
        if not token:
            return None
        url = f"{self._base}/{psid}"
        params = {"fields": "name,profile_pic", "access_token": token}
        try:
            if _client is not None:
                resp = await _client.get(url, params=params)
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url, params=params)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        data = resp.json() if resp.content else {}
        if not isinstance(data, dict) or data.get("error"):
            return None
        name = (data.get("name") or "").strip() or None
        pic = data.get("profile_pic") or None
        if not name and not pic:
            return None
        return {"name": name, "profile_pic": pic}

    def build_sender_action(self, customer_ref: str, action: str) -> dict[str, Any]:
        """A sender action carries no message: it only tells the thread what the agent is doing."""
        return {"recipient": {"id": customer_ref}, "sender_action": action}

    async def send_sender_action(
        self,
        credentials: ProviderCredentials,
        customer_ref: str,
        action: str,
        _client: httpx.AsyncClient | None = None,
    ) -> None:
        """mark_seen when the agent opens the chat, typing_on while they write.

        The same Graph endpoint as a send, addressed to the customer's PSID. A courtesy signal:
        the caller swallows a failure, and it never opens the 24h window.
        """
        token = credentials.get("api_key") or credentials.get("page_access_token")
        if not token:
            raise ExternalProviderError("messenger integration missing api_key")
        url = f"{self._base}/me/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = self.build_sender_action(customer_ref, action)

        async def _post() -> None:
            if _client is not None:
                resp = await _client.post(url, headers=headers, json=body)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, headers=headers, json=body)
            data = parse_provider_body(resp, "messenger sender action")
            if resp.status_code not in (200, 201):
                raise ExternalProviderError(
                    f"messenger {action} failed: HTTP {resp.status_code} — {str(data)[:200]}"
                )

        await get_breaker(PROVIDER_MESSENGER).call(_post)

    async def send(
        self,
        credentials: ProviderCredentials,
        message: OutboundMessage,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """Send an outbound Messenger message via Graph API.

        _client is an injection point for tests (MockTransport).
        """
        token = credentials.get("api_key") or credentials.get("page_access_token")
        if not token:
            raise ExternalProviderError("messenger integration missing api_key")
        url = f"{self._base}/me/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        recipient = {"id": message.customer_ref}
        # A text message and an attachment are two messages on Messenger: one request cannot carry
        # both. A file with a caption therefore goes out as the file, then the caption.
        payloads: list[dict[str, Any]] = []
        if message.template_name:
            payloads.append(
                {
                    "recipient": recipient,
                    "message": {
                        "attachment": {
                            "type": "template",
                            "payload": {
                                "template_type": message.template_name,
                                **message.template_vars,
                            },
                        }
                    },
                }
            )
        elif message.media_url:
            kind = attachment_type(message.meta.get("media_type"))
            try:
                check_attachment(message.media_url, kind, message.meta.get("media_size_bytes"))
            except MessengerLimitError as exc:
                raise ExternalProviderError(f"messenger send refused: {exc}") from exc
            payloads.append(
                {
                    "recipient": recipient,
                    "message": {
                        "attachment": {"type": kind, "payload": {"url": message.media_url}}
                    },
                }
            )
            if message.body:
                payloads.append({"recipient": recipient, "message": {"text": message.body}})
        else:
            payloads.append({"recipient": recipient, "message": {"text": message.body or ""}})

        # The policy layer grants a human a 7-day window, but Meta only honours it when the request
        # says so: without the tag a reply after hour 24 is refused by the provider even though we
        # allowed it. Instagram already sends this; Messenger did not.
        for payload in payloads:
            if message.meta.get("human_agent"):
                payload["messaging_type"] = "MESSAGE_TAG"
                payload["tag"] = "HUMAN_AGENT"
            reply_to = message.meta.get("reply_to_provider_id")
            if reply_to:
                payload["reply_to"] = {"mid": reply_to}

        async def _post_one(client: httpx.AsyncClient, payload: dict[str, Any]) -> str:
            resp = await client.post(url, headers=headers, json=payload)
            # A provider that REJECTS the send is a provider FAILURE, so it must
            # be raised INSIDE the breaker — checking the status outside would
            # record a rejecting provider as a SUCCESS and never open the breaker.
            data = parse_provider_body(resp, "messenger send")
            if resp.status_code not in (200, 201):
                raise ExternalProviderError(
                    f"messenger send failed: HTTP {resp.status_code} — {str(data)[:200]}"
                )
            return str(data.get("message_id", ""))

        async def _post() -> str:
            """Post and return the provider message id — entirely inside the breaker.

            With a file and a caption it is the FILE's id that is kept: that is the message the
            conversation row stands for, and the caption follows it.
            """
            ids: list[str] = []
            if _client is not None:
                for payload in payloads:
                    ids.append(await _post_one(_client, payload))
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    for payload in payloads:
                        ids.append(await _post_one(client, payload))
            return ids[0]

        # §47/G-13: the outbound call goes through the process-wide
        # `provider.messenger` breaker, so a dead provider is backed off instead
        # of hammered on every send and worker retry. An OPEN breaker raises
        # CircuitOpenError; deciding whether that retries or fails is the caller's
        # job, not the adapter's.
        return await get_breaker(PROVIDER_MESSENGER).call(_post)


messenger_adapter = MessengerAdapter()
