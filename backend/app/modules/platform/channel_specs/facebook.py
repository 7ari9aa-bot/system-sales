"""Facebook Page — connection spec (NEW channel).

A Facebook connection is a PAGE connection: the owner pastes the page id and a
page access token (with pages_messaging). Messaging itself rides the same Meta
webhook plumbing as Messenger — the `FacebookPageAdapter` (gateway/facebook.py)
reuses it verbatim, and `resolve_channel_tenant` matches the page id stored in
`config.account_id`, so no migration is needed.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import ValidationError
from app.modules.platform.channel_specs.base import (
    GRAPH_BASE,
    ConnectionSpec,
    FieldSpec,
    VerifiedChannel,
    graph_get,
    numeric_id,
    required_text,
)


class FacebookConnectionSpec(ConnectionSpec):
    name = "facebook"
    display_name = "فيسبوك"
    description = "ربط صفحة فيسبوك لاستقبال رسائل العملاء والرد عليها"
    credential_fields = [
        FieldSpec(
            key="page_access_token",
            label="توكن الصفحة (Page Access Token)",
            secret=True,
            placeholder="EAAG...",
        ),
    ]
    config_fields = [
        FieldSpec(key="page_id", label="Page ID", placeholder="1234567890"),
    ]
    identity_field = "account_id"
    setup_notes = (
        "من Meta Developer Console: اشترك تطبيقك في صفحتك (Page subscribe) مع "
        "صلاحية pages_messaging، ثم استخدم Webhook URL: /webhooks/facebook"
    )

    async def verify(
        self,
        credentials: dict[str, Any],
        config: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> VerifiedChannel:
        page_id = numeric_id(config, "page_id")
        token = required_text(credentials, "page_access_token")
        owns_client = client is None
        http = client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
        )
        try:
            data = await graph_get(
                http,
                provider_label="Facebook",
                url=f"{GRAPH_BASE}/{page_id}",
                token=token,
                params={"fields": "id,name"},
            )
        finally:
            if owns_client:
                await http.aclose()
        identity = str(data.get("id") or "")
        if identity != page_id:
            raise ValidationError("The Facebook page ID does not match the token.")
        return VerifiedChannel(
            {"account_id": identity},
            str(data.get("name") or "") or None,
        )


facebook_connection_spec = FacebookConnectionSpec()


# Messaging parity note: page messages ride the SAME Meta webhook plumbing as
# Messenger — the conversations gateway exposes `FacebookPageAdapter`
# (gateway/facebook.py) with name="facebook", so /webhooks/facebook and
# `resolve_channel_tenant('facebook', page_id)` work with zero database
# changes: the tenant-resolution SQL function is identity-generic (matches
# config->>'account_id' for any channel-kind provider).
