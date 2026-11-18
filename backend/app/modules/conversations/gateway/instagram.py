"""Spec §26 / §175 Phase 3 — Instagram channel adapter.

Instagram messaging uses the Meta Graph API — the same pattern as the
WhatsApp adapter but with Instagram-specific endpoints and payload shapes.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.core.circuit_breaker import PROVIDER_INSTAGRAM, get_breaker
from app.core.config import get_settings
from app.core.errors import ExternalProviderError
from app.core.instagram_version import INSTAGRAM_API_VERSION
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
from app.modules.conversations.gateway.instagram_limits import (
    MAX_QUICK_REPLIES,
    QUICK_REPLY_TITLE_CHARS,
    InstagramFailure,
    check_media,
    check_text,
    classify_instagram_error,
    media_kind,
)

logger = logging.getLogger(__name__)

# Stored as the body of a reaction row that withdraws the sender's earlier reaction.
REACTION_REMOVED = "\u2205"


class InstagramProviderError(ExternalProviderError):
    """A Graph refusal that carries what to do about it (see `instagram_limits`).

    It IS an ExternalProviderError, so every caller that already catches that keeps working;
    the ones that care (the send worker, the inbox) read `.failure` instead of parsing text.
    """

    def __init__(self, message: str, failure: InstagramFailure) -> None:
        super().__init__(message)
        self.failure = failure
        self.retryable = failure.retryable


def _refusal(context: str, status: int | None, data: Any) -> InstagramProviderError:
    """Build the error for a refused Graph call, classified from Meta's own error object."""
    failure = classify_instagram_error(data if isinstance(data, dict) else str(data))
    if failure.kind == "unknown" and status is not None:
        failure = classify_instagram_error(f"HTTP {status} {data}")
    head = f"{context} failed: HTTP {status}" if status is not None else f"{context} failed"
    return InstagramProviderError(f"{head} [{failure.kind}] - {str(data)[:200]}", failure)


class InstagramAdapter(ChannelAdapter):
    """Instagram messaging adapter via Meta Graph API.

    Inbound: webhook → verify X-Hub-Signature-256 → parse entry[0].messaging[0].
    Outbound: POST to Graph API /messages endpoint.
    """

    name = "instagram"  # ChannelAdapter registry key
    channel = "instagram"

    def __init__(self, *, api_version: str = INSTAGRAM_API_VERSION):
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

    @classmethod
    def check_outbound(cls, message: OutboundMessage) -> None:
        """Refuse what Instagram would refuse, before spending a call on it.

        Raises InstagramLimitError (a ValueError) naming the rule broken. A reaction, a heart
        and a shared post carry no free text, so only text and media are measured.
        """
        meta = message.meta or {}
        if (
            meta.get("reaction_to_provider_id")
            or meta.get("like_heart")
            or meta.get("share_media_id")
        ):
            return
        if message.media_url:
            check_media(
                message.media_url,
                media_kind(meta.get("media_type")),
                meta.get("media_size_bytes"),
            )
            return
        if not message.template_name:
            check_text(message.body)

    @classmethod
    def build_send_payload(cls, message: OutboundMessage) -> dict[str, Any]:
        """The Graph API body for one outbound message (pure, so it is testable).

        A reaction names its target by provider id and carries only an emoji (an
        empty one withdraws it). Anything else is text, one media attachment, or a
        template, optionally quoting an earlier message.
        """
        recipient = {"id": message.customer_ref}
        cls.check_outbound(message)
        target = message.meta.get("reaction_to_provider_id")
        if target:
            emoji = message.body or ""
            if emoji == REACTION_REMOVED or not emoji:
                return {
                    "recipient": recipient,
                    "sender_action": "unreact",
                    "payload": {"message_id": target},
                }
            return {
                "recipient": recipient,
                "sender_action": "react",
                "payload": {"message_id": target, "reaction": emoji},
            }
        if message.template_name:
            body: dict[str, Any] = {
                "attachment": {
                    "type": "template",
                    "payload": {"template_type": message.template_name, **message.template_vars},
                }
            }
        elif message.meta.get("like_heart"):
            body = {"attachment": {"type": "like_heart"}}
        elif message.meta.get("share_media_id"):
            body = {
                "attachment": {
                    "type": "MEDIA_SHARE",
                    "payload": {"id": message.meta["share_media_id"]},
                }
            }
        elif message.media_url:
            kind = media_kind(message.meta.get("media_type"))
            body = {"attachment": {"type": kind, "payload": {"url": message.media_url}}}
        else:
            body = {"text": message.body or ""}
        payload: dict[str, Any] = {"recipient": recipient, "message": body}
        if message.meta.get("human_agent"):
            # A person's reply after the 24h window, inside the 7-day human-agent window.
            payload["messaging_type"] = "MESSAGE_TAG"
            payload["tag"] = "HUMAN_AGENT"
        reply_to = message.meta.get("reply_to_provider_id")
        if reply_to:
            # Verified: reply_to sits at the ROOT of the request, beside "message".
            payload["reply_to"] = {"mid": reply_to}
        quick = message.meta.get("quick_replies")
        if quick and "text" in body:
            body["quick_replies"] = [
                {
                    "content_type": "text",
                    "title": str(q.get("title", ""))[:QUICK_REPLY_TITLE_CHARS],
                    "payload": str(q.get("payload", q.get("title", ""))),
                }
                for q in quick[:MAX_QUICK_REPLIES]
            ]
        return payload

    @staticmethod
    def build_sender_action(customer_ref: str, action: str) -> dict[str, Any]:
        """mark_seen / typing_on / typing_off — no message body, just the action."""
        if action not in ("mark_seen", "typing_on", "typing_off"):
            raise ValueError(f"unsupported sender action: {action}")
        return {"recipient": {"id": customer_ref}, "sender_action": action}

    async def send_sender_action(
        self,
        credentials: ProviderCredentials,
        customer_ref: str,
        action: str,
        _client: httpx.AsyncClient | None = None,
    ) -> None:
        """Tell Instagram the agent saw the chat / is typing. Best effort for the caller."""
        token = credentials.get("api_key")
        account_id = credentials.get("account_id")
        if not token or not account_id:
            raise ExternalProviderError("instagram integration missing api_key or account_id")
        url = f"{self._base}/{account_id}/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = self.build_sender_action(customer_ref, action)

        async def _post() -> None:
            if _client is not None:
                resp = await _client.post(url, headers=headers, json=body)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, headers=headers, json=body)
            data = parse_provider_body(resp, "instagram sender action")
            if resp.status_code not in (200, 201):
                raise _refusal(f"instagram {action}", resp.status_code, data)

        await get_breaker(PROVIDER_INSTAGRAM).call(_post)

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
        payload = self.build_send_payload(message)

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
                raise _refusal("instagram send", resp.status_code, data)
            if "error" in data:
                raise _refusal("instagram send", resp.status_code, data)
            return str(data.get("message_id", ""))

        # §47/G-13: the outbound call goes through the process-wide
        # `provider.instagram` breaker, so a dead provider is backed off instead
        # of hammered on every send and worker retry. An OPEN breaker raises
        # CircuitOpenError; deciding whether that retries or fails is the caller's
        # job, not the adapter's.
        return await get_breaker(PROVIDER_INSTAGRAM).call(_post)

    # ---------- posts and comments (the store's own content) ----------
    #
    # Endpoints and fields are the ones Meta documents for comment moderation and
    # private replies (pages updated Oct 2026). A commenter arrives as an id and a
    # username only: Instagram gives no photo or follower data for a commenter.

    _MEDIA_FIELDS = (
        "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,"
        "timestamp,like_count,comments_count"
    )
    _COMMENT_FIELDS = "id,text,username,timestamp,like_count,hidden,parent_id,from"

    @staticmethod
    def _creds(credentials: ProviderCredentials) -> tuple[str, str]:
        token = credentials.get("api_key")
        account_id = credentials.get("account_id")
        if not token or not account_id:
            raise ExternalProviderError("instagram integration missing api_key or account_id")
        return str(token), str(account_id)

    async def _graph(
        self,
        method: str,
        path: str,
        credentials: ProviderCredentials,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """One Graph call, inside the breaker. A rejection is a provider FAILURE."""
        token, _ = self._creds(credentials)
        url = f"{self._base}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {token}"}

        async def _call() -> dict[str, Any]:
            if _client is not None:
                resp = await _client.request(method, url, headers=headers, params=params, json=json)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.request(
                        method, url, headers=headers, params=params, json=json
                    )
            data = parse_provider_body(resp, f"instagram {method} {path}")
            if resp.status_code not in (200, 201):
                raise _refusal(f"instagram {method} {path}", resp.status_code, data)
            if "error" in data:
                raise _refusal(f"instagram {method} {path}", resp.status_code, data)
            return data

        return await get_breaker(PROVIDER_INSTAGRAM).call(_call)

    async def list_media(
        self,
        credentials: ProviderCredentials,
        *,
        limit: int = 25,
        after: str | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """The store's posts, newest first: {"items": [...], "next": cursor|None}."""
        _, account_id = self._creds(credentials)
        params: dict[str, Any] = {"fields": self._MEDIA_FIELDS, "limit": max(1, min(limit, 50))}
        if after:
            params["after"] = after
        data = await self._graph(
            "GET", f"{account_id}/media", credentials, params=params, _client=_client
        )
        return {
            "items": data.get("data") or [],
            "next": ((data.get("paging") or {}).get("cursors") or {}).get("after")
            if (data.get("paging") or {}).get("next")
            else None,
        }

    async def list_comments(
        self,
        credentials: ProviderCredentials,
        media_id: str,
        *,
        limit: int = 50,
        after: str | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Top-level comments of one post, each with its replies inline."""
        params: dict[str, Any] = {
            "fields": f"{self._COMMENT_FIELDS},replies{{{self._COMMENT_FIELDS}}}",
            "limit": max(1, min(limit, 100)),
        }
        if after:
            params["after"] = after
        data = await self._graph(
            "GET", f"{media_id}/comments", credentials, params=params, _client=_client
        )
        return {
            "items": data.get("data") or [],
            "next": ((data.get("paging") or {}).get("cursors") or {}).get("after")
            if (data.get("paging") or {}).get("next")
            else None,
        }

    async def reply_to_comment(
        self,
        credentials: ProviderCredentials,
        comment_id: str,
        text: str,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """A public reply under a comment. Returns the new comment id."""
        data = await self._graph(
            "POST", f"{comment_id}/replies", credentials, params={"message": text}, _client=_client
        )
        return str(data.get("id", ""))

    async def set_comment_hidden(
        self,
        credentials: ProviderCredentials,
        comment_id: str,
        hidden: bool,
        _client: httpx.AsyncClient | None = None,
    ) -> None:
        await self._graph(
            "POST",
            comment_id,
            credentials,
            params={"hide": "true" if hidden else "false"},
            _client=_client,
        )

    async def delete_comment(
        self,
        credentials: ProviderCredentials,
        comment_id: str,
        _client: httpx.AsyncClient | None = None,
    ) -> None:
        await self._graph("DELETE", comment_id, credentials, _client=_client)

    async def set_comments_enabled(
        self,
        credentials: ProviderCredentials,
        media_id: str,
        enabled: bool,
        _client: httpx.AsyncClient | None = None,
    ) -> None:
        await self._graph(
            "POST",
            media_id,
            credentials,
            params={"comment_enabled": "true" if enabled else "false"},
            _client=_client,
        )

    # ---- publishing (photo / carousel; Reels are deliberately not here yet) ----
    # Instagram builds a post in steps: a "container" per picture, a parent container for a
    # carousel, wait until Instagram has fetched the pictures, then publish. A container
    # that is never published expires on its own after 24 hours.
    CAROUSEL_MIN = 2
    CAROUSEL_MAX = 10
    PUBLISH_POLL_SECONDS = 2.0
    PUBLISH_POLL_TRIES = 15

    @staticmethod
    def check_publishable(image_urls: list[str], caption: str | None) -> None:
        """Refuse what Instagram would refuse, before spending a call on it."""
        if not image_urls:
            raise ValueError("a post needs at least one picture")
        if len(image_urls) > InstagramAdapter.CAROUSEL_MAX:
            raise ValueError(f"a post holds at most {InstagramAdapter.CAROUSEL_MAX} pictures")
        for url in image_urls:
            # Instagram downloads the picture itself, so it must be a public web address.
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ValueError("every picture must be a public https link")
        if caption is not None and len(caption) > 2200:
            raise ValueError("a caption is at most 2,200 characters")

    async def _wait_until_ready(
        self,
        credentials: ProviderCredentials,
        container_id: str,
        _client: httpx.AsyncClient | None = None,
    ) -> None:
        """Publishing a container Instagram is still fetching fails, so wait for FINISHED."""
        for _ in range(self.PUBLISH_POLL_TRIES):
            data = await self._graph(
                "GET", container_id, credentials, params={"fields": "status_code"}, _client=_client
            )
            status = data.get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise ExternalProviderError(f"instagram refused the picture ({status})")
            await asyncio.sleep(self.PUBLISH_POLL_SECONDS)
        raise ExternalProviderError("instagram took too long to fetch the pictures")

    async def publish_post(
        self,
        credentials: ProviderCredentials,
        image_urls: list[str],
        caption: str | None = None,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """Publish one picture, or 2-10 as a carousel. Returns the new post's media id."""
        self.check_publishable(image_urls, caption)
        _, account_id = self._creds(credentials)
        if len(image_urls) == 1:
            params: dict[str, Any] = {"image_url": image_urls[0]}
            if caption:
                params["caption"] = caption
            made = await self._graph(
                "POST", f"{account_id}/media", credentials, params=params, _client=_client
            )
            container = str(made["id"])
        else:
            if len(image_urls) < self.CAROUSEL_MIN:
                raise ValueError(f"a carousel needs at least {self.CAROUSEL_MIN} pictures")
            children: list[str] = []
            for url in image_urls:
                child = await self._graph(
                    "POST",
                    f"{account_id}/media",
                    credentials,
                    params={"image_url": url, "is_carousel_item": "true"},
                    _client=_client,
                )
                children.append(str(child["id"]))
            for child_id in children:
                await self._wait_until_ready(credentials, child_id, _client)
            params = {"media_type": "CAROUSEL", "children": ",".join(children)}
            if caption:
                params["caption"] = caption
            made = await self._graph(
                "POST", f"{account_id}/media", credentials, params=params, _client=_client
            )
            container = str(made["id"])
        await self._wait_until_ready(credentials, container, _client)
        done = await self._graph(
            "POST",
            f"{account_id}/media_publish",
            credentials,
            params={"creation_id": container},
            _client=_client,
        )
        return str(done["id"])

    @staticmethod
    def build_private_reply(comment_id: str, text: str) -> dict[str, Any]:
        """A DM to someone who commented. One per comment, within 7 days of it."""
        return {"recipient": {"comment_id": comment_id}, "message": {"text": text}}

    async def send_private_reply(
        self,
        credentials: ProviderCredentials,
        comment_id: str,
        text: str,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """Returns the DM's provider message id (the customer's thread starts here)."""
        _, account_id = self._creds(credentials)
        data = await self._graph(
            "POST",
            f"{account_id}/messages",
            credentials,
            json=self.build_private_reply(comment_id, text),
            _client=_client,
        )
        return str(data.get("message_id", ""))

    # ---------- who the customer is ----------

    _PROFILE_FIELDS = (
        "name,username,profile_pic,is_verified_user,follower_count,"
        "is_user_follow_business,is_business_follow_user"
    )

    async def get_user_profile(
        self,
        credentials: ProviderCredentials,
        igsid: str,
        _client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any] | None:
        """The customer's public profile by their page-scoped id, or None when it cannot be read.

        Meta refuses it for someone who commented but never messaged ("user consent is
        required") and for a blocked user, so a refusal is NORMAL and not an error: the chat
        simply keeps showing what it has. Only a real outage (breaker open, network) raises.
        `profile_pic` is a link that expires after a few days, so the caller must copy the
        image, not keep the link.
        """
        try:
            data = await self._graph(
                "GET", igsid, credentials, params={"fields": self._PROFILE_FIELDS}, _client=_client
            )
        except ExternalProviderError as exc:
            text = str(exc).lower()
            if (
                "consent" in text
                or "cannot be loaded" in text
                or "does not exist" in text
                or "(#100)" in text
            ):
                return None
            if "http 400" in text or "http 403" in text or "http 404" in text:
                return None
            raise
        return {
            "name": (data.get("name") or "").strip() or None,
            "username": (data.get("username") or "").strip() or None,
            "profile_pic": data.get("profile_pic") or None,
            "verified": bool(data.get("is_verified_user")),
            "follower_count": data.get("follower_count"),
            "follows_you": data.get("is_user_follow_business"),
            "you_follow": data.get("is_business_follow_user"),
        }


instagram_adapter = InstagramAdapter()
