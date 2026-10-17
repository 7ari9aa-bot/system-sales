"""Spec §26 family — Facebook PAGE channel adapter (NEW).

A Facebook connection and a Messenger connection speak the IDENTICAL Meta
Graph protocol (page token, X-Hub-Signature-256, /me/messages): the only
difference is the integration `provider` value the owner connected through.
This adapter therefore REUSES the Messenger parsing/sending verbatim and
changes only the registry key, so:

* `/webhooks/facebook` (GET verify + POST) is served by the generic
  /webhooks/{channel} dispatcher the moment this adapter is registered;
* `resolve_channel_tenant('facebook', page_id)` matches the page id stored in
  `config.account_id` by the platform connection spec — the SQL function is
  identity-generic, so no migration is needed;
* sending goes through the same `provider.messenger` breaker (same endpoint).
"""

import hashlib
import hmac

from app.core.config import get_settings
from app.modules.conversations.gateway.messenger import MessengerAdapter


class FacebookPageAdapter(MessengerAdapter):
    """Facebook Page messaging — Messenger's protocol under the page's name."""

    name = "facebook"
    channel = "facebook"

    def verify_request(self, query_params: dict[str, str]) -> str | None:
        """Meta webhook handshake — supports messenger_verify_token or meta app token."""
        settings = get_settings()
        expected = settings.messenger_verify_token or getattr(settings, "whatsapp_verify_token", "")
        if not expected:
            return None
        if (
            query_params.get("hub.mode") == "subscribe"
            and query_params.get("hub.verify_token") == expected
        ):
            return query_params.get("hub.challenge", "")
        return None

    def check_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        """X-Hub-Signature-256 — uses messenger_app_secret or meta_app_secret."""
        settings = get_settings()
        secret = settings.messenger_app_secret or getattr(settings, "meta_app_secret", "")
        if not secret:
            return False
        signature = headers.get("x-hub-signature-256", "")
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature[7:].encode(), expected.encode())


facebook_adapter = FacebookPageAdapter()
