"""Identity + auth HTTP routes."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import PermissionDeniedError, ValidationError
from app.modules.billing.service import EntitlementService
from app.modules.identity import schemas, service
from app.modules.identity.deps import (
    CurrentUserDep,
    DbSession,
    TenantContext,
    TenantCtxDep,
    require_permission,
)

router = APIRouter(tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])
tenants_router = APIRouter(prefix="/tenants", tags=["tenants"])
# §151 — the tenant's hierarchy surface. Tenancy comes from the request
# context only (no tenant ids in paths): every handler passes ctx.tenant_id
# into the service, which filters with it AND runs under the bound RLS GUC.
hierarchy_router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])

_CLIENT_TTL = 60 * 60 * 24 * 30  # refresh cookie life if cookie mode used


class LifecycleTransitionRequest(BaseModel):
    """Platform-admin request to move a tenant to another §48 state."""

    state: str = Field(min_length=1, max_length=31)
    reason: str | None = Field(default=None, max_length=255)


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


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("user-agent"), request.client.host if request.client else None


@router.post("/auth/register", response_model=schemas.CurrentUser, status_code=201)
async def register(body: schemas.RegisterRequest, session: DbSession):
    user, _tenant = await service.AuthService.register(
        session,
        tenant_name=body.tenant_name,
        tenant_slug=body.tenant_slug,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
    )
    return schemas.CurrentUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_platform_admin=user.is_platform_admin,
        tenants=[],
    )


@router.post("/auth/login", response_model=schemas.TokenPair)
async def login(body: schemas.LoginRequest, request: Request, session: DbSession):
    user_agent, ip = _client_meta(request)
    pair, _user, _tenant_id = await service.AuthService.login(
        session, email=body.email, password=body.password, user_agent=user_agent, ip=ip
    )
    return pair


@router.post("/auth/refresh", response_model=schemas.TokenPair)
async def refresh(body: schemas.RefreshRequest, request: Request, session: DbSession):
    user_agent, ip = _client_meta(request)
    pair, _user, _tenant_id = await service.AuthService.refresh(
        session, refresh_token=body.refresh_token, user_agent=user_agent, ip=ip
    )
    return pair


@router.post("/auth/logout", status_code=204)
async def logout(body: schemas.RefreshRequest, session: DbSession, response: Response):
    await service.AuthService.logout(session, refresh_token=body.refresh_token)
    response.status_code = 204
    return None


@router.get("/auth/me", response_model=schemas.CurrentUser)
async def me(user: CurrentUserDep, session: DbSession):
    # RLS: tenant_users uses the `app.user_id` OR-clause for self-discovery —
    # bind it before the membership query or the list comes back empty.
    await bind_tenant_user(session, user.id)
    full = await service.UserService.get(session, user.id)
    tenants = await service.TenantService.list_for_user(session, user.id)
    return schemas.CurrentUser(
        id=full.id,
        email=full.email,
        full_name=full.full_name,
        is_platform_admin=full.is_platform_admin,
        tenants=[
            schemas.CurrentTenant(id=t.id, name=t.name, slug=t.slug, role_code=role)
            for t, role in tenants
        ],
    )


@router.post("/auth/switch-tenant", response_model=schemas.TokenPair)
async def switch_tenant(
    body: schemas.RefreshRequest, tenant_id: uuid.UUID, user: CurrentUserDep, session: DbSession
):
    return await service.AuthService.switch_tenant(
        session, user=user, tenant_id=tenant_id, refresh_token=body.refresh_token
    )


# ---------- §146 MFA (TOTP) ----------

class MfaVerifyRequest(BaseModel):
    """Body for POST /auth/mfa/verify — the login challenge's second step.

    The code is a 6-digit TOTP *or* a 16-char hex recovery code (§146: backup
    codes must work when the authenticator is gone).
    """

    challenge_id: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=6, max_length=64)


class MfaEnrollOut(BaseModel):
    """The TOTP secret + provisioning URL, shown ONCE at enrollment."""

    secret: str
    otpauth_url: str


class MfaEnrollRequest(BaseModel):
    """Body for POST /auth/mfa/enroll — §146 step-up.

    Enrollment permanently changes how an account proves identity, so a
    bearer token alone must not be enough: with only a token, an attacker who
    stole a session could attach THEIR authenticator and lock the real user
    out at the next login.
    """

    password: str = Field(min_length=1)


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class MfaDisableRequest(BaseModel):
    code: str | None = Field(default=None, min_length=6, max_length=10)
    backup_code: str | None = Field(default=None, min_length=6, max_length=32)


@router.post("/auth/mfa/verify", response_model=schemas.TokenPair)
async def mfa_verify(body: MfaVerifyRequest, request: Request, session: DbSession):
    """§146: complete an MFA-challenged login (challenge is single-use)."""
    user_agent, ip = _client_meta(request)
    pair, _user, _tenant_id = await service.AuthService.mfa_verify(
        session,
        challenge_id=body.challenge_id,
        code=body.code,
        user_agent=user_agent,
        ip=ip,
    )
    return pair


@router.post("/auth/mfa/enroll", response_model=MfaEnrollOut, status_code=201)
async def mfa_enroll(body: MfaEnrollRequest, user: CurrentUserDep, session: DbSession):
    """§146: start TOTP enrollment — confirm with a code before it challenges.

    Step-up (§146): the password is re-verified before a secret is minted, so
    a stolen access token cannot be used to bind an attacker's authenticator.
    """
    from app.core.mfa import enroll_mfa
    from app.core.security import verify_password

    row = await service.UserService.get(session, user.id)
    if not verify_password(body.password, row.password_hash):
        raise PermissionDeniedError("password step-up failed — re-authenticate first")

    enrolled = await enroll_mfa(session, user_id=user.id)
    return MfaEnrollOut(secret=enrolled.secret, otpauth_url=enrolled.otpauth_url)


@router.post("/auth/mfa/confirm")
async def mfa_confirm(body: MfaCodeRequest, user: CurrentUserDep, session: DbSession):
    """§146: prove possession → MFA enabled; backup codes are returned ONCE."""
    from app.core.mfa import confirm_mfa

    codes = await confirm_mfa(session, user_id=user.id, code=body.code)
    return {"backup_codes": codes}


@router.post("/auth/mfa/disable", status_code=204)
async def mfa_disable(body: MfaDisableRequest, user: CurrentUserDep, session: DbSession):
    """§146: disable with a current TOTP code OR a one-time backup code."""
    from app.core.mfa import disable_mfa

    await disable_mfa(
        session, user_id=user.id, code=body.code, backup_code=body.backup_code
    )
    return Response(status_code=204)


async def bind_tenant_user(session, user_id) -> None:
    """Bind the `app.user_id` GUC (transaction-scoped, pooler-safe)."""
    from sqlalchemy import text

    await session.execute(
        text("SELECT set_config(:guc, :user_id, true)"),
        {"guc": "app.user_id", "user_id": str(user_id)},
    )


@router.post("/invitations/accept", response_model=schemas.CurrentUser, status_code=201)
async def accept_invitation(body: schemas.AcceptInvitationRequest, session: DbSession):
    """Public endpoint: redeem an invitation token (no auth — the token is the credential)."""
    user, _invitation = await service.TenantService.accept_invitation(
        session, token=body.token, password=body.password, full_name=body.full_name
    )
    tenants = await service.TenantService.list_for_user(session, user.id)
    return schemas.CurrentUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_platform_admin=user.is_platform_admin,
        tenants=[
            schemas.CurrentTenant(id=t.id, name=t.name, slug=t.slug, role_code=role)
            for t, role in tenants
        ],
    )


@users_router.get("/me", response_model=schemas.CurrentUser)
async def my_profile(ctx: TenantCtxDep):
    full = await service.UserService.get(ctx.session, ctx.user.id)
    tenants = await service.TenantService.list_for_user(ctx.session, ctx.user.id)
    return schemas.CurrentUser(
        id=full.id,
        email=full.email,
        full_name=full.full_name,
        is_platform_admin=full.is_platform_admin,
        tenants=[
            schemas.CurrentTenant(id=t.id, name=t.name, slug=t.slug, role_code=role)
            for t, role in tenants
        ],
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
    await EntitlementService.ensure(ctx.session, tenant_id, "CanAddUser")
    invitation = await service.TenantService.invite(
        ctx.session,
        tenant_id=tenant_id,
        email=body.email,
        role_code=body.role_code,
        invited_by=ctx.user.id,
    )
    return invitation


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


@tenants_router.post("/{tenant_id}/lifecycle", response_model=TenantLifecycleOut)
async def transition_tenant_lifecycle(
    tenant_id: uuid.UUID,
    body: LifecycleTransitionRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Move a tenant between §48 lifecycle states (suspend, reactivate, offboard)."""
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
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

    return await OffboardingWorker.export_data(ctx.session, tenant_id)


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


# --- §151 hierarchy routes -------------------------------------------------


@hierarchy_router.get("/workspaces", response_model=schemas.WorkspaceListOut)
async def list_workspaces(ctx: TenantContext = Depends(require_permission("settings:read"))):
    rows = await service.HierarchyService.list_workspaces(ctx.session, ctx.tenant_id)
    return schemas.WorkspaceListOut(items=list(rows))


@hierarchy_router.post(
    "/workspaces", response_model=schemas.WorkspaceOut, status_code=201
)
async def create_workspace(
    body: schemas.WorkspaceCreate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.create_workspace(
        ctx.session, ctx.tenant_id, name=body.name, slug=body.slug
    )


@hierarchy_router.get(
    "/workspaces/{workspace_id}", response_model=schemas.WorkspaceOut
)
async def get_workspace(
    workspace_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    return await service.HierarchyService.get_workspace(ctx.session, ctx.tenant_id, workspace_id)


@hierarchy_router.patch(
    "/workspaces/{workspace_id}", response_model=schemas.WorkspaceOut
)
async def update_workspace(
    workspace_id: uuid.UUID,
    body: schemas.WorkspaceUpdate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.update_workspace(
        ctx.session,
        ctx.tenant_id,
        workspace_id,
        name=body.name,
        is_active=body.is_active,
    )


@hierarchy_router.get(
    "/workspaces/{workspace_id}/locations", response_model=schemas.LocationListOut
)
async def list_locations(
    workspace_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    rows = await service.HierarchyService.list_locations(
        ctx.session, ctx.tenant_id, workspace_id
    )
    return schemas.LocationListOut(items=list(rows))


@hierarchy_router.post(
    "/workspaces/{workspace_id}/locations",
    response_model=schemas.LocationOut,
    status_code=201,
)
async def create_location(
    workspace_id: uuid.UUID,
    body: schemas.LocationCreate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.create_location(
        ctx.session,
        ctx.tenant_id,
        workspace_id,
        name=body.name,
        code=body.code,
    )


@hierarchy_router.patch(
    "/locations/{location_id}", response_model=schemas.LocationOut
)
async def update_location(
    location_id: uuid.UUID,
    body: schemas.LocationUpdate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.update_location(
        ctx.session,
        ctx.tenant_id,
        location_id,
        name=body.name,
        code=body.code,
        is_active=body.is_active,
    )


@hierarchy_router.get(
    "/locations/{location_id}/access", response_model=schemas.LocationAccessListOut
)
async def list_location_access(
    location_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    rows = await service.HierarchyService.list_access(
        ctx.session, ctx.tenant_id, location_id
    )
    return schemas.LocationAccessListOut(items=list(rows))


@hierarchy_router.put(
    "/locations/{location_id}/access/{user_id}",
    response_model=schemas.LocationAccessOut,
)
async def grant_location_access(
    location_id: uuid.UUID,
    user_id: uuid.UUID,
    body: schemas.LocationAccessGrant,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.grant_access(
        ctx.session,
        ctx.tenant_id,
        location_id,
        user_id=user_id,
        role_override=body.role_override,
        granted_by=ctx.user.id,
    )


@hierarchy_router.delete(
    "/locations/{location_id}/access/{user_id}", status_code=204
)
async def revoke_location_access(
    location_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    await service.HierarchyService.revoke_access(
        ctx.session, ctx.tenant_id, location_id, user_id=user_id
    )
    return Response(status_code=204)

