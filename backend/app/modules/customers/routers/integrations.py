"""Platform routes — invitations, channel integrations, connect/verify/disconnect."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, ExternalProviderError, NotFoundError, ValidationError
from app.core.secrets import encrypt_credentials_dict
from app.modules.billing.service import EntitlementService
from app.modules.customers import meta_unsubscribe, schemas
from app.modules.customers.meta_scopes import missing_facebook_scopes, missing_instagram_scopes
from app.modules.customers.schemas import IntegrationBody
from app.modules.identity.models import Invitation, Role
from app.modules.platform.integration_verifier import (
    channel_field_allow_lists,
    configure_telegram_webhook,
    signed_webhook_providers,
    telegram_webhook_secret_configured,
    verify_channel_credentials,
)
from app.modules.platform.models import Integration, WebhookEvent
from app.modules.platform.service import AuditService, IntegrationCredentialsService

from ._deps import SettingsReadCtx, TenantContext, require_permission

platform_router = APIRouter(tags=["platform"])

# §145: pre-lifecycle status values and the canonical states the migration
# (f8a1c2d3e4b5) rewrites them to. The request body above still defaults to
# the legacy 'connected', so transition decisions must compare through this
# mapping — otherwise every re-registration of a legacy row would look like
# a jump from a state the lifecycle table does not name.
_LEGACY_STATUS_ALIASES = {"connected": "active", "error": "reauth_required"}
_CHANNEL_PROVIDERS = frozenset(
    {"whatsapp", "facebook", "instagram", "messenger", "telegram", "webchat"}
)
# The field allow-lists are DERIVED from the per-channel specs
# (platform.channel_specs) — the specs are the single source of truth, so a
# new channel needs no edit here. Drift is pinned by tests/test_channel_connections.py.
_CHANNEL_CREDENTIAL_FIELDS, _CHANNEL_CONFIG_FIELDS = channel_field_allow_lists()
_SIGNED_WEBHOOK_PROVIDERS = signed_webhook_providers()


def _last_webhook_at(integration: Integration) -> str | None:
    health = integration.webhook_health
    value = health.get("last_webhook_at") if isinstance(health, dict) else None
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else None


def _meta_page_webhook_configured(settings) -> bool:
    """Whether the Page webhook (Facebook and Messenger) can pass Meta's checks on this server."""
    secret = settings.messenger_app_secret or getattr(settings, "meta_app_secret", "")
    return bool(secret and settings.messenger_verify_token)


def _webhook_status(integration: Integration) -> str:
    if integration.provider == "webchat":
        return "ready"

    from app.core.config import get_settings

    settings = get_settings()
    public_api_configured = _telegram_webhook_base_url() is not None
    configured = {
        "whatsapp": public_api_configured
        and bool(settings.whatsapp_app_secret and settings.whatsapp_verify_token),
        # Facebook and Messenger share one adapter rule (gateway/messenger.py): the Meta app
        # secret signs the webhook, the Messenger verify token opens the handshake. The badge
        # must describe the webhook that actually answers, or it cries wolf on a working one.
        "messenger": public_api_configured and _meta_page_webhook_configured(settings),
        "facebook": public_api_configured and _meta_page_webhook_configured(settings),
        "instagram": public_api_configured
        and bool(settings.instagram_app_secret and settings.instagram_verify_token),
        "telegram": public_api_configured and telegram_webhook_secret_configured(),
    }.get(integration.provider, False)
    if not configured:
        return "server_setup_required"
    if integration.provider == "telegram":
        connection = (
            integration.config.get("_connection") if isinstance(integration.config, dict) else None
        )
        if not isinstance(connection, dict) or not connection.get("webhook_configured_at"):
            return "server_setup_required"
    return "receiving" if _last_webhook_at(integration) else "awaiting_first_event"


def _telegram_webhook_base_url() -> str | None:
    from app.core.config import get_settings

    base = get_settings().api_public_base_url.strip().rstrip("/")
    parsed = urlparse(base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None
    return base


def _telegram_webhook_url(public_key: str) -> str:
    base = _telegram_webhook_base_url()
    if base is None:
        raise ExternalProviderError(
            "Telegram webhook setup requires the server's canonical HTTPS API URL.",
            retryable=False,
        )
    route = f"{base}/api/v1/webhooks/telegram"
    return f"{route}?{urlencode({'tenant_key': public_key})}"


def _provider_webhook_url(provider: str) -> str | None:
    if provider not in _SIGNED_WEBHOOK_PROVIDERS:
        return None
    if provider == "telegram":
        return None
    base = _telegram_webhook_base_url()
    if base is None:
        return None
    return f"{base}/api/v1/webhooks/{provider}"


def _integration_output(integration: Integration) -> dict:
    config = integration.config if isinstance(integration.config, dict) else {}
    connection = config.get("_connection")
    if not isinstance(connection, dict):
        connection = {}
    verified_at = connection.get("verified_at")
    if not isinstance(verified_at, str):
        verified_at = None
    display_name = connection.get("display_name")
    if not isinstance(display_name, str):
        display_name = None
    public_key = (
        config.get("public_key")
        if integration.provider in {"webchat", "telegram"} and integration.kind == "channel"
        else None
    )
    webhook_url = (
        _telegram_webhook_url(public_key)
        if integration.provider == "telegram" and public_key and _telegram_webhook_base_url()
        else _provider_webhook_url(integration.provider)
    )
    return {
        "id": str(integration.id),
        "provider": integration.provider,
        "kind": integration.kind,
        "status": integration.status,
        "credentials_verified": bool(verified_at) and integration.status in {"active", "connected"},
        "display_name": display_name,
        "verified_at": verified_at,
        "webhook_status": _webhook_status(integration),
        "last_webhook_at": _last_webhook_at(integration),
        "webhook_url": webhook_url,
        "meta_cleanup": _meta_cleanup_state(integration),
        "public_key": public_key if integration.provider == "webchat" else None,
        # The permissions this connection lacks. Facebook: posting, comments, insights. Instagram:
        # messages, comments, publishing. A connection made before they were asked for lacks all
        # of them and must connect again.
        "missing_scopes": (
            missing_facebook_scopes(connection.get("granted_scopes"))
            if integration.provider == "facebook" and integration.kind == "channel"
            else missing_instagram_scopes(connection.get("granted_scopes"))
            if integration.provider == "instagram" and integration.kind == "channel"
            else []
        ),
    }


def _meta_cleanup_state(integration: Integration) -> dict | None:
    """What Meta last said when this channel's subscription was removed (no secrets in it)."""
    config = integration.config if isinstance(integration.config, dict) else {}
    cleanup = config.get("_meta_cleanup")
    return cleanup if isinstance(cleanup, dict) else None


def _activate_verified_channel(integration: Integration) -> None:
    """Apply the legal lifecycle path after provider verification succeeds."""
    current = _LEGACY_STATUS_ALIASES.get(integration.status, integration.status)
    if current == "active":
        integration.status = "active"
        return
    if current in {"pending", "reauth_required", "disconnected"}:
        Integration.validate_transition(current, "connecting")
        integration.status = "connecting"
        current = "connecting"
    if current != "active":
        Integration.validate_transition(current, "active")
    integration.status = "active"


def _verification_metadata(
    *, verified_at: str | None, display_name: str | None, failure: str | None = None
) -> dict:
    result = {"verified_at": verified_at, "display_name": display_name}
    if failure:
        result["last_failure"] = failure
    return result


@platform_router.get("/invitations", response_model=list[schemas.PlatformInvitation])
async def list_invitations(
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    rows = (
        await ctx.session.execute(
            select(Invitation, Role.code)
            .outerjoin(Role, Role.id == Invitation.role_id)
            .where(Invitation.tenant_id == ctx.tenant_id)
            .order_by(Invitation.created_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "id": str(invitation.id),
            "email": invitation.email,
            "role_code": role_code,
            "status": invitation.status,
        }
        for invitation, role_code in rows
    ]


@platform_router.delete(
    "/invitations/{invitation_id}",
    status_code=204,
)
async def revoke_invitation(
    invitation_id: UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    invitation = (
        await ctx.session.execute(
            select(Invitation).where(
                Invitation.id == invitation_id,
                Invitation.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise NotFoundError(f"invitation {invitation_id} not found")
    invitation.status = "revoked"
    return Response(status_code=204)


@platform_router.get("/integrations", response_model=list[schemas.IntegrationOut])
async def list_integrations(ctx: SettingsReadCtx):
    rows = (
        (
            await ctx.session.execute(
                select(Integration).where(Integration.tenant_id == ctx.tenant_id).limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [_integration_output(i) for i in rows]


async def audit_channel_connected(
    session,
    tenant_id,
    actor_user_id,
    integration,
    *,
    is_new: bool,
    extra: dict | None = None,
) -> None:
    """Write the `integration.connected` audit row for a channel that now works.

    Every way in (manual connect, WhatsApp Embedded Signup) redirects the same webhook traffic,
    so every way in leaves this row. Identity metadata only: never a token, a code or a PIN.
    """
    after = {"provider": integration.provider, "status": integration.status, "is_new": is_new}
    if extra:
        after.update(extra)
    await AuditService.write(
        session,
        tenant_id,
        actor_user_id,
        "integration.connected",
        "integration",
        str(integration.id),
        after=after,
    )


@platform_router.post(
    "/integrations/connect",
    status_code=201,
    response_model=schemas.IntegrationVerificationOut,
)
async def connect_integration(
    body: schemas.IntegrationConnectBody,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Verify credentials before persisting a channel as active."""
    provider = body.provider
    if provider == "whatsapp":
        # There must be ONE way to create a WhatsApp channel. Embedded Signup is that way: Meta
        # hands back the WABA and phone number id, the app gets subscribed to the WABA, the
        # onboarding mode is recorded (a Business App number is coexistence, not cloud_api) and the
        # contacts/history sync is requested. A token-paste here produced an Integration that looked
        # active while none of that had happened, so the number received nothing and never synced.
        raise ValidationError(
            "WhatsApp connects through Embedded Signup, not a pasted token. Finish the WhatsApp "
            "link from Settings → Channels so Meta records the coexistence mode and starts the "
            "contacts and history sync."
        )
    unexpected = set(body.credentials) - _CHANNEL_CREDENTIAL_FIELDS[provider]
    if unexpected:
        raise ValidationError("Unexpected credential fields for this provider.")
    unexpected_config = set(body.config) - _CHANNEL_CONFIG_FIELDS[provider]
    if unexpected_config:
        raise ValidationError("Unexpected channel configuration fields for this provider.")
    credentials = {key: value.strip() for key, value in body.credentials.items()}

    existing = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.tenant_id == ctx.tenant_id,
                Integration.provider == provider,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status == "disabled":
        raise ValidationError("This channel was permanently disabled and cannot be reconnected.")
    if existing is None:
        await EntitlementService.ensure_channel_allowed(ctx.session, ctx.tenant_id, provider)

    verification_config = (
        dict(existing.config) if existing and isinstance(existing.config, dict) else {}
    )
    verification_config.update(body.config)
    verified = await verify_channel_credentials(provider, credentials, verification_config)
    verified_at = datetime.now(UTC).isoformat()
    integration_config = {
        **verified.identity_config,
        "_connection": _verification_metadata(
            verified_at=verified_at, display_name=verified.display_name
        ),
    }

    if existing is None:
        integration = Integration(
            id=uuid.uuid4(),
            tenant_id=ctx.tenant_id,
            provider=provider,
            kind="channel",
            config=integration_config,
            credentials=encrypt_credentials_dict(credentials),
            status="pending",
        )
        _activate_verified_channel(integration)
        ctx.session.add(integration)
    else:
        _activate_verified_channel(existing)
        existing.config = integration_config
        existing.credentials = encrypt_credentials_dict(credentials)
        integration = existing

    try:
        await ctx.session.flush()
    except IntegrityError:
        # The partial unique index covers provider identity across tenants.
        # Never expose the conflicting tenant or any provider account details.
        raise ConflictError(
            "This provider account is already connected to another workspace."
        ) from None

    if provider == "telegram":
        await configure_telegram_webhook(
            credentials,
            _telegram_webhook_url(integration_config["public_key"]),
        )
        connection_metadata = dict(integration_config["_connection"])
        connection_metadata["webhook_configured_at"] = datetime.now(UTC).isoformat()
        integration_config = {**integration_config, "_connection": connection_metadata}
        integration.config = integration_config
        await ctx.session.flush()

    # §66: binding (or re-binding) a channel is a credential-bearing act with
    # tenant-wide blast radius — it redirects the provider's webhook traffic.
    # The audit row carries identity metadata only, never credentials.
    await AuditService.write(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        "integration.connected",
        "integration",
        str(integration.id),
        after={
            "provider": provider,
            "status": integration.status,
            "is_new": integration is not existing,
        },
    )

    return {
        "id": str(integration.id),
        "provider": provider,
        "status": integration.status,
        "credentials_verified": True,
        "display_name": verified.display_name,
        "verified_at": verified_at,
        "public_key": integration_config.get("public_key") if provider == "webchat" else None,
    }


@platform_router.post(
    "/integrations/{integration_id}/verify",
    response_model=schemas.IntegrationVerificationOut,
)
async def verify_integration(
    integration_id: UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Recheck a saved connection without returning its encrypted credentials."""
    integration = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.tenant_id == ctx.tenant_id,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise NotFoundError("channel integration not found")
    if integration.provider not in _CHANNEL_PROVIDERS:
        raise ValidationError("This channel provider cannot be verified.")
    if integration.status == "disabled":
        raise ValidationError("This channel was permanently disabled.")

    credentials = await IntegrationCredentialsService.decrypt(ctx.session, integration)
    try:
        verified = await verify_channel_credentials(
            integration.provider, credentials, integration.config or {}
        )
    except ValidationError as exc:
        current = _LEGACY_STATUS_ALIASES.get(integration.status, integration.status)
        if current == "active":
            Integration.validate_transition(current, "reauth_required")
            integration.status = "reauth_required"
        config = dict(integration.config or {})
        config["_connection"] = _verification_metadata(
            verified_at=None,
            display_name=(config.get("_connection") or {}).get("display_name"),
            failure="credentials_rejected",
        )
        integration.config = config
        await ctx.session.flush()
        # §66: the demotion to reauth_required is a state change on a live
        # channel — audited so an operator can see WHEN the credential died.
        await AuditService.write(
            ctx.session,
            ctx.tenant_id,
            ctx.user.id,
            "integration.verification_failed",
            "integration",
            str(integration.id),
            before={"status": current},
            after={"status": integration.status},
        )
        return {
            "id": str(integration.id),
            "provider": integration.provider,
            "status": integration.status,
            "credentials_verified": False,
            "display_name": (config.get("_connection") or {}).get("display_name"),
            "verified_at": None,
            "public_key": config.get("public_key") if integration.provider == "webchat" else None,
            "message": exc.message,
        }
    except ExternalProviderError as exc:
        config = dict(integration.config or {})
        return {
            "id": str(integration.id),
            "provider": integration.provider,
            "status": integration.status,
            "credentials_verified": bool((config.get("_connection") or {}).get("verified_at")),
            "display_name": (config.get("_connection") or {}).get("display_name"),
            "verified_at": (config.get("_connection") or {}).get("verified_at"),
            "public_key": config.get("public_key") if integration.provider == "webchat" else None,
            "message": exc.message,
        }

    _activate_verified_channel(integration)
    verified_at = datetime.now(UTC).isoformat()
    # Verify refreshes what it just learned (when, and under which name) and keeps what only the
    # link could record. `granted_scopes` is written once, by the OAuth flow; replacing the block
    # wholesale erased it, so the next GET reported every Page permission missing and told the
    # owner of a healthy channel to reconnect. `last_failure` is the one thing a success retires.
    previous = (integration.config or {}).get("_connection")
    kept = {
        key: value
        for key, value in (previous if isinstance(previous, dict) else {}).items()
        if key != "last_failure"
    }
    integration.config = {
        **verified.identity_config,
        "_connection": {
            **kept,
            **_verification_metadata(verified_at=verified_at, display_name=verified.display_name),
        },
    }
    try:
        await ctx.session.flush()
    except IntegrityError:
        raise ConflictError(
            "This provider account is already connected to another workspace."
        ) from None
    if integration.provider == "telegram":
        await configure_telegram_webhook(
            credentials,
            _telegram_webhook_url(integration.config["public_key"]),
        )
        connection_metadata = dict(integration.config["_connection"])
        connection_metadata["webhook_configured_at"] = datetime.now(UTC).isoformat()
        integration.config = {
            **integration.config,
            "_connection": connection_metadata,
        }
        await ctx.session.flush()

    # §66: a successful re-verification re-arms a live channel — audited with
    # the resulting status (active vs reconnected), never any credential.
    await AuditService.write(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        "integration.reverified",
        "integration",
        str(integration.id),
        after={"provider": integration.provider, "status": integration.status},
    )
    return {
        "id": str(integration.id),
        "provider": integration.provider,
        "status": integration.status,
        "credentials_verified": True,
        "display_name": verified.display_name,
        "verified_at": verified_at,
        "public_key": integration.config.get("public_key")
        if integration.provider == "webchat"
        else None,
    }


def _page_id_of(integration: Integration, credentials: dict) -> str:
    """The Facebook Page a Page-based channel is subscribed on.

    Facebook stores it in its config; Messenger's account id IS the Page id; Instagram's account id
    is the Instagram account, so its Page id is in the encrypted connection record.
    """
    config = integration.config if isinstance(integration.config, dict) else {}
    meta = credentials.get("_meta") if isinstance(credentials.get("_meta"), dict) else {}
    return str(
        meta.get("page_id")
        or config.get("page_id")
        or (config.get("account_id") if integration.provider == "messenger" else "")
        or ""
    )


async def _remove_meta_subscription(ctx: TenantContext, integration: Integration) -> dict | None:
    """Take this channel's webhook subscription off Meta and return what happened.

    ``None`` for a channel that has no Meta subscription (telegram, webchat). Never raises for a
    Meta failure: the local disconnect must not depend on Meta being reachable.
    """
    import httpx

    provider = integration.provider
    if provider not in (*meta_unsubscribe.PAGE_PROVIDERS, "whatsapp"):
        return None
    credentials = await IntegrationCredentialsService.decrypt(ctx.session, integration)
    async with httpx.AsyncClient(timeout=15.0) as http:
        if provider == "whatsapp":
            config = integration.config if isinstance(integration.config, dict) else {}
            waba_id = str(config.get("waba_id") or "")
            token = str(credentials.get("access_token") or "")
            if not waba_id or not token:
                return meta_unsubscribe._record(meta_unsubscribe.NOT_NEEDED, reason="no_waba")
            return await meta_unsubscribe.unsubscribe_waba(http, waba_id=waba_id, token=token)

        page_id = _page_id_of(integration, credentials)
        token = str(credentials.get("api_key") or credentials.get("page_access_token") or "")
        if not page_id or not token:
            return meta_unsubscribe._record(meta_unsubscribe.NOT_NEEDED, reason="no_page")
        # Siblings: the OTHER Page channels of this workspace that are still connected on the
        # same Page. They share the one subscription, so it may not be removed under them.
        siblings: list[str] = []
        rows = (
            (
                await ctx.session.execute(
                    select(Integration).where(
                        Integration.tenant_id == ctx.tenant_id,
                        Integration.kind == "channel",
                        Integration.provider.in_(meta_unsubscribe.PAGE_PROVIDERS),
                        Integration.id != integration.id,
                        Integration.status.in_(("active", "connected", "restricted")),
                    )
                )
            )
            .scalars()
            .all()
        )
        for other in rows:
            other_credentials = await IntegrationCredentialsService.decrypt(ctx.session, other)
            if _page_id_of(other, other_credentials) == page_id:
                siblings.append(other.provider)
        return await meta_unsubscribe.unsubscribe_page(
            http, page_id=page_id, page_token=token, sibling_providers=siblings
        )


def _store_cleanup(integration: Integration, outcome: dict | None) -> None:
    """Keep what Meta answered on the row, so it is shown and can be retried."""
    if outcome is None:
        return
    config = dict(integration.config) if isinstance(integration.config, dict) else {}
    config["_meta_cleanup"] = outcome
    integration.config = config


@platform_router.post(
    "/integrations/{integration_id}/disconnect",
    response_model=schemas.IntegrationOut,
)
async def disconnect_integration(
    integration_id: UUID,
    body: schemas.IntegrationDisconnectBody,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Disconnect a channel (§145 lifecycle: active|restricted → disconnected).

    DELIBERATE confirmation gate: the body must carry ``confirm=true``. A
    stray click or a replayed request must not cut a live provider webhook —
    disconnecting stops inbound message flow for the whole tenant, so the
    request is destructive enough to require an explicit assertion.

    Fail-closed on the state machine: only ``active`` and ``restricted`` rows
    may disconnect (those are the states that receive provider traffic);
    ``pending``/``connecting``/``reauth_required`` have no provider traffic to
    stop and are refused with the legal sources listed. ``disabled`` is
    terminal and reconnecting is refused by design (connect enforces it too).
    Idempotent: an already-disconnected row returns as-is without a second
    audit entry. Reversal is the verified connect path — ``POST
    /integrations/connect`` — so a reconnection always re-proves credentials
    with the provider before going live. The decision is audited (§66) with
    the before/after status.
    """
    if not body.confirm:
        raise ValidationError(
            'disconnecting a channel requires confirmation — send {"confirm": true}',
            details={"integration_id": str(integration_id)},
        )
    integration = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.tenant_id == ctx.tenant_id,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise NotFoundError("channel integration not found")

    current = _LEGACY_STATUS_ALIASES.get(integration.status, integration.status)
    if current == "disconnected":
        return _integration_output(integration)
    if current == "disabled":
        raise ValidationError("This channel was permanently disabled.")
    if current not in ("active", "restricted"):
        raise ValidationError(
            "this channel cannot be disconnected in its current status — only an "
            "active or restricted channel receives provider traffic; the legal "
            "sources to disconnect from are: active, restricted",
            details={
                "integration_id": str(integration_id),
                "status": integration.status,
            },
        )
    Integration.validate_transition(current, "disconnected")
    integration.status = "disconnected"
    # The other half of a disconnect: stop Meta delivering this channel's events. The outcome is
    # kept (never the token), and a Meta failure does not undo or block the local disconnect.
    outcome = await _remove_meta_subscription(ctx, integration)
    _store_cleanup(integration, outcome)
    await ctx.session.flush()
    await AuditService.write(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        "integration.disconnected",
        "integration",
        str(integration.id),
        before={"status": current},
        after={
            "status": "disconnected",
            "meta_subscription": (outcome or {}).get("state"),
        },
    )
    return _integration_output(integration)


@platform_router.get(
    "/integrations/{integration_id}/diagnostics",
    response_model=schemas.ChannelDiagnosticsOut,
)
async def channel_diagnostics(integration_id: UUID, ctx: SettingsReadCtx):
    """Why a Meta channel is, or is not, receiving: one named check per thing that can go wrong.

    Reads our own records, then asks Meta live (subscription and permissions) with the channel's
    own token. A Meta outage is reported as an unknown check, never as a failed request, and no
    token or secret is ever returned.
    """
    import httpx

    from app.core.config import get_settings
    from app.modules.customers import meta_channel_diagnostics as diag

    integration = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.tenant_id == ctx.tenant_id,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise NotFoundError("channel integration not found")
    if integration.provider not in diag.WEBHOOK_OBJECT:
        raise ValidationError("Diagnostics exist for the Meta channels only.")

    settings = get_settings()
    config = integration.config if isinstance(integration.config, dict) else {}
    connection = config.get("_connection") if isinstance(config.get("_connection"), dict) else {}
    connected = integration.status in ("active", "connected", "restricted")

    subscription = permissions = None
    if connected:
        credentials = await IntegrationCredentialsService.decrypt(ctx.session, integration)
        async with httpx.AsyncClient(timeout=8.0) as http:
            if integration.provider == "whatsapp":
                token = str(credentials.get("access_token") or "")
                asset = str(config.get("waba_id") or "")
            else:
                token = str(
                    credentials.get("api_key") or credentials.get("page_access_token") or ""
                )
                asset = _page_id_of(integration, credentials)
            # An Instagram Login token is honoured by graph.instagram.com only, and that grant has
            # no debug_token / Page-permission list to measure, so it is probed on its own host.
            ig_login = integration.provider == "instagram" and diag._is_instagram_login(config)
            graph = diag.INSTAGRAM_LOGIN_GRAPH if ig_login else None
            if ig_login:
                # The account id is the asset; the Instagram app (not the Facebook one) owns it.
                asset = str(config.get("account_id") or asset)
            if token and asset:
                subscription = await diag.probe_subscription(
                    http,
                    asset_id=asset,
                    token=token,
                    app_id=(
                        (settings.instagram_app_id or settings.meta_app_id)
                        if ig_login
                        else settings.meta_app_id
                    )
                    or None,
                    graph=graph,
                )
            if token and integration.provider != "whatsapp":
                permissions = await diag.probe_permissions(http, token=token, graph=graph)

    failed = (
        await ctx.session.execute(
            select(func.count())
            .select_from(WebhookEvent)
            .where(
                WebhookEvent.tenant_id == ctx.tenant_id,
                WebhookEvent.provider == integration.provider,
                WebhookEvent.processing_status.in_(("failed", "dead")),
            )
        )
    ).scalar_one()

    return diag.build_report(
        provider=integration.provider,
        status=_LEGACY_STATUS_ALIASES.get(integration.status, integration.status),
        config=config,
        webhook_health=integration.webhook_health,
        recorded_scopes=connection.get("granted_scopes"),
        subscription=subscription,
        permissions=permissions,
        server_webhook_ready=_webhook_status(integration) != "server_setup_required",
        api_base_url=_telegram_webhook_base_url(),
        failed_events=int(failed or 0),
    )


def reconcile_page_id(provider: str, config: dict) -> str | None:
    """The Page id a reconciliation walks, or None.

    A Messenger channel keeps its Page id in `account_id` (the OAuth callback writes only that);
    an Instagram channel's `account_id` is the Instagram account, never a Page, so Instagram needs
    an explicit `page_id`.
    """
    explicit = str(config.get("page_id") or "")
    if explicit:
        return explicit
    if provider == "messenger":
        return str(config.get("account_id") or "") or None
    return None


@platform_router.post(
    "/integrations/{integration_id}/messenger-reconcile",
    response_model=schemas.MessengerReconcileOut,
)
async def messenger_reconcile(integration_id: UUID, ctx: SettingsReadCtx):
    """Compare FIHRIST's threads for a Page to what Meta still lists, within the provider's bounds.

    The answer names what Meta has that we never stored, so a missed webhook becomes a list to
    import instead of a silent gap. A capped or failed walk reports that it could not prove
    absence, and a rate limit or outage comes back as an error with its reason.
    """
    import httpx

    from app.modules.conversations.messenger_reconcile import reconcile_page
    from app.modules.customers.models import CustomerIdentity

    integration = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.tenant_id == ctx.tenant_id,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise NotFoundError("channel integration not found")
    if integration.provider not in ("messenger", "instagram"):
        raise ValidationError("Reconciliation exists for Messenger and Instagram only.")
    if integration.provider == "instagram":
        # The walker reads a Page's Messenger conversations. An Instagram connection (above all an
        # Instagram Login one, which has no Page at all) has no such listing here yet, so running it
        # would compare the wrong world. Say so plainly instead of returning a misleading result.
        return {
            "supported": False,
            "reason": "not_supported_for_this_channel_yet",
            "missing_locally": [],
            "stale_locally": [],
            "error": None,
        }

    config = integration.config if isinstance(integration.config, dict) else {}
    page_id = reconcile_page_id(integration.provider, config)
    if not page_id:
        raise ValidationError("This channel has no Page id to reconcile against.")

    credentials = await IntegrationCredentialsService.decrypt(ctx.session, integration)
    token = str(credentials.get("page_access_token") or credentials.get("api_key") or "")
    if not token:
        raise ValidationError("This channel has no usable token to reconcile with.")

    # A customer identity stores the PSID, so it is compared with the conversation PARTICIPANTS
    # (the people), never with Meta's thread ids: a person Meta lists and FIHRIST has never seen.
    rows = (
        await ctx.session.execute(
            select(CustomerIdentity.external_id).where(
                CustomerIdentity.tenant_id == ctx.tenant_id,
                CustomerIdentity.channel == integration.provider,
            )
        )
    ).scalars()
    local = {str(value) for value in rows if value}

    async with httpx.AsyncClient(timeout=20.0) as http:
        return await reconcile_page(
            http,
            page_id=page_id,
            token=token,
            local_person_ids=local,
            provider=integration.provider,
        )


@platform_router.get(
    "/integrations/{integration_id}/reconnect-plan",
    response_model=schemas.ReconnectPlanOut,
)
async def reconnect_plan_route(
    integration_id: UUID,
    ctx: SettingsReadCtx,
    capability: str | None = None,
):
    """One Page connection, its capability states, and what to ask Meta for.

    Four problems look identical on a channel screen ("it does not work"): a dead token, a missing
    scope, an unsubscribed webhook field, and a feature Meta has not approved. Each needs a
    different action, so this route says which one it is instead of sending the owner to reconnect
    everything. `capability` narrows it to one function; without it every capability is answered.
    """
    from app.modules.customers import meta_linking

    integration = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.tenant_id == ctx.tenant_id,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise NotFoundError("channel integration not found")
    if integration.provider not in diag_webhook_objects():
        raise ValidationError("The linking layer exists for the Meta channels only.")

    connection = meta_linking.MetaPageConnection.from_integration(integration)
    wanted = [capability] if capability else list(meta_linking.CAPABILITIES)
    unknown = [name for name in wanted if name not in meta_linking.CAPABILITIES]
    if unknown:
        raise ValidationError("unknown capability: " + ", ".join(unknown))

    return {
        "page_id": connection.page_id,
        "connected": connection.connected,
        "has_token": connection.has_token,
        "granted_scopes": sorted(connection.granted_scopes or ()),
        "page_tasks": sorted(connection.page_tasks or ()),
        "subscribed_fields": (
            sorted(connection.subscribed_fields)
            if connection.subscribed_fields is not None
            else None
        ),
        "capabilities": [
            {
                "capability": name,
                "plan": meta_linking.reconnect_plan(connection, name),
            }
            for name in wanted
        ],
        "states": connection.capability_states(),
    }


def diag_webhook_objects() -> tuple[str, ...]:
    """The providers the shared linking layer covers (the Meta channels)."""
    from app.modules.customers import meta_channel_diagnostics as diag

    return tuple(diag.WEBHOOK_OBJECT)


@platform_router.get(
    "/integrations/{integration_id}/whatsapp-roadmap",
    response_model=schemas.WhatsAppRoadmapOut,
)
async def whatsapp_roadmap(integration_id: UUID, ctx: SettingsReadCtx):
    """The WhatsApp features Meta gates, each with its state and what the owner can do.

    Calls, Groups and Marketing Messages are not switches FIHRIST owns: Meta decides per number,
    per business account and per approval. They are listed here with that state and the evidence,
    so the channel screen shows a reason instead of a button that cannot work. Coexistence is the
    one of the four FIHRIST can ask for at signup, and its measured state comes from what the
    connection actually recorded.
    """
    from app.modules.customers import whatsapp_roadmap as roadmap_mod

    integration = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.tenant_id == ctx.tenant_id,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise NotFoundError("channel integration not found")
    if integration.provider != "whatsapp":
        raise ValidationError("The WhatsApp roadmap exists for the WhatsApp channel only.")

    config = integration.config if isinstance(integration.config, dict) else {}
    mode = str(config.get("onboarding_mode") or "cloud_api")
    rows = []
    for row in roadmap_mod.roadmap():
        if row["key"] == "coexistence":
            row = dict(row)
            row["onboarding_mode"] = mode
            row["measured"] = True
            # Connected through coexistence means Meta already allowed it for this number. A
            # cloud_api connection simply has not asked, which is NOT a refusal: only Meta's own
            # "no" (recorded at signup) is account_ineligible.
            row["state"] = roadmap_mod.coexistence_state(
                config, connected=integration.status in ("active", "connected", "restricted")
            )
        rows.append(row)
    return {
        "connected": integration.status in ("active", "connected", "restricted"),
        "onboarding_mode": mode,
        "features": rows,
    }


@platform_router.post(
    "/integrations/{integration_id}/retry-meta-cleanup",
    response_model=schemas.IntegrationOut,
)
async def retry_meta_cleanup(
    integration_id: UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Try again to remove a disconnected channel's subscription from Meta.

    Only for a channel that is already disconnected and whose last removal did not complete. A
    channel that is connected is refused: removing its subscription would stop its messages.
    """
    integration = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.tenant_id == ctx.tenant_id,
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()
    if integration is None:
        raise NotFoundError("channel integration not found")
    if integration.status != "disconnected":
        raise ValidationError("Only a disconnected channel can have its Meta subscription removed.")
    if not meta_unsubscribe.needs_cleanup(integration.config):
        return _integration_output(integration)
    outcome = await _remove_meta_subscription(ctx, integration)
    _store_cleanup(integration, outcome)
    await ctx.session.flush()
    await AuditService.write(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        "integration.meta_cleanup_retried",
        "integration",
        str(integration.id),
        before={},
        after={"meta_subscription": (outcome or {}).get("state")},
    )
    return _integration_output(integration)


@platform_router.post(
    "/integrations",
    status_code=201,
    response_model=schemas.IntegrationUpserted,
)
async def upsert_integration(
    body: IntegrationBody,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Register a non-channel integration through the generic lifecycle API."""
    if body.kind == "channel" and body.provider in _CHANNEL_PROVIDERS:
        raise ValidationError("Use POST /integrations/connect to verify channel credentials.")
    existing = (
        await ctx.session.execute(
            select(Integration).where(
                Integration.tenant_id == ctx.tenant_id,
                Integration.provider == body.provider,
                Integration.kind == body.kind,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # §145: a status CHANGE on an existing row must be a legal lifecycle
        # transition — validate_transition was dead code while this wrote
        # status directly. Creation (below) and same-status re-upserts skip
        # the check so the webhook-credential refresh path (idempotent
        # re-register) cannot fail. The check runs BEFORE any field is
        # written so a rejected upsert stages no partial write.
        from_status = _LEGACY_STATUS_ALIASES.get(existing.status, existing.status)
        to_status = _LEGACY_STATUS_ALIASES.get(body.status, body.status)
        if to_status != from_status:
            try:
                Integration.validate_transition(from_status, to_status)
            except ValueError as exc:
                raise ValidationError(
                    str(exc),
                    details={
                        "from_status": existing.status,
                        "to_status": body.status,
                        "allowed": sorted(
                            Integration._LIFECYCLE_TRANSITIONS.get(from_status, set())
                        ),
                    },
                ) from exc
        existing.config = body.config
        # §68: credentials are encrypted at rest BEFORE they touch the row.
        # Merge semantics (§145): an update WITHOUT a credentials payload is
        # the documented idempotent re-register (webhook/config refresh) and
        # must not erase the channel secrets already stored — the default {}
        # would otherwise silently wipe them and break the next outbound send.
        if body.credentials:
            existing.credentials = encrypt_credentials_dict(body.credentials)
        existing.status = body.status
        return {"id": str(existing.id), "status": existing.status}
    # §165: which channels a plan includes is an entitlement. Only the CREATE
    # branch is gated — refreshing an existing integration is not a new channel
    # and must keep working after a downgrade.
    #
    # The plan stores `channels` as an ALLOWLIST of names, so the provider is
    # what must be checked: `ensure(..., "CanCreateChannel")` could only ever ask
    # "may this tenant add any channel at all", and the capability name never
    # matched a plan row anyway.
    await EntitlementService.ensure_channel_allowed(ctx.session, ctx.tenant_id, body.provider)
    integration = Integration(
        tenant_id=ctx.tenant_id,
        provider=body.provider,
        kind=body.kind,
        config=body.config,
        # §68: credentials are encrypted at rest BEFORE they touch the row.
        credentials=encrypt_credentials_dict(body.credentials),
        status=body.status,
    )
    ctx.session.add(integration)
    await ctx.session.flush()
    return {"id": str(integration.id), "status": integration.status}


# The Meta OAuth connect flow registers onto the same platform surface
# (deferred bottom import: meta_oauth defers router helpers back here).
from app.modules.customers.meta_oauth import meta_oauth_router  # noqa: E402
from app.modules.customers.meta_whatsapp_signup import (  # noqa: E402
    whatsapp_signup_router,
)

platform_router.include_router(meta_oauth_router)
platform_router.include_router(whatsapp_signup_router)
