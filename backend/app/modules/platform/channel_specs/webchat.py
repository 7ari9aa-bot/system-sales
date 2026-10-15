"""Website chat (webchat) — connection spec.

No provider, no secrets to verify: connecting mints the tenant's public key
that the embeddable web widget signs its sessions with.
"""

from __future__ import annotations

from typing import Any

from app.modules.platform.channel_specs.base import (
    ConnectionSpec,
    FieldSpec,
    VerifiedChannel,
    or_generate_public_key,
)


class WebchatConnectionSpec(ConnectionSpec):
    name = "webchat"
    display_name = "شات الموقع"
    description = "نافذة محادثة مدمجة في موقعك — بدون أي مزوّد خارجي"
    credential_fields = []
    config_fields = [
        FieldSpec(key="public_key", label="المفتاح العام (Public Key)"),
    ]
    identity_field = "public_key"
    setup_notes = "انسخ المفتاح العام إلى كود الشات المدمج في موقعك."

    async def verify(
        self,
        credentials: dict[str, Any],
        config: dict[str, Any],
        *,
        client: Any = None,
    ) -> VerifiedChannel:
        return VerifiedChannel(
            {"public_key": or_generate_public_key(config)},
            "Website chat",
        )


webchat_connection_spec = WebchatConnectionSpec()
