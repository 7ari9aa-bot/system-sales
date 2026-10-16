"""WhatsApp Embedded Signup — the click-and-connect flow (spec: channels).

The owner presses the WhatsApp button on the channels page; Meta's own popup
opens; the store owner logs in with THEIR Meta account, creates/selects a
WhatsApp Business Account and a phone number; Meta hands this server a
one-time `code` plus the chosen `waba_id` / `phone_number_id`. We exchange the
code for a business token, subscribe our app to the WABA (so inbound messages
start flowing), verify the number against Graph, and store the integration.

Why this is a SEPARATE flow from meta_oauth.py: Embedded Signup is a JS-SDK
POPUP (not a redirect), it exchanges the code WITHOUT a redirect_uri, and its
product is a WABA + phone number rather than a Facebook Page. Same app, same
tenant, different product — so it gets its own file.

Meta console prerequisites (docs/META_SETUP.md §WhatsApp):
  * Facebook Login for Business enabled, with a configuration created from the
    "WhatsApp Embedded Signup Configuration" template → META_WHATSAPP_CONFIG_ID
  * the dashboard origin listed under Allowed Domains for the JavaScript SDK
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.errors import ExternalProviderError, ValidationError
from app.core.secrets import encrypt_credentials_dict
from app.modules.identity.deps import DbSession, TenantContext, require_permission

logger = logging.getLogger(__name__)

whatsapp_signup_router = APIRouter()

#: Same pinned Graph release as the OAuth flow — one version for both dialogs
#: and calls, so the app's configuration and our requests never disagree.
_GRAPH_VERSION = "v26.0"
_GRAPH = f"https://graph.facebook.com/{_GRAPH_VERSION}"


class WhatsAppSignupStartOut(BaseModel):
    """Public values the browser needs to open Meta's popup — nothing secret."""

    app_id: str
    config_id: str
    graph_version: str


class WhatsAppSignupCompleteOut(BaseModel):
    """The connected channel, typed — the AI surface refuses free-form bodies
    (the open-body schema is the permission to drop any field)."""

    id: str
    provider: Literal["whatsapp"]
    status: str
    display_name: str | None = None
    phone_number_id: str
    waba_id: str


class WhatsAppSignupCompleteBody(BaseModel):
    """What the JS SDK popup hands back, plus the two ids from its session."""

    code: str = Field(min_length=8, max_length=4096)
    waba_id: str = Field(min_length=3, max_length=64)
    phone_number_id: str = Field(min_length=3, max_length=64)


def _whatsapp_config() -> tuple[str, str, str]:
    """(app_id, app_secret, embedded-signup config id) or a loud failure."""
    s = get_settings()
    app_id = s.meta_app_id.strip()
    app_secret = s.meta_app_secret.strip()
    config_id = s.meta_whatsapp_config_id.strip()
    if not (app_id and app_secret and config_id):
        raise ValidationError(
            "WhatsApp Embedded Signup is not configured on this server — set "
            "META_APP_ID, META_APP_SECRET and META_WHATSAPP_CONFIG_ID (create the "
            "configuration from Meta's 'WhatsApp Embedded Signup Configuration' "
            "template; see docs/META_SETUP.md)."
        )
    return app_id, app_secret, config_id


@whatsapp_signup_router.get(
    "/integrations/whatsapp/embedded-signup/start",
    response_model=WhatsAppSignupStartOut,
)
async def whatsapp_signup_start(
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Hand the browser the PUBLIC popup parameters (app id + config id).

    Only public values leave here: the popup is Meta's own page and the
    consent happens with the store owner's Meta account. The app SECRET stays
    on the server and is used only at completion time.
    """
    app_id, _secret, config_id = _whatsapp_config()
    return WhatsAppSignupStartOut(
        app_id=app_id, config_id=config_id, graph_version=_GRAPH_VERSION
    )


async def _exchange_code_for_token(
    http: httpx.AsyncClient, *, app_id: str, app_secret: str, code: str
) -> str:
    """code → business token. Embedded Signup sends NO redirect_uri."""
    try:
        response = await http.get(
            f"{_GRAPH}/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "code": code,
            },
        )
    except httpx.RequestError:
        raise ExternalProviderError(
            "Could not reach Meta to complete the WhatsApp connection. Try again."
        ) from None
    if response.status_code >= 500 or response.status_code == 429:
        raise ExternalProviderError(
            "Meta is temporarily unavailable. Try again.", retryable=True
        )
    try:
        payload = response.json()
    except ValueError:
        raise ExternalProviderError("Meta returned an invalid token response.") from None
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValidationError(
            "Meta rejected the WhatsApp authorization code. Press connect again."
        )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValidationError(
            "Meta returned no access token for this WhatsApp signup. Press connect again."
        )
    return token


async def _phone_display_name(
    http: httpx.AsyncClient, *, phone_number_id: str, token: str
) -> str | None:
    """The verified business name / display number, for the settings UI."""
    response = await http.get(
        f"{_GRAPH}/{phone_number_id}",
        params={"fields": "display_phone_number,verified_name"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.is_error:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return (
        str(payload.get("verified_name") or payload.get("display_phone_number") or "")
        or None
    )


async def _subscribe_app_to_waba(http: httpx.AsyncClient, *, waba_id: str, token: str) -> None:
    """Subscribe our app to the WABA — without this NO inbound message arrives.

    A silent failure here would connect a number that can never receive
    anything, so it raises and the caller reports it instead of storing a
    half-working integration.
    """
    try:
        response = await http.post(
            f"{_GRAPH}/{waba_id}/subscribed_apps",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.RequestError:
        raise ExternalProviderError(
            "Could not subscribe the WhatsApp account to this app. Try again."
        ) from None
    if response.is_error:
        raise ExternalProviderError(
            "Meta refused the WhatsApp webhook subscription — check the app's "
            "whatsapp_business_messaging permission, then retry.",
            retryable=False,
        )


@whatsapp_signup_router.post(
    "/integrations/whatsapp/embedded-signup/complete",
    response_model=WhatsAppSignupCompleteOut,
    status_code=201,
)
async def whatsapp_signup_complete(
    body: WhatsAppSignupCompleteBody,
    session: DbSession,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Finish the popup: exchange → subscribe → verify → store the channel."""
    from app.modules.billing.service import EntitlementService
    from app.modules.customers.router import (
        _activate_verified_channel,
        _verification_metadata,
    )
    from app.modules.platform.integration_verifier import verify_channel_credentials
    from app.modules.platform.models import Integration

    app_id, app_secret, _config_id = _whatsapp_config()
    tenant_id = ctx.tenant_id

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False
    ) as http:
        token = await _exchange_code_for_token(
            http, app_id=app_id, app_secret=app_secret, code=body.code
        )
        await _subscribe_app_to_waba(http, waba_id=body.waba_id, token=token)
        display_name = await _phone_display_name(
            http, phone_number_id=body.phone_number_id, token=token
        )
        # The SAME verification the manual connect runs: the token must own
        # the phone number id it claims, or nothing is stored.
        verified = await verify_channel_credentials(
            "whatsapp",
            {"access_token": token},
            {"phone_number_id": body.phone_number_id},
            client=http,
        )

    existing = (
        await session.execute(
            _select_integration(tenant_id, "whatsapp")
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status == "disabled":
        raise ValidationError("This channel was permanently disabled and cannot be reconnected.")
    if existing is None:
        await EntitlementService.ensure_channel_allowed(session, tenant_id, "whatsapp")

    verified_at = datetime.now(UTC).isoformat()
    integration_config = {
        **verified.identity_config,
        # The WABA id is not used for tenant resolution (phone_number_id is),
        # but it is what future template/quality calls address.
        "waba_id": body.waba_id,
        "_connection": _verification_metadata(
            verified_at=verified_at, display_name=display_name or verified.display_name
        ),
    }
    encrypted = encrypt_credentials_dict({"access_token": token})

    if existing is None:
        integration = Integration(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            provider="whatsapp",
            kind="channel",
            config=integration_config,
            credentials=encrypted,
            status="pending",
        )
        _activate_verified_channel(integration)
        session.add(integration)
    else:
        _activate_verified_channel(existing)
        existing.config = integration_config
        existing.credentials = encrypted
        integration = existing
    await session.flush()

    logger.info(
        "whatsapp.embedded_signup_connected tenant=%s phone_number_id=%s waba=%s",
        tenant_id,
        body.phone_number_id,
        body.waba_id,
    )
    return {
        "id": str(integration.id),
        "provider": "whatsapp",
        "status": integration.status,
        "display_name": display_name or verified.display_name,
        "phone_number_id": body.phone_number_id,
        "waba_id": body.waba_id,
    }


def _select_integration(tenant_id, provider: str):
    """The tenant's channel row for this provider (one per provider)."""
    from sqlalchemy import select

    from app.modules.platform.models import Integration

    return select(Integration).where(
        Integration.tenant_id == tenant_id,
        Integration.provider == provider,
        Integration.kind == "channel",
    )
