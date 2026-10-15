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

from __future__ import annotations

from app.modules.conversations.gateway.messenger import MessengerAdapter


class FacebookPageAdapter(MessengerAdapter):
    """Facebook Page messaging — Messenger's protocol under the page's name."""

    name = "facebook"
    channel = "facebook"


facebook_adapter = FacebookPageAdapter()
