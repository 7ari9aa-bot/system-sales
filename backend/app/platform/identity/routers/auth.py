"""Identity auth HTTP routes: login, signup, tokens, MFA, reset, invitations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.core import turnstile
from app.core.config import get_settings
from app.core.errors import PermissionDeniedError
from app.core.mfa import is_mfa_enabled
from app.platform.identity import avatar, cookies, schemas, service
from app.platform.identity.deps import CurrentUserDep, DbSession
from app.platform.identity.routers._deps import _client_meta, bind_tenant_user

router = APIRouter(tags=["auth"])


# ---------- §146 MFA (TOTP) Models ----------


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


# ---------- Auth Endpoints ----------


@router.post("/auth/register", status_code=202)
async def register(
    body: schemas.RegisterRequest, request: Request, session: DbSession, response: Response
):
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
    # Bot gate BEFORE any work or any account lookup, and identical for every
    # address, so it can never reveal whether the address is already taken.
    await turnstile.verify(body.captcha_token, ip=_client_meta(request)[1])
    try:
        await service.AuthService.register(
            session,
            tenant_name=body.tenant_name or body.shop_name,
            tenant_slug=body.tenant_slug,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            visitor_id=body.visitor_id,
            country_code=body.country_code,
            terms_accepted=body.terms_accepted,
            offer_activity_setup=True,
        )
    except service.EmailAlreadyRegistered:
        # The service already queued the re-verification on its way out. The
        # response must not distinguish — that is the whole point.
        pass
    response.headers["Cache-Control"] = "no-store"
    return {"message": "Check your email to confirm your account before signing in."}


@router.post("/auth/verify-email", status_code=204)
async def verify_email(body: schemas.VerifyEmailRequest, session: DbSession, response: Response):
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
    body: schemas.ResendVerificationRequest,
    request: Request,
    session: DbSession,
    response: Response,
):
    """Re-queue the verification email — neutral, like password-reset/request.

    The same 202 is returned for known, unknown, inactive, verified and
    recently-throttled addresses, so the endpoint discloses nothing about
    account existence or verification state. Throttling (60s) lives in the
    service; the delivery worker picks the row up like any other token email.
    """
    await turnstile.verify(body.captcha_token, ip=_client_meta(request)[1])
    await service.AuthService.request_email_verification(session, email=str(body.email))
    response.headers["Cache-Control"] = "no-store"
    return {
        "message": "If the account needs verification, a confirmation email will be sent shortly."
    }


@router.post("/auth/login", response_model=schemas.TokenPair)
async def login(
    body: schemas.LoginRequest, request: Request, session: DbSession, response: Response
):
    user_agent, ip = _client_meta(request)
    # A challenge is demanded only once this (ip, email) has already failed a few
    # times, so a normal sign-in never sees one and the desktop/API clients keep
    # working. The count is the lockout counter, which sits below its threshold.
    if turnstile.enabled():
        failures = await service.AuthService.recent_login_failures(ip=ip, email=body.email)
        if failures >= get_settings().turnstile_login_after_failures:
            await turnstile.verify(body.captcha_token, ip=ip)
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
    request: Request,
    session: DbSession,
    response: Response,
):
    """Queue a single-use account recovery email.

    The same 202 response is returned for known, unknown, inactive, and
    recently-throttled accounts to avoid an email-address enumeration oracle.
    """
    await turnstile.verify(body.captcha_token, ip=_client_meta(request)[1])
    await service.AuthService.request_password_reset(session, email=str(body.email))
    response.headers["Cache-Control"] = "no-store"
    return {"message": "If the account exists, password reset instructions will be sent shortly."}


@router.post("/auth/password-reset/confirm", status_code=204)
async def confirm_password_reset(
    body: schemas.PasswordResetConfirmRequest,
    session: DbSession,
    response: Response,
):
    """Consume a reset link and revoke all sessions issued before the reset."""
    await service.AuthService.reset_password(session, token=body.token, password=body.password)
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
        avatar_url=avatar.read_url(full.avatar_url),
        mfa_enabled=await is_mfa_enabled(session, user_id=user.id),
        tenants=[
            schemas.CurrentTenant(
                id=t.id, name=t.name, slug=t.slug, role_code=role, currency=t.currency
            )
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
    await disable_mfa(session, user_id=user.id, code=body.code, backup_code=body.backup_code, ip=ip)
    return Response(status_code=204)


# ---------- changing the password, and the devices that are signed in -------


def _refresh_cookie(request: Request) -> str | None:
    return request.cookies.get(cookies.REFRESH_COOKIE)


def _current_token_hash(request: Request) -> str | None:
    """The caller's own chain, so a screen can say "this device" and keep it alive."""
    from app.platform.identity.services._common import _hash_token

    token = _refresh_cookie(request)
    return _hash_token(token) if token else None


@router.post("/auth/password/change", status_code=204)
async def change_password(
    body: schemas.ChangePasswordRequest,
    request: Request,
    user: CurrentUserDep,
    session: DbSession,
):
    """Change the password of the signed-in account and sign out everywhere else.

    Deliberately not a reset: the current password must be presented, so a
    borrowed session cannot lock the owner out. The device that asked stays
    signed in; every other chain is closed.
    """
    await service.AuthService.change_password(
        session,
        user_id=user.id,
        current_password=body.current_password,
        new_password=body.new_password,
        keep_token_hash=_current_token_hash(request),
        ip=_client_meta(request)[1],
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/auth/sessions", response_model=list[schemas.SignedInDeviceOut])
async def list_sessions(request: Request, user: CurrentUserDep, session: DbSession):
    """Every device signed in to this account, with the caller's own one marked."""
    devices = await service.SignedInDeviceService.list_devices(
        session, user.id, current_token_hash=_current_token_hash(request)
    )
    return devices


@router.post("/auth/sessions/revoke-others", response_model=schemas.RevokedSessionsOut)
async def revoke_other_sessions(request: Request, user: CurrentUserDep, session: DbSession):
    """Sign out every device except the one asking."""
    revoked = await service.SignedInDeviceService.revoke_others(
        session, user.id, current_token_hash=_current_token_hash(request)
    )
    return schemas.RevokedSessionsOut(revoked=revoked)


@router.post("/auth/sessions/revoke-all", response_model=schemas.RevokedSessionsOut)
async def revoke_all_sessions(
    request: Request, response: Response, user: CurrentUserDep, session: DbSession
):
    """Sign out everywhere, this device included, and clear the session cookies."""
    revoked = await service.SignedInDeviceService.revoke_all(session, user.id)
    cookies.clear_auth_cookies(response)
    return schemas.RevokedSessionsOut(revoked=revoked)


@router.post("/auth/sessions/{session_id}/revoke", status_code=204)
async def revoke_one_session(
    session_id: uuid.UUID, user: CurrentUserDep, session: DbSession
) -> Response:
    """Close one chain. A chain that is not this account's is a 404."""
    await service.SignedInDeviceService.revoke_one(session, user.id, session_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


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
            schemas.CurrentTenant(
                id=t.id, name=t.name, slug=t.slug, role_code=role, currency=t.currency
            )
            for t, role in tenants
        ],
    )
