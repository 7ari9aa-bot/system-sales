"""Channel Gateway framework — the boundary between platforms and the core.

Adapters own every platform detail (verification, parsing, media, rate limits,
sending quirks). After normalization, the core never knows which channel a
message came from.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
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
