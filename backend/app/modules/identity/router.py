"""Identity + auth HTTP routes."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import PermissionDeniedError, ValidationError
from app.modules.billing.service import EntitlementService
from app.modules.identity import cookies, schemas, service
from app.modules.identity.deps import (
    CurrentUserDep,
    DbSession,
    TenantContext,
    TenantCtxDep,
    require_permission,
)
from app.modules.identity.models import Role

router = APIRouter(tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])
tenants_router = APIRouter(prefix="/tenants", tags=["tenants"])
# §151 — the tenant's hierarchy surface. Tenancy comes from the request
# context only (no tenant ids in paths): every handler passes ctx.tenant_id
# into the service, which filters with it AND runs under the bound RLS GUC.
hierarchy_router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])

_CLIENT_TTL = 60 * 60 * 24 * 30  # refresh cookie life if cookie mode used


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


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("user-agent"), request.client.host if request.client else None


@router.post("/auth/register", status_code=202)
async def register(body: schemas.RegisterRequest, session: DbSession, response: Response):
    """Signup, neutral on purpose (external audit, account pre-hijack).

    The same 202 body is returned whether the address was fresh or already
    taken: a fresh registration creates an UNVERIFIED account + tenant and
    queues a verification email; a taken address re-queues that verification
    (throttled) and changes nothing. The previous 201 + CurrentUser response
    — and the 409 "email already registered" it replaced for duplicates —
    were a user-enumeration oracle, and the duplicate path was half of the
    pre-hijack attack (register a victim's address first, then let an
    invitation to that address bind the victim's role to the attacker's
    account). CONTRACT CHANGE: callers that read the registered user's id from
    this response must move to /auth/me after sign-in.
    """
    try:
        await service.AuthService.register(
            session,
            tenant_name=body.tenant_name,
            tenant_slug=body.tenant_slug,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
        )
    except service.EmailAlreadyRegistered:
        # The service already queued the re-verification on its way out. The
        # response must not distinguish — that is the whole point.
        pass
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Check your email to confirm your account before signing in."}


@router.post("/auth/verify-email", status_code=204)
async def verify_email(
    body: schemas.VerifyEmailRequest, session: DbSession, response: Response
):
    """Consume a verification link and mark the account's email proven.

    Verification is what accept_invitation requires of an existing account
    before it will bind a membership to it — the fact that closes the
    account pre-hijack attack.
    """
    await service.AuthService.verify_email(session, token=body.token)
    response.headers["Cache-Control"] = "no-store"
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/auth/resend-verification", status_code=202)
async def resend_verification(
    body: schemas.ResendVerificationRequest, session: DbSession, response: Response
):
    """Re-queue the verification email — neutral, like password-reset/request.

    The same 202 is returned for known, unknown, inactive, verified and
    recently-throttled addresses, so the endpoint discloses nothing about
    account existence or verification state. Throttling (60s) lives in the
    service; the delivery worker picks the row up like any other token email.
    """
    await service.AuthService.request_email_verification(session, email=str(body.email))
    response.headers["Cache-Control"] = "no-store"
    return {
        "message": "If the account needs verification, a confirmation email "
        "will be sent shortly."
    }


@router.post("/auth/login", response_model=schemas.TokenPair)
async def login(
    body: schemas.LoginRequest, request: Request, session: DbSession, response: Response
):
    user_agent, ip = _client_meta(request)
    pair, _user, _tenant_id = await service.AuthService.login(
        session, email=body.email, password=body.password, user_agent=user_agent, ip=ip
    )
    # The pair still rides the body (desktop/Bearer flow unchanged); the
    # cookies are the XSS-hardened delivery the dashboard adopts.
    cookies.set_auth_cookies(response, pair.access_token, pair.refresh_token)
    return pair


@router.post("/auth/password-reset/request", status_code=202)
async def request_password_reset(
    body: schemas.PasswordResetRequest,
    session: DbSession,
    response: Response,
):
    """Queue a single-use account recovery email.

    The same 202 response is returned for known, unknown, inactive, and
    recently-throttled accounts to avoid an email-address enumeration oracle.
    """
    await service.AuthService.request_password_reset(session, email=str(body.email))
    response.headers["Cache-Control"] = "no-store"
    return {
        "message": "If the account exists, password reset instructions will be sent shortly."
    }


@router.post("/auth/password-reset/confirm", status_code=204)
async def confirm_password_reset(
    body: schemas.PasswordResetConfirmRequest,
    session: DbSession,
    response: Response,
):
    """Consume a reset link and revoke all sessions issued before the reset."""
    await service.AuthService.reset_password(
        session, token=body.token, password=body.password
    )
    response.headers["Cache-Control"] = "no-store"
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/auth/refresh", response_model=schemas.TokenPair)
async def refresh(
    body: schemas.RefreshRequest, request: Request, session: DbSession, response: Response
):
    user_agent, ip = _client_meta(request)
    refresh_token = body.refresh_token or request.cookies.get(cookies.REFRESH_COOKIE)
    if not refresh_token:
        raise PermissionDeniedError("no refresh token supplied")
    pair, _user, _tenant_id = await service.AuthService.refresh(
        session, refresh_token=refresh_token, user_agent=user_agent, ip=ip
    )
    cookies.set_auth_cookies(response, pair.access_token, pair.refresh_token)
    return pair


@router.post("/auth/logout", status_code=204)
async def logout(
    body: schemas.RefreshRequest, request: Request, session: DbSession, response: Response
):
    refresh_token = body.refresh_token or request.cookies.get(cookies.REFRESH_COOKIE)
    if refresh_token:
        await service.AuthService.logout(session, refresh_token=refresh_token)
    cookies.clear_auth_cookies(response)
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
    body: schemas.SwitchTenantRequest,
    request: Request,
    user: CurrentUserDep,
    session: DbSession,
    response: Response,
):
    # Same token-supply contract as refresh/logout below: the body wins, the
    # refresh cookie (path=/api/v1/auth, which covers this route) is the
    # browser flow's fallback. Without it a cookie-only caller — body empty —
    # handed the service a None token, which died hashing (a 500) instead of
    # being refused (a 403).
    refresh_token = body.refresh_token or request.cookies.get(cookies.REFRESH_COOKIE)
    pair = await service.AuthService.switch_tenant(
        session, user=user, tenant_id=body.tenant_id, refresh_token=refresh_token
    )
    cookies.set_auth_cookies(response, pair.access_token, pair.refresh_token)
    return pair


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
async def mfa_verify(
    body: MfaVerifyRequest, request: Request, session: DbSession, response: Response
):
    """§146: complete an MFA-challenged login (challenge is single-use)."""
    user_agent, ip = _client_meta(request)
    pair, _user, _tenant_id = await service.AuthService.mfa_verify(
        session,
        challenge_id=body.challenge_id,
        code=body.code,
        user_agent=user_agent,
        ip=ip,
    )
    cookies.set_auth_cookies(response, pair.access_token, pair.refresh_token)
    return pair


@router.post("/auth/mfa/enroll", response_model=MfaEnrollOut, status_code=201)
async def mfa_enroll(body: MfaEnrollRequest, user: CurrentUserDep, session: DbSession):
    """§146: start TOTP enrollment — confirm with a code before it challenges.

    Step-up (§146): the password is re-verified before a secret is minted, so
    a stolen access token cannot be used to bind an attacker's authenticator.
    """
    from app.core.mfa import enroll_mfa
    from app.core.security import verify_password_async

    row = await service.UserService.get(session, user.id)
    if not await verify_password_async(body.password, row.password_hash):
        raise PermissionDeniedError("password step-up failed — re-authenticate first")

    enrolled = await enroll_mfa(session, user_id=user.id)
    return MfaEnrollOut(secret=enrolled.secret, otpauth_url=enrolled.otpauth_url)


@router.post("/auth/mfa/confirm")
async def mfa_confirm(
    body: MfaCodeRequest, request: Request, user: CurrentUserDep, session: DbSession
):
    """§146: prove possession → MFA enabled; backup codes are returned ONCE.

    Wrong codes are throttled (core/mfa) and every rejection emits a §67
    security event, so the request IP rides along for the audit trail.
    """
    from app.core.mfa import confirm_mfa

    _user_agent, ip = _client_meta(request)
    codes = await confirm_mfa(session, user_id=user.id, code=body.code, ip=ip)
    return {"backup_codes": codes}


@router.post("/auth/mfa/disable", status_code=204)
async def mfa_disable(
    body: MfaDisableRequest, request: Request, user: CurrentUserDep, session: DbSession
):
    """§146: disable with a current TOTP code OR a one-time backup code.

    Re-verification is mandatory and wrong codes are throttled (core/mfa);
    rejections emit §67 security events with the request IP.
    """
    from app.core.mfa import disable_mfa

    _user_agent, ip = _client_meta(request)
    await disable_mfa(
        session, user_id=user.id, code=body.code, backup_code=body.backup_code, ip=ip
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
        await ctx.session.execute(
            sa.select(Role.code).where(Role.id == invitation.role_id)
        )
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
                "re-authentication (your password) is required to request "
                "offboarding"
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
        raise PermissionDeniedError(
            f"tenant admins may only request offboarding, not {body.state}"
        )
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


class TenantCurrencyRequest(BaseModel):
    currency: str = Field(min_length=3, max_length=3)


class TenantTimezoneRequest(BaseModel):
    #: An empty string clears the setting (back to the deployment zone), which
    #: is why the field is optional rather than required-and-non-empty.
    timezone: str | None = Field(default=None, max_length=64)


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
            "Content-Disposition": (
                f'attachment; filename="sales-os-export-{tenant_id}.json"'
            ),
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

