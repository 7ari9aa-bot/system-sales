"""WhatsApp Business App Coexistence — connection verification.

The token and phone number id originate from Meta Embedded Signup. Verification reads the
number back from Graph, checks that the id belongs to the token, and fails closed unless
Meta confirms the same number is active in both WhatsApp Business app and Cloud API.
No Cloud API-only number can be connected through this spec.
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

#: Everything one Graph GET on a phone number id must return: the identity we store, the label the
#: settings screen shows, and Meta's own coexistence evidence.
NUMBER_FIELDS = "id,display_phone_number,verified_name,is_on_biz_app,platform_type"

#: `platform_type` a coexistence number reports. Together with `is_on_biz_app: true` this is the
#: documented proof that the app and the API are live on the same number.
COEXISTENCE_PLATFORM = "CLOUD_API"


def number_platform_facts(payload: dict[str, Any]) -> dict[str, Any]:
    """The coexistence facts in a phone-number payload, typed, with unknown left as None.

    A missing field stays ``None`` on purpose: "Meta did not say" is not "no", and a caller that
    turns it into ``False`` would connect a Business App number as if it were Cloud-API-only.
    """
    raw_on_app = payload.get("is_on_biz_app")
    raw_platform = payload.get("platform_type")
    platform = str(raw_platform).strip().upper() if raw_platform else None
    return {
        "is_on_biz_app": raw_on_app if isinstance(raw_on_app, bool) else None,
        "platform_type": platform or None,
    }


def coexistence_evidence(facts: dict[str, Any]) -> bool:
    """True only on Meta's documented pair: on the app AND on the Cloud API."""
    return facts.get("is_on_biz_app") is True and facts.get("platform_type") == COEXISTENCE_PLATFORM


class WhatsAppConnectionSpec(ConnectionSpec):
    name = "whatsapp"
    display_name = "واتساب"
    description = "ربط رقم WhatsApp Business الحالي مع FIHRIST عبر Coexistence"
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
        "من Meta Developer Console: على كائن WhatsApp Business Account سجّل Webhook URL "
        "التالي مع Verify Token من إعدادات الخادم: /webhooks/whatsapp (حقل messages)"
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
                params={"fields": NUMBER_FIELDS},
            )
        finally:
            if owns_client:
                await http.aclose()
        identity = str(data.get("id") or "")
        if identity != phone_number_id:
            # The token belongs to a DIFFERENT number: fail rather than store
            # credentials that can never send from the pasted id.
            raise ValidationError("The WhatsApp phone number ID does not match the token.")
        identity_config: dict[str, str] = {"phone_number_id": identity}
        facts = number_platform_facts(data)
        if not coexistence_evidence(facts):
            raise ValidationError(
                "FIHRIST connects existing WhatsApp Business app numbers only. "
                "Meta did not verify that this number is active in both the Business app "
                "and Cloud API, so the connection was refused."
            )
        # Recorded as text because the config column is non-secret JSON of plain strings. Only
        # what Meta actually answered is written — an absent field stays absent.
        if facts["is_on_biz_app"] is not None:
            identity_config["is_on_biz_app"] = "true" if facts["is_on_biz_app"] else "false"
        if facts["platform_type"]:
            identity_config["platform_type"] = str(facts["platform_type"])
        return VerifiedChannel(
            identity_config,
            str(data.get("verified_name") or data.get("display_phone_number") or "") or None,
        )


whatsapp_connection_spec = WhatsAppConnectionSpec()
