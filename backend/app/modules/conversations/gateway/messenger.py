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
        """Delivery receipts: ``messaging[].delivery.mids`` -> one ``delivered`` each.

        A read receipt carries only a watermark (everything up to that time was read), not message
        ids, so it cannot name a row here. It is surfaced by `parse_read_watermarks` instead and
        applied against the conversation by the ingest step that knows our outbound rows.
        """
        updates: list[StatusUpdate] = []
        for event in self._messaging_events(payload):
            delivery = event.get("delivery")
            if not isinstance(delivery, dict):
                continue
            watermark = delivery.get("watermark")
            for mid in delivery.get("mids") or []:
                if mid:
                    updates.append(
                        StatusUpdate(
                            channel_message_id=str(mid),
                            status="delivered",
                            timestamp=watermark,
                        )
                    )
        return updates

    def parse_read_watermarks(self, payload: dict) -> list[dict]:
        """Read receipts: ``{"customer_ref", "watermark"}``, one per ``messaging[].read`` event.

        Messenger says "the customer read everything we sent up to <watermark>". Nothing in the
        event names a message, so the caller marks the customer's outbound rows up to that time.
        """
        out: list[dict] = []
        for event in self._messaging_events(payload):
            read = event.get("read")
            if isinstance(read, dict) and read.get("watermark") is not None:
                out.append(
                    {
                        "customer_ref": str((event.get("sender") or {}).get("id", "")),
                        "watermark": read.get("watermark"),
                    }
                )
        return out

    @staticmethod
    def _messaging_events(payload: dict):
        for entry in payload.get("entry", []) or []:
            for event in entry.get("messaging", []) or []:
                if isinstance(event, dict):
                    yield event

    def parse_comments(self, payload: dict) -> list[InboundComment]:
        """Public page/post comments ride the SAME signed webhook envelope —
        field "feed" (item=comment). Facebook Page inherits this verbatim."""
        return parse_meta_comment_changes(payload)

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        """Parse a Meta Messenger webhook payload into 0..n messages.

        Always a list — the dispatcher and the WebhookWorker iterate it. Events that are not a
        customer's chat message (receipts, echoes of our own sends, thread-control handovers) yield
        nothing here; they are surfaced by their own parse_* methods.
        """
        messages: list[InboundMessage] = []
        for event in self._messaging_events(payload):
            messages.extend(self._parse_message_event(event, payload))
        return messages

    def _parse_message_event(self, event: dict, payload: dict) -> list[InboundMessage]:
        sender = event.get("sender") or {}
        recipient = event.get("recipient") or {}

        postback = event.get("postback")
        if isinstance(postback, dict):
            parsed = self._parse_postback(event, postback, sender, recipient, payload)
            return [parsed] if parsed is not None else []

        referral = event.get("referral")
        if isinstance(referral, dict):
            parsed = self._parse_referral(event, referral, sender, recipient, payload)
            return [parsed] if parsed is not None else []

        reaction = event.get("reaction")
        if isinstance(reaction, dict):
            parsed = self._parse_reaction(event, reaction, sender, recipient, payload)
            return [parsed] if parsed is not None else []

        message = event.get("message")
        if not isinstance(message, dict) or not message:
            return []
        # Our own send echoed back by Meta: not something the customer said.
        if message.get("is_echo"):
            return []

        mid = message.get("mid")
        text = message.get("text")
        reply_to = (message.get("reply_to") or {}).get("mid")
        attachments = [a for a in (message.get("attachments") or []) if isinstance(a, dict)]
        if not attachments:
            return [
                self._build(sender, recipient, payload, mid, text, None, None, "text", reply_to)
            ]

        # One event can carry several attachments (an album). Each becomes its own message so none
        # is lost: the first keeps the provider id and the caption, the rest get a stable suffixed
        # id (a retried delivery still dedupes) and no caption.
        type_map = {"image": "image", "audio": "voice", "video": "video", "file": "file"}
        out: list[InboundMessage] = []
        for index, att in enumerate(attachments):
            att_type = att.get("type", "")
            content_type = type_map.get(att_type, "unsupported")
            media_url = (att.get("payload") or {}).get("url")
            if att_type == "location":
                content_type = "location"
            out.append(
                self._build(
                    sender,
                    recipient,
                    payload,
                    mid if index == 0 or not mid else f"{mid}#{index}",
                    text if index == 0 else None,
                    media_url,
                    content_type if media_url else None,
                    content_type,
                    reply_to,
                )
            )
        return out

    def _build(
        self,
        sender: dict,
        recipient: dict,
        payload: dict,
        mid: str | None,
        body: str | None,
        media_url: str | None,
        media_type: str | None,
        content_type: str,
        reply_to: str | None,
    ) -> InboundMessage:
        return InboundMessage(
            channel=self.channel,
            channel_message_id=mid,
            customer_ref=str(sender.get("id", "")),
            customer_name=None,
            body=body,
            media_url=media_url,
            media_type=media_type,
            content_type=content_type,
            reply_to_message_id=reply_to,
            conversation_ref=str(recipient.get("id", "")),
            raw=payload,
        )

    def _parse_postback(
        self, event: dict, postback: dict, sender: dict, recipient: dict, payload: dict
    ) -> InboundMessage | None:
        """A tap on a button, quick reply or persistent-menu item.

        It reads as the customer saying the button's title. A postback has no message id, so the
        id is made from who, when and what: the same tap redelivered is one message.
        """
        title = str(postback.get("title") or postback.get("payload") or "").strip()
        if not title or not sender.get("id"):
            return None
        stamp = event.get("timestamp") or ""
        key = f"postback:{sender.get('id')}:{stamp}:{postback.get('payload') or ''}"
        ref = postback.get("referral")
        return InboundMessage(
            channel=self.channel,
            channel_message_id=postback.get("mid") or key,
            customer_ref=str(sender.get("id", "")),
            body=title,
            content_type="text",
            conversation_ref=str(recipient.get("id", "")),
            raw={
                **payload,
                "_messenger": {
                    "postback_payload": postback.get("payload"),
                    **({"referral": ref} if isinstance(ref, dict) else {}),
                },
            },
        )

    def _parse_referral(
        self, event: dict, referral: dict, sender: dict, recipient: dict, payload: dict
    ) -> InboundMessage | None:
        """How the customer reached the chat (m.me link, ad, shop). Kept as context, not chatter.

        Stored as a system-flavoured text row with a stable id so the source is visible on the
        conversation and a redelivery is one row. An ad referral also names the ad id, which the
        policy layer uses to extend the reply window.
        """
        if not sender.get("id"):
            return None
        source = str(referral.get("source") or "").strip()
        ref = str(referral.get("ref") or "").strip()
        ad_id = str(referral.get("ad_id") or "").strip()
        stamp = event.get("timestamp") or ""
        key = f"referral:{sender.get('id')}:{stamp}:{ad_id or ref or source}"
        label = " / ".join(x for x in (source, ref, f"ad {ad_id}" if ad_id else "") if x)
        return InboundMessage(
            channel=self.channel,
            channel_message_id=key,
            customer_ref=str(sender.get("id", "")),
            body=label or "referral",
            content_type="text",
            conversation_ref=str(recipient.get("id", "")),
            raw={**payload, "_messenger": {"referral": referral}},
        )

    def _parse_reaction(
        self, event: dict, reaction: dict, sender: dict, recipient: dict, payload: dict
    ) -> InboundMessage | None:
        """A customer's emoji on one of our messages. The id is derived from the event so a
        redelivered reaction is one row, never a duplicate."""
        target = reaction.get("mid")
        if not target or not sender.get("id"):
            return None
        action = reaction.get("action")
        emoji = (reaction.get("emoji") or reaction.get("reaction") or "").strip()
        if action == "unreact" or not emoji:
            emoji = "\u200b-"  # same "withdrawn" marker the Instagram adapter stores
        stamp = event.get("timestamp") or ""
        key = f"reaction:{sender.get('id')}:{target}:{stamp}:{action or 'react'}"
        return InboundMessage(
            channel=self.channel,
            channel_message_id=key,
            customer_ref=str(sender.get("id", "")),
            body=emoji,
            content_type="reaction",
            reply_to_message_id=str(target),
            conversation_ref=str(recipient.get("id", "")),
            raw=payload,
        )

    def parse_handovers(self, payload: dict) -> list[dict]:
        """Thread-control events: pass / take / request, and Meta Business AI hand-offs.

        ``messaging_handovers`` carries ``pass_thread_control``, ``take_thread_control`` and
        ``request_thread_control``. Returned as plain dicts so the caller can pause or resume the
        AI on that conversation; nothing here changes state by itself.
        """
        out: list[dict] = []
        for event in self._messaging_events(payload):
            for kind in ("pass_thread_control", "take_thread_control", "request_thread_control"):
                data = event.get(kind)
                if isinstance(data, dict):
                    out.append(
                        {
                            "customer_ref": str((event.get("sender") or {}).get("id", "")),
                            "event": kind,
                            "new_owner_app_id": data.get("new_owner_app_id"),
                            "previous_owner_app_id": data.get("previous_owner_app_id"),
                            "metadata": data.get("metadata"),
                            "reason": data.get("handoff_reason") or data.get("reason"),
                            "timestamp": event.get("timestamp"),
                        }
                    )
        return out

    def parse_echoes(self, payload: dict) -> list[dict]:
        """Messages WE (or a human on the Page inbox) sent, echoed back: ``is_echo`` events.

        ``customer_ref`` is the recipient (the customer) and ``app_id`` says which app sent it, so
        a reply typed in Meta's own inbox can be told apart from one this system sent.
        """
        out: list[dict] = []
        for event in self._messaging_events(payload):
            message = event.get("message")
            if isinstance(message, dict) and message.get("is_echo"):
                out.append(
                    {
                        "customer_ref": str((event.get("recipient") or {}).get("id", "")),
                        "mid": message.get("mid"),
                        "app_id": message.get("app_id"),
                        "text": message.get("text"),
                        "timestamp": event.get("timestamp"),
                    }
                )
        return out

    async def fetch_profile(
        self, credentials: dict, psid: str, *, _client: httpx.AsyncClient | None = None
    ) -> dict[str, str] | None:
        """The customer's name (and picture) from Meta, or None when Meta will not say.

        Messenger webhooks carry only the page-scoped id, so a customer shows in the inbox as a
        number. Meta answers ``GET /{psid}?fields=name,profile_pic`` with the Page token, but only
        for a person who has messaged the Page, and may refuse (a user who blocked profile access,
        a token without the right permission, rate limits). Every failure here is "no name": it
        must never fail a message that was already received.
        """
        token = (credentials or {}).get("api_key") or (credentials or {}).get("page_access_token")
        if not token or not psid:
            return None
        try:
            if _client is not None:
                response = await _client.get(
                    f"{self._base}/{psid}",
                    params={"fields": "name,profile_pic"},
                    headers={"Authorization": f"Bearer {token}"},
                )
            else:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"{self._base}/{psid}",
                        params={"fields": "name,profile_pic"},
                        headers={"Authorization": f"Bearer {token}"},
                    )
            if not response.is_success:
                return None
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        name = str(data.get("name") or "").strip()
        if not name:
            return None
        out = {"name": name[:255]}
        picture = str(data.get("profile_pic") or "").strip()
        if picture:
            out["profile_pic"] = picture
        return out

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

        # A person's reply after the 24h window (inside the 7-day human-agent window) MUST carry
        # the HUMAN_AGENT tag or Meta refuses it. Every other send is left as it was: Meta treats
        # a send with no messaging_type as a RESPONSE.
        if message.meta.get("human_agent"):
            for body in payloads:
                body["messaging_type"] = "MESSAGE_TAG"
                body["tag"] = "HUMAN_AGENT"

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
