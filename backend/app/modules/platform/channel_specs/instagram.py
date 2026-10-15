"""Instagram Messaging — connection spec."""

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


class InstagramConnectionSpec(ConnectionSpec):
    name = "instagram"
    display_name = "انستجرام"
    description = "ربط حساب انستجرام التجاري لاستقبال الرسائل المباشرة"
    credential_fields = [
        FieldSpec(
            key="api_key",
            label="توكن الحساب (Access Token)",
            secret=True,
            placeholder="EAAG...",
        ),
    ]
    config_fields = [
        FieldSpec(key="account_id", label="Instagram Account ID", placeholder="17841400000000000"),
    ]
    identity_field = "account_id"
    setup_notes = (
        "من Meta Developer Console: اشترك تطبيقك في حساب انستجرام التجاري مع "
        "صلاحية instagram_manage_messages، ثم استخدم Webhook URL: /webhooks/instagram"
    )

    async def verify(
        self,
        credentials: dict[str, Any],
        config: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> VerifiedChannel:
        account_id = numeric_id(config, "account_id")
        token = required_text(credentials, "api_key")
        owns_client = client is None
        http = client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
        )
        try:
            data = await graph_get(
                http,
                provider_label="Instagram",
                url=f"{GRAPH_BASE}/{account_id}",
                token=token,
                params={"fields": "id,username"},
            )
        finally:
            if owns_client:
                await http.aclose()
        identity = str(data.get("id") or "")
        if identity != account_id:
            raise ValidationError("The Instagram account ID does not match the token.")
        return VerifiedChannel(
            {"account_id": identity},
            str(data.get("username") or "") or None,
        )


instagram_connection_spec = InstagramConnectionSpec()
