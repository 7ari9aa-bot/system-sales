"""Channel Gateway framework — the boundary between platforms and the core.

Adapters own every platform detail (verification, parsing, media, rate limits,
sending quirks). After normalization, the core never knows which channel a
message came from.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from app.core.errors import ExternalProviderError


def parse_provider_body(response: httpx.Response, context: str) -> dict[str, Any]:
    """Decode a provider 2xx body into a JSON object, or raise a provider error.

    A 2xx is not a success: a proxy, CDN or captive portal can answer 200 with an
    HTML error page, and the Graph/Bot APIs answer 200 with an `error` object. A
    bare `response.json()` turned the first case into an unhandled
    `json.JSONDecodeError` — the wrong exception for the caller, and, when the
    decode sits outside `breaker.call()`, a recorded SUCCESS, so a provider
    broken this way never opened the breaker.

    Callers must invoke this INSIDE the breaker, like the status-code check.
    """
    try:
        data = response.json()
    except ValueError as exc:  # json.JSONDecodeError subclasses ValueError
        raise ExternalProviderError(
            f"{context}: provider returned a non-JSON body (HTTP {response.status_code})"
        ) from exc
    if not isinstance(data, dict):
        raise ExternalProviderError(
            f"{context}: provider returned a non-object JSON body (HTTP {response.status_code})"
        )
    return data


@dataclass
class InboundMessage:
    """Normalized inbound message — identical shape for every channel."""

    channel: str  # whatsapp | telegram | webchat | ...
    channel_message_id: str | None  # provider message id (idempotency key)
    customer_ref: str  # channel-side identity (wa_id / chat id / session)
    customer_name: str | None = None
    body: str | None = None
    media_url: str | None = None  # original provider URL (expires!) — fetch to S3
    media_type: str | None = None
    # §155: canonical content type derived by the adapter from the provider
    # payload. text | image | voice | video | file | location | contact |
    # buttons | list | reaction | unsupported. Falls back to "text" when the
    # adapter does not set it, preserving backward compatibility.
    content_type: str = "text"
    # §155: threaded reply — the provider's message id this message replies to.
    reply_to_message_id: str | None = None
    conversation_ref: str | None = None  # channel-side thread id when separate
    raw: dict = field(default_factory=dict)


@dataclass
class OutboundMessage:
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID  # our messages.id (for status updates)
    customer_ref: str
    body: str | None = None
    media_url: str | None = None
    template_name: str | None = None  # required outside 24h window on WhatsApp
    template_vars: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


@dataclass
class StatusUpdate:
    """Provider delivery receipt for a message we sent."""

    channel_message_id: str
    status: str  # sent | delivered | read | failed
    error: str | None = None
    timestamp: Any = None


@dataclass
class InboundComment:
    """Normalized public comment — one social post's comment or reply.

    Deliberately NOT an InboundMessage: a comment is not a conversation turn.
    It does not page anyone, does not start an AI run, and does not open a
    conversation — it is public interaction data the merchant's analyst reads.
    """

    platform_comment_id: str  # idempotency key
    post_id: str | None = None  # the post/media the comment sits on
    parent_comment_id: str | None = None  # a reply thread when present
    author_ref: str | None = None  # platform-side user id
    author_name: str | None = None
    body: str | None = None
    permalink: str | None = None
    like_count: int = 0
    commented_at: datetime | None = None  # platform time, not our receipt time
    verb: str = "add"  # add | edited | remove
    raw: dict = field(default_factory=dict)


#: Field names Meta uses for public comments across its webhook families:
#: page "feed" changes carry item=comment; Instagram uses field "comments".
_COMMENT_FIELDS = ("feed", "comments")


def parse_meta_comment_changes(payload: dict) -> list[InboundComment]:
    """Normalize Meta comment webhook changes — both envelope families.

    Page/web (field ``feed``): value carries ``item: "comment"``, ``verb``
    (add | edited | remove), ``comment_id``, ``post_id``, ``parent_id``,
    ``from``, ``message``, ``created_time`` (epoch seconds).
    Instagram Graph (field ``comments``): value carries ``id``, ``text``,
    ``from``, ``media.id``, ``parent_id``, ``timestamp`` (ISO string).

    A change that is not a comment (a like, a reaction, a post edit) yields
    nothing; an unparseable entry yields nothing — comments are analytics
    input, and a malformed delivery must never fail a webhook that may also
    carry real messages. Returns a list, always.
    """
    out: list[InboundComment] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            if change.get("field") not in _COMMENT_FIELDS:
                continue
            value = change.get("value") or {}
            if change.get("field") == "feed" and value.get("item") != "comment":
                continue
            verb = str(value.get("verb") or "add").lower()
            comment_id = str(
                value.get("comment_id") or value.get("id") or ""
            ).strip()
            if not comment_id:
                continue
            body = value.get("message") if value.get("message") is not None else value.get("text")
            if verb == "remove":
                body = None
            author = value.get("from") or {}
            commented_at = _meta_timestamp(value.get("created_time") or value.get("timestamp"))
            out.append(
                InboundComment(
                    platform_comment_id=comment_id,
                    post_id=str(
                        value.get("post_id")
                        or (value.get("media") or {}).get("id")
                        or ""
                    )
                    or None,
                    parent_comment_id=str(value.get("parent_id") or "") or None,
                    author_ref=str(author.get("id") or "") or None,
                    author_name=author.get("name") or author.get("username"),
                    body=(str(body).strip() or None) if body is not None else None,
                    permalink=value.get("permalink_url") or value.get("permalink"),
                    like_count=int(value.get("like_count") or 0),
                    commented_at=commented_at,
                    verb=verb,
                    raw=value,
                )
            )
    return out


def _meta_timestamp(raw: Any) -> datetime | None:
    """Meta's two timestamp shapes: epoch seconds (page) and ISO (Instagram)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@dataclass
class ProviderCredentials:
    """Per-tenant provider credentials (from integrations.credentials)."""

    config: dict[str, Any]

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.config.get(key, default)


class ChannelAdapter(Protocol):
    """Every channel implements this. The core depends on this protocol only."""

    name: str

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        """Webhook verification handshake; return challenge or None."""
        ...

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        """True when the webhook is authentic. Reject otherwise."""
        ...

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        """Normalize a webhook payload into 0..n inbound messages."""
        ...

    def parse_status_updates(self, payload: dict) -> list[StatusUpdate]:
        """Delivery receipts, if the channel provides them (default: none)."""
        return []

    def resolve_tenant_key(self, payload: dict) -> str | None:
        """Extract the key that maps the webhook to a tenant
        (phone_number_id / bot id / public key) — looked up in integrations."""
        ...

    async def send(self, credentials: ProviderCredentials, message: OutboundMessage) -> str:
        """Deliver an outbound message; return the provider message id."""
        ...
