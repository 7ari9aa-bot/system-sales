"""Platform routes — invitations, channel integrations, connect/verify/disconnect."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import urlencode, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import ConflictError, ExternalProviderError, NotFoundError, ValidationError
from app.core.secrets import encrypt_credentials_dict
from app.modules.billing.service import EntitlementService
from app.modules.customers import schemas
from app.modules.customers.schemas import IntegrationBody
from app.modules.identity.models import Invitation, Role
from app.modules.platform.integration_verifier import (
    channel_field_allow_lists,
    configure_telegram_webhook,
    signed_webhook_providers,
    telegram_webhook_secret_configured,
    verify_channel_credentials,
)
from app.modules.platform.models import Integration
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


def _webhook_status(integration: Integration) -> str:
    if integration.provider == "webchat":
        return "ready"

    from app.core.config import get_settings

    settings = get_settings()
    public_api_configured = _telegram_webhook_base_url() is not None
    configured = {
        "whatsapp": public_api_configured
        and bool(settings.whatsapp_app_secret and settings.whatsapp_verify_token),
        "messenger": public_api_configured
        and bool(settings.messenger_app_secret and settings.messenger_verify_token),
        "facebook": public_api_configured
        and bool(settings.messenger_app_secret and settings.messenger_verify_token),
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
        "public_key": public_key if integration.provider == "webchat" else None,
    }


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
    integration.config = {
        **verified.identity_config,
        "_connection": _verification_metadata(
            verified_at=verified_at, display_name=verified.display_name
        ),
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
    if current not in ("active", "restricted", "reauth_required", "connecting", "pending"):
        raise ValidationError(
            "this channel cannot be disconnected in its current status",
            details={
                "integration_id": str(integration_id),
                "status": integration.status,
            },
        )
    Integration.validate_transition(current, "disconnected")
    integration.status = "disconnected"
    await ctx.session.flush()
    await AuditService.write(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        "integration.disconnected",
        "integration",
        str(integration.id),
        before={"status": current},
        after={"status": "disconnected"},
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
