"""Identity tenants HTTP routes: invitations, lifecycle, settings, offboarding."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import PermissionDeniedError, ValidationError
from app.modules.identity import schemas, service
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.identity.models import Role

tenants_router = APIRouter(prefix="/tenants", tags=["tenants"])


class LifecycleTransitionRequest(BaseModel):
    """Platform-admin request to move a tenant to another §48 state.

    ``password`` is the §146 step-up for the one tenant-side-requestable
    transition (offboarding): it is ignored for platform-admin callers, whose
    authority gate is the DB-verified platform flag.
    """

    state: str = Field(min_length=1, max_length=31)
    reason: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=128)


class TenantCapabilityPolicyOut(BaseModel):
    """What a tenant may do in its current state — shown to the operator."""

    model_config = ConfigDict(from_attributes=True)

    allows_login: bool
    allows_api: bool
    allows_ai: bool
    allows_channels: bool
    allows_automation: bool
    allows_data_access: bool


class TenantLifecycleOut(BaseModel):
    tenant_id: uuid.UUID
    lifecycle_state: str
    is_active: bool
    status_reason: str | None = None
    suspended_at: datetime | None = None
    grace_ends_at: datetime | None = None
    deletion_scheduled_at: datetime | None = None
    policy: TenantCapabilityPolicyOut


class TenantCurrencyRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3)


class TenantTimezoneRequest(BaseModel):
    #: An empty string clears the setting (back to the deployment zone), which
    #: is why the field is optional rather than required-and-non-empty.
    timezone: str | None = Field(default=None, max_length=64)


def _lifecycle_out(tenant) -> TenantLifecycleOut:
    policy = service.TenantLifecycleService.policy_for(tenant.lifecycle_state)
    return TenantLifecycleOut(
        tenant_id=tenant.id,
        lifecycle_state=tenant.lifecycle_state,
        is_active=tenant.is_active,
        status_reason=tenant.status_reason,
        suspended_at=tenant.suspended_at,
        grace_ends_at=tenant.grace_ends_at,
        deletion_scheduled_at=tenant.deletion_scheduled_at,
        policy=TenantCapabilityPolicyOut(**asdict(policy)),
    )


@tenants_router.post(
    "/{tenant_id}/invitations", response_model=schemas.InvitationOut, status_code=201
)
async def create_invitation(
    tenant_id: uuid.UUID,
    body: schemas.InviteRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    # §165: seat limits are a plan entitlement. Enforced here so the invitation
    # cannot be created at all, rather than failing at acceptance time.
    from app.modules.billing.service import EntitlementService

    await EntitlementService.ensure(ctx.session, tenant_id, "CanAddUser")
    invitation = await service.TenantService.invite(
        ctx.session,
        tenant_id=tenant_id,
        email=body.email,
        role_code=body.role_code,
        invited_by=ctx.user.id,
        # Privilege-escalation guard (audit finding 7): the service enforces
        # the hierarchy against the CALLER's role — ctx.role_code is the
        # membership row's role, resolved per request by get_tenant_ctx, and
        # the platform flag is the DB-verified one from get_current_user.
        inviter_role_code=ctx.role_code,
        inviter_is_platform_admin=ctx.user.is_platform_admin,
    )
    # The response's role_code is read back from the roles table by the stored
    # role_id — the same read-back discipline the hierarchy guard itself
    # follows (the DB decides, never the request body). Serializing the ORM
    # row directly was a 500 on every successful invite: Invitation carries
    # role_id, and InvitationOut's role_code had no attribute to read.
    role_code = (
        await ctx.session.execute(sa.select(Role.code).where(Role.id == invitation.role_id))
    ).scalar_one_or_none()
    return schemas.InvitationOut(
        id=invitation.id,
        email=invitation.email,
        role_code=role_code,
        status=invitation.status,
        expires_at=invitation.expires_at,
        token=invitation.token,  # shown once to the inviting admin
    )


@tenants_router.delete(
    "/{tenant_id}/invitations/{invitation_id}",
    status_code=204,
)
async def revoke_tenant_invitation(
    tenant_id: uuid.UUID,
    invitation_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    await service.TenantService.revoke_invitation(
        ctx.session, tenant_id=tenant_id, invitation_id=invitation_id
    )
    return Response(status_code=204)


@tenants_router.post("/{tenant_id}/lifecycle", response_model=TenantLifecycleOut)
async def transition_tenant_lifecycle(
    tenant_id: uuid.UUID,
    body: LifecycleTransitionRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Move a tenant between §48 lifecycle states (suspend, reactivate, offboard).

    Authority (external audit finding 1): ``settings:write`` alone used to gate
    the whole state machine, so ANY owner/admin could wave their own tenant
    from past_due or suspension back to active — a billing bypass by API call.
    The transitions that RESTORE service or steer billing (→active, →past_due,
    →grace, →deleted) are platform-admin-only now. The flag checked here is
    ``ctx.user.is_platform_admin`` — the SAME DB-verified value the
    ``require_platform_admin`` dependency gates on: deps.get_current_user
    re-reads it from the users row on EVERY request and never trusts the JWT
    claim for it, so a demoted admin is cut off at once, not at token expiry.
    (The dependency itself cannot be applied unconditionally — it would also
    block the owner's one permitted request below — so the check happens here,
    on the same verified flag.)

    A tenant-side caller may request exactly ONE transition: their own
    ``offboarding`` — capability-REDUCING, so it cannot bypass billing — and
    because it starts the deletion countdown it is step-up protected with the
    §146 pattern (mfa/enroll): the password is re-verified before the
    destructive change. ``suspended`` is not owner-requestable at all; it is
    the billing system's and the platform's lever.

    Cross-tenant break-glass transitions do NOT come through this route (it
    requires membership in the target tenant); platform admins use
    PATCH /admin/tenants/{id}/status in the platform module.
    """
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    # The admin check comes FIRST, not last: the previous ordering tested the
    # target sets before the flag, so `suspended` — which is in NEITHER set —
    # fell into the tenant-refusal branch and a platform admin could not move
    # a tenant into suspension at all (the state the billing system and the
    # §147 break-glass route exist to reach). Now: a DB-verified platform
    # admin passes for every target the state machine accepts; everyone else
    # gets exactly one requestable target plus two distinct refusals.
    if ctx.user.is_platform_admin:
        pass  # full authority over every target the state machine accepts
    elif body.state in service.TENANT_REQUESTABLE_LIFECYCLE_TARGETS:
        # §146 step-up for the owner's one destructive request.
        if not body.password:
            raise PermissionDeniedError(
                "re-authentication (your password) is required to request offboarding"
            )
        from app.core.security import verify_password_async

        row = await service.UserService.get(ctx.session, ctx.user.id)
        if not await verify_password_async(body.password, row.password_hash):
            raise PermissionDeniedError("password step-up failed — re-authenticate first")
    elif body.state in service.PLATFORM_ONLY_LIFECYCLE_TARGETS:
        raise PermissionDeniedError(
            "platform admin access is required to move a tenant to "
            f"{body.state} — tenant admins may only request offboarding"
        )
    else:
        # `suspended` is in neither set: it is the billing system's and the
        # platform's lever, never tenant-requestable.
        raise PermissionDeniedError(f"tenant admins may only request offboarding, not {body.state}")
    tenant = await service.TenantLifecycleService.transition(
        ctx.session,
        tenant_id,
        body.state,
        reason=body.reason,
        actor_user_id=ctx.user.id,
    )
    return _lifecycle_out(tenant)


@tenants_router.get("/{tenant_id}/lifecycle", response_model=TenantLifecycleOut)
async def get_tenant_lifecycle(
    tenant_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Current lifecycle state + what that state actually permits."""
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    tenant = await service.TenantLifecycleService.get(ctx.session, tenant_id)
    return _lifecycle_out(tenant)


@tenants_router.put("/{tenant_id}/currency")
async def set_tenant_currency(
    tenant_id: uuid.UUID,
    body: TenantCurrencyRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§47: declare the one currency this tenant trades in.

    Refused rather than converted when the code is unknown, cannot be stored, or
    would mix with money already booked — see ``TenantSettingsService``.
    """
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    tenant = await service.TenantSettingsService.set_currency(
        ctx.session, tenant_id, body.currency, actor_user_id=ctx.user.id
    )
    return {"tenant_id": str(tenant.id), "currency": tenant.currency}


@tenants_router.get("/{tenant_id}/currency")
async def get_tenant_currency(
    tenant_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    """§47 read: which currency this tenant trades in.

    The PUT has always been here; the money a screen renders has a currency, so
    a client must be able to ASK for it rather than assume one. The lifecycle
    service already loads the same tenant row, so this reuses that read rather
    than adding a second one.
    """
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    tenant = await service.TenantLifecycleService.get(ctx.session, tenant_id)
    return {"tenant_id": str(tenant.id), "currency": tenant.currency}


@tenants_router.put("/{tenant_id}/timezone")
async def set_tenant_timezone(
    tenant_id: uuid.UUID,
    body: TenantTimezoneRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§47/M10 remainder: declare the calendar day this merchant counts in.

    The sibling of ``PUT /tenants/{id}/currency``, with the same posture: an
    IANA name this runtime cannot resolve is refused (400) rather than stored,
    and the change is audited through the same lineage. What the zone changes is
    the LABEL on a day bucket, never an instant — analytics re-derives every
    bucket from ``timestamptz`` on read, so moving it re-reads history rather
    than rewriting it.
    """
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    tenant = await service.TenantSettingsService.set_timezone(
        ctx.session, tenant_id, body.timezone, actor_user_id=ctx.user.id
    )
    return {"tenant_id": str(tenant.id), "timezone": tenant.timezone}


@tenants_router.get("/{tenant_id}/timezone")
async def get_tenant_timezone(
    tenant_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    """§47/M10 remainder read: which zone this tenant declared, NULL if none.

    ``timezone: null`` is the tenant's own answer — "no opinion, use the
    deployment's" — not a missing one. The EFFECTIVE zone belongs to the reader
    that used it, and every analytics response already carries it as
    ``timezone`` beside ``timezone_source`` (``param`` / ``tenant`` /
    ``deployment`` / ``fallback``), because the only honest answer to "which zone
    were these numbers bucketed in" is the one made by the code that bucketed
    them.
    """
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    tenant = await service.TenantLifecycleService.get(ctx.session, tenant_id)
    return {"tenant_id": str(tenant.id), "timezone": tenant.timezone}


@tenants_router.post("/{tenant_id}/offboarding/export")
async def export_tenant_data(
    tenant_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§49: export all tenant data during the offboarding window.

    Only available when the tenant is in the 'offboarding' state — the
    admin uses this to take their data out before the retention window
    expires and the data is purged.
    """
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    tenant = await service.TenantLifecycleService.get(ctx.session, tenant_id)
    if tenant.lifecycle_state != "offboarding":
        raise ValidationError(
            "data export is only available during offboarding "
            f"(current state: {tenant.lifecycle_state})",
            details={"lifecycle_state": tenant.lifecycle_state},
        )
    from app.workers.retention_worker import OffboardingWorker

    export = await OffboardingWorker.export_data(ctx.session, tenant_id)
    return JSONResponse(
        content=export,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": (f'attachment; filename="sales-os-export-{tenant_id}.json"'),
            "X-Export-Schema-Version": "1.0",
        },
    )


@tenants_router.get("/{tenant_id}/offboarding/status")
async def offboarding_status(
    tenant_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§50: check the offboarding retention window status."""
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    tenant = await service.TenantLifecycleService.get(ctx.session, tenant_id)
    if tenant.lifecycle_state != "offboarding":
        return {
            "tenant_id": str(tenant_id),
            "lifecycle_state": tenant.lifecycle_state,
            "action": "not_applicable",
        }
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    deletion_at = tenant.deletion_scheduled_at
    remaining_days = (deletion_at - now).days if deletion_at else None
    return {
        "tenant_id": str(tenant_id),
        "lifecycle_state": tenant.lifecycle_state,
        "deletion_scheduled_at": deletion_at.isoformat() if deletion_at else None,
        "remaining_days": remaining_days,
        "can_export": True,
        "retention_days": 30,
    }
