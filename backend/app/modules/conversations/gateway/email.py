"""Spec §26 / §175 Phase 3 — Email channel adapter.

Inbound: ESP webhook → signature → parse → canonical InboundMessage list.
Outbound: OutboundMessage → the ESP's REST API.

The core never knows it is talking to an email provider — only the
ChannelAdapter interface. This adapter conforms to the SAME protocol as the
other five channels: ``parse_inbound`` is synchronous and returns a LIST (the
generic dispatcher and the WebhookWorker iterate it), ``send`` returns the
provider message id as a ``str``, and the auth surface is ``verify_request`` /
``check_signature`` — the per-instance ``verify_webhook`` variant that used to
live here was dead code keyed on constructor secrets that were never supplied,
so it verified nothing; it is gone.

Tenant routing note: ``resolve_tenant_key`` answers the recipient address, but
``public.resolve_channel_tenant`` has no ``email`` branch yet, so an email
delivery resolves to NO tenant and is acknowledged without ingestion — exactly
like any other unattributed delivery. Email is therefore also absent from the
generic dispatcher's ``_WEBHOOK_CHANNELS`` (like webchat): the signature
surface below is complete and fail-closed, but nothing routes here until the
SQL lookup learns the channel.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

from app.core.circuit_breaker import PROVIDER_EMAIL, get_breaker
from app.core.config import get_settings
from app.core.errors import ExternalProviderError
from app.modules.conversations.gateway.base import (
    ChannelAdapter,
    InboundMessage,
    OutboundMessage,
    ProviderCredentials,
    parse_provider_body,
)

logger = logging.getLogger(__name__)


class EmailAdapter(ChannelAdapter):
    """Email channel adapter — supports SendGrid/Mailgun-style webhooks.

    Inbound: receives ESP webhook events, verifies the provider signature and
    normalizes to the canonical InboundMessage list. Outbound: sends via the
    ESP's REST API through the process-wide ``provider.email`` breaker.
    """

    # ``name`` is what the gateway registry keys on (get_adapter(channel));
    # ``channel`` is the value stamped on the normalized message. The protocol
    # requires ``name``, and its absence is why this adapter was never
    # registered — see tests/test_no_dead_modules.py.
    name = "email"
    channel = "email"

    def __init__(self, *, provider: str = "sendgrid"):
        self._provider = provider

    # ---------- webhook auth (same surface as every other adapter) ----------

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        """ESP inbound-parse webhooks have no GET subscription handshake."""
        return None

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        """Verify the ESP webhook signature — fail CLOSED without a secret.

        An unconfigured ``email_webhook_secret`` must reject ALL traffic, not
        accept it: the secret is the only thing standing between the internet
        and a pre-auth message injection. Both comparisons run on BYTES via
        ``hmac.compare_digest`` — a str compare raises TypeError on non-ASCII
        input, which would turn a hostile header into a 500.
        """
        secret = get_settings().email_webhook_secret
        if not secret:
            return False
        if self._provider == "sendgrid":
            # SendGrid's signed inbound-parse webhooks carry the shared secret
            # as the verification payload of the Authorization header.
            provided = headers.get("authorization", "")
            prefix = "Bearer "
            if not provided.startswith(prefix):
                return False
            return hmac.compare_digest(
                provided[len(prefix) :].encode(), secret.encode()
            )
        if self._provider == "mailgun":
            # Mailgun-style: HMAC-SHA256 over the raw body, hex-encoded in a
            # signature header. Compared WITHOUT any prefix, byte-wise.
            signature = headers.get("x-mailgun-signature", "")
            expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(signature.encode(), expected.encode())
        # An unknown ESP has no verification scheme we can vouch for.
        return False

    # ---------- tenant resolution ----------

    def resolve_tenant_key(self, payload: dict) -> str | None:
        """The recipient address is the routing key an email integration
        would be matched on (no ``email`` branch exists in
        ``resolve_channel_tenant`` yet — see the module docstring)."""
        recipient = payload.get("to") or payload.get("recipient")
        return str(recipient) if recipient else None

    # ---------- normalization ----------

    def parse_inbound(self, payload: dict) -> list[InboundMessage]:
        """Parse an ESP webhook payload into 0..1 canonical messages.

        Synchronous and list-shaped like every other adapter: the dispatcher
        and the WebhookWorker iterate the result, so returning ``None`` (the
        old shape) or awaiting (the old signature) crashed the hot path.
        """
        if self._provider == "sendgrid":
            return self._parse_sendgrid(payload)
        if self._provider == "mailgun":
            return self._parse_mailgun(payload)
        raise ExternalProviderError(f"unknown email provider: {self._provider}")

    def _parse_sendgrid(self, raw: dict) -> list[InboundMessage]:
        """Parse a SendGrid inbound parse webhook."""
        from_addr = str(raw.get("from", ""))
        if not from_addr:
            return []
        body = raw.get("text", raw.get("html", ""))
        display_name = from_addr.split("<")[0].strip() if "<" in from_addr else from_addr
        return [
            InboundMessage(
                channel=self.name,
                channel_message_id=raw.get("messageId", raw.get("message_id")),
                customer_ref=from_addr,
                customer_name=display_name,
                body=body,
                content_type="text",
                raw=raw,
                conversation_ref=str(raw.get("to", "")) or None,
            )
        ]

    def _parse_mailgun(self, raw: dict) -> list[InboundMessage]:
        """Parse a Mailgun webhook payload."""
        from_addr = raw.get("sender", raw.get("from", ""))
        if not from_addr:
            return []
        body = raw.get("body-plain", raw.get("body-html", ""))
        return [
            InboundMessage(
                channel=self.name,
                channel_message_id=raw.get("Message-Id", raw.get("messageId")),
                customer_ref=str(from_addr),
                customer_name=str(from_addr),
                body=body,
                content_type="text",
                raw=raw,
                conversation_ref=str(raw.get("recipient", raw.get("to", ""))) or None,
            )
        ]

    # ---------- outbound ----------

    async def send(
        self,
        credentials: ProviderCredentials,
        message: OutboundMessage,
        _client: httpx.AsyncClient | None = None,
    ) -> str:
        """Send an outbound email via the ESP and return the provider id.

        _client is an injection point for tests (MockTransport). The argument
        order matches the ChannelAdapter protocol (credentials first); it used to
        be (message, credentials), which meant the outbound worker — the only
        caller — passed them backwards. The return is the provider message id
        (the ``X-Message-Id`` response header) as a plain ``str``, like every
        other adapter — not a StatusUpdate, which is a RECEIPT shape and is
        produced by ``parse_status_updates``, not by a send.
        """
        api_key = credentials.get("api_key")
        if not api_key:
            raise ExternalProviderError("email integration missing api_key")
        # The sending address is integration config, not server config: it
        # belongs to the tenant's ESP account, so it rides the credentials.
        from_email = credentials.get("from_email") or "noreply@example.com"
        url = self._get_send_url(from_email)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "personalizations": [
                {"to": [{"email": message.customer_ref}]}
            ],
            "from": {"email": from_email},
            "subject": message.meta.get("subject", "Message"),
            "content": [
                {"type": "text/plain", "value": message.body or ""},
            ],
        }

        async def _post() -> str:
            """Send and extract the provider id — entirely inside the breaker.

            The status check must live inside ``breaker.call()``: a rejecting ESP
            is a provider FAILURE, and raising it outside would record a SUCCESS
            and never open the breaker. A 2xx without a message id is also a
            failure — a send we cannot reference later cannot be reconciled.
            """
            if _client is not None:
                resp = await _client.post(url, headers=headers, json=payload)
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code not in (200, 201, 202):
                raise ExternalProviderError(
                    f"email send failed: HTTP {resp.status_code} — {resp.text[:200]}"
                )
            # SendGrid answers 202 with an EMPTY body — that is a success; an
            # intermediary answers 200 with an HTML error page — that is not.
            # Only decode when there is something to decode, and require an
            # object when there is; both run INSIDE the breaker so a broken
            # ESP counts against it instead of recording a phantom SUCCESS.
            if resp.content.strip():
                parse_provider_body(resp, "email send")
            message_id = resp.headers.get("X-Message-Id", "")
            if not message_id:
                raise ExternalProviderError(
                    f"email send: no X-Message-Id header (HTTP {resp.status_code})"
                )
            return str(message_id)

        # §47/G-13: the outbound call goes through the process-wide
        # `provider.email` breaker, so a dead ESP is backed off instead of
        # hammered on every send and worker retry. An OPEN breaker raises
        # CircuitOpenError; deciding whether that retries or fails is the
        # caller's job, not the adapter's.
        return await get_breaker(PROVIDER_EMAIL).call(_post)

    def _get_send_url(self, from_email: str | None) -> str:
        if self._provider == "sendgrid":
            return "https://api.sendgrid.com/v3/mail/send"
        if self._provider == "mailgun":
            # The Mailgun API URL is per sending domain, taken from the
            # configured FROM address — an address without a domain is a
            # configuration failure, not a crash.
            domain = (from_email or "").rpartition("@")[2]
            if not domain:
                raise ExternalProviderError(
                    "email integration missing a from_email with a domain"
                )
            return f"https://api.mailgun.net/v3/{domain}/messages"
        raise ExternalProviderError(f"unknown email provider: {self._provider}")


email_adapter = EmailAdapter()
