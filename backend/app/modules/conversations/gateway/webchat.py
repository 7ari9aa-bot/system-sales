"""Webchat channel — first-party, no external dependencies.

Tenant resolution: integrations row (provider="webchat", kind="channel")
whose config.public_key matches the widget key.
Customer identity: a SERVER-ISSUED visitor session key (S2) — the widget never
chooses its own key, it presents the signed `session_token` it was given.
"""

from __future__ import annotations

import uuid

import httpx

from app.modules.conversations.gateway.base import (
    ChannelAdapter,
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
)


class WebchatAdapter(ChannelAdapter):
    name = "webchat"

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        return None  # no handshake needed

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        """Always False — webchat has no provider signature to verify.

        The channel is deliberately absent from `_WEBHOOK_CHANNELS`, so the
        generic /webhooks/{channel} dispatcher never routes here. Returning
        True (the previous behaviour) meant that any future re-registration
        would silently accept unauthenticated bodies carrying an
        attacker-chosen `public_key`. Webchat traffic belongs on the public
        route, which validates the widget key from the PATH plus a signed
        visitor session.
        """
        return False

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        # session_key is injected by the router from a verified visitor token.
        session_key = str(payload.get("session_key", "")).strip()
        body = str(payload.get("body", "")).strip()
        if not session_key or not body:
            return []
        return [
            InboundMessage(
                channel=self.name,
                channel_message_id=payload.get("client_message_id"),
                customer_ref=session_key,
                customer_name=payload.get("visitor_name"),
                body=body,
                raw=payload,
            )
        ]

    def resolve_tenant_key(self, payload: dict) -> str | None:
        # Only reachable through the generic webhook dispatcher, which excludes
        # webchat; the public route takes the key from the URL path instead.
        return payload.get("public_key")

    async def send(
        self,
        credentials: ProviderCredentials,
        message: OutboundMessage,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        # Delivery for webchat is pull-based (the widget polls / fetches via
        # SSE), so "sending" just means persisting — the message row is the
        # transport. ``_client`` is accepted (and ignored) so all six adapters
        # share ONE send signature; webchat opens no HTTP client.
        return f"webchat-{uuid.uuid4()}"


webchat_adapter = WebchatAdapter()
