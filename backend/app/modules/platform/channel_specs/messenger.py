"""Facebook Messenger — connection spec.

Messenger connects a PAGE too: the token is a page access token and `GET /me`
resolves it to the page. Identity lands in `config.account_id` — the same key
the messenger webhook adapter and `resolve_channel_tenant` match on.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import ValidationError
from app.modules.platform.channel_specs.base import (
    _NUMERIC_ID,
    GRAPH_BASE,
    ConnectionSpec,
    FieldSpec,
    VerifiedChannel,
    graph_get,
    required_text,
)


class MessengerConnectionSpec(ConnectionSpec):
    name = "messenger"
    display_name = "ماسنجر"
    description = "ربط رسائل ماسنجر عبر صفحة فيسبوك"
    credential_fields = [
        FieldSpec(
            key="api_key",
            label="توكن الصفحة (Page Access Token)",
            secret=True,
            placeholder="EAAG...",
        ),
    ]
    config_fields = []  # the page id comes back from /me — nothing to paste
    identity_field = "account_id"
    setup_notes = (
        "من Meta Developer Console: اشترك تطبيقك في صفحتك مع صلاحية pages_messaging، "
        "ثم استخدم Webhook URL: /webhooks/messenger"
    )

    async def verify(
        self,
        credentials: dict[str, Any],
        config: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> VerifiedChannel:
        token = required_text(credentials, "api_key")
        owns_client = client is None
        http = client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
        )
        try:
            data = await graph_get(
                http,
                provider_label="Messenger",
                url=f"{GRAPH_BASE}/me",
                token=token,
                params={"fields": "id,name"},
            )
        finally:
            if owns_client:
                await http.aclose()
        identity = str(data.get("id") or "")
        if not _NUMERIC_ID.fullmatch(identity):
            raise ValidationError(
                "This token does not identify a Messenger page or lacks page permissions."
            )
        return VerifiedChannel(
            {"account_id": identity},
            str(data.get("name") or "") or None,
        )


messenger_connection_spec = MessengerConnectionSpec()
