"""WhatsApp Cloud API — connection spec.

The owner pastes a permanent Cloud API token + the phone number id. The live
verification reads the number back from Graph and REJECTS when the id does not
match the token, so a copy/paste slip can never connect somebody else's number.
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


class WhatsAppConnectionSpec(ConnectionSpec):
    name = "whatsapp"
    display_name = "واتساب"
    description = "ربط رقم واتساب للأعمال عبر WhatsApp Cloud API"
    credential_fields = [
        FieldSpec(
            key="access_token",
            label="التوكن الدائم (Permanent Access Token)",
            secret=True,
            placeholder="EAAG...",
        ),
    ]
    config_fields = [
        FieldSpec(key="phone_number_id", label="Phone Number ID", placeholder="1234567890"),
    ]
    identity_field = "phone_number_id"
    setup_notes = (
        "من Meta Developer Console: أضف الرقم إلى تطبيقك، ثم استخدم Webhook URL "
        "التالي مع Verify Token من إعدادات الخادم: /webhooks/whatsapp"
    )

    async def verify(
        self,
        credentials: dict[str, Any],
        config: dict[str, Any],
        *,
        client: httpx.AsyncClient | None = None,
    ) -> VerifiedChannel:
        phone_number_id = numeric_id(config, "phone_number_id")
        token = required_text(credentials, "access_token")
        owns_client = client is None
        http = client or httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False
        )
        try:
            data = await graph_get(
                http,
                provider_label="WhatsApp",
                url=f"{GRAPH_BASE}/{phone_number_id}",
                token=token,
                params={"fields": "id,display_phone_number,verified_name"},
            )
        finally:
            if owns_client:
                await http.aclose()
        identity = str(data.get("id") or "")
        if identity != phone_number_id:
            # The token belongs to a DIFFERENT number: fail rather than store
            # credentials that can never send from the pasted id.
            raise ValidationError("The WhatsApp phone number ID does not match the token.")
        return VerifiedChannel(
            {"phone_number_id": identity},
            str(data.get("verified_name") or data.get("display_phone_number") or "") or None,
        )


whatsapp_connection_spec = WhatsAppConnectionSpec()
