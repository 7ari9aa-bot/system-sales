"""AuthService — registration, login, MFA, tokens, password reset, email verification.

Extracted from the original monolithic service.py.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy import select

from app.core import auth_lockout
from app.core.config import get_settings
from app.core.db import bind_tenant
from app.core.errors import PermissionDeniedError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password_async,
    verify_password_async,
)
from app.modules.identity.models import (
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
    Role,
    Tenant,
    TenantUser,
    User,
)
from app.modules.identity.schemas import TokenPair
from app.modules.identity.services._common import (
    _REFRESH_REUSE_GRACE_SECONDS,
    EmailAlreadyRegistered,
    _dummy_password_hash,
    _hash_token,
    _lockout_op,
    _now,
    _record_audit,
    _record_security_event,
    _revoke_family_on_reuse,
)

# Late import to avoid circular: lifecycle uses AuthService indirectly via
# STATE_POLICIES which is defined in the lifecycle sub-module.
_STATE_POLICIES = None


def _get_state_policies():
    global _STATE_POLICIES
    if _STATE_POLICIES is None:
        from app.modules.identity.services.lifecycle import STATE_POLICIES
        _STATE_POLICIES = STATE_POLICIES
    return _STATE_POLICIES


class AuthService:
    @staticmethod
    async def register(
        session,
        *,
        tenant_name: str | None,
        tenant_slug: str | None,
        email: str,
        password: str,
        full_name: str | None,
    ) -> tuple[User, Tenant]:
        from app.core.errors import ConflictError

        local_part = email.split("@", 1)[0]
        # Display name ignores plus-addressing and trailing unique suffixes
        # ("hamed.adel+a12@x.com", "hamed.adel-3f2a1b@x.com" -> "Hamed Adel").
        segments = [seg for seg in re.split(r"[._-]+", local_part.split("+", 1)[0]) if seg]
        if len(segments) > 1 and re.fullmatch(r"\d+|[0-9a-f]{6,}", segments[-1]):
            segments = segments[:-1]
        display_name = " ".join(segments).strip().title() or local_part
        tenant_name = tenant_name or display_name
        full_name = full_name or display_name

        existing_email = (
            await session.execute(select(User).where(User.email == email.strip().lower()))
        ).scalar_one_or_none()
        if existing_email is not None:
            await AuthService.queue_email_verification(session, user=existing_email)
            raise EmailAlreadyRegistered("email already registered")

        if tenant_slug is None:
            base = re.sub(r"[^a-z0-9]+", "-", local_part.lower()).strip("-")[:40] or "workspace"
            tenant_slug = base
            for _attempt in range(6):
                taken = (
                    await session.execute(select(Tenant).where(Tenant.slug == tenant_slug))
                ).scalar_one_or_none()
                if taken is None:
                    break
                tenant_slug = f"{base}-{uuid.uuid4().hex[:6]}"
            else:
                raise ConflictError("tenant slug already taken")
        else:
            existing_slug = (
                await session.execute(select(Tenant).where(Tenant.slug == tenant_slug))
            ).scalar_one_or_none()
            if existing_slug is not None:
                raise ConflictError("tenant slug already taken")

        owner_role = (await session.execute(select(Role).where(Role.code == "owner"))).scalar_one()
        tenant = Tenant(slug=tenant_slug, name=tenant_name)
        user = User(
            email=email.strip().lower(),
            password_hash=await hash_password_async(password),
            full_name=full_name,
        )
        session.add_all([tenant, user])
        await session.flush()
        await session.execute(
            sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)}
        )
        await bind_tenant(session, tenant.id)
        session.add(
            TenantUser(tenant_id=tenant.id, user_id=user.id, role_id=owner_role.id, is_default=True)
        )
        await session.flush()
        from app.modules.identity.bootstrap import seed_tenant_defaults

        await seed_tenant_defaults(session, tenant.id)
        from app.core.tenancy import dispatch_tenant_created_hooks

        await dispatch_tenant_created_hooks(session, tenant.id)
        await AuthService.queue_email_verification(session, user=user)
        await AuthService._audit(
            session, None, "auth.registered", "user", str(user.id), tenant_id=tenant.id
        )
        return user, tenant

    @staticmethod
    async def _assert_tenant_allows_login(
        session,
        tenant_id: uuid.UUID | None,
        *,
        user_id: uuid.UUID | None = None,
        ip: str | None = None,
    ) -> None:
        """§48: a suspended or deleted tenant cannot sign in."""
        if tenant_id is None:
            return
        state = (
            await session.execute(sa.select(Tenant.lifecycle_state).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        policy = _get_state_policies().get(state) if state else None
        if policy is None or not policy.allows_login:
            await _record_security_event(
                "tenant_login_blocked",
                details={"lifecycle_state": state or "unknown"},
                ip=ip,
                actor_user_id=user_id,
            )
            raise PermissionDeniedError(
                f"workspace is {state or 'unavailable'} — sign-in is disabled"
            )

    @staticmethod
    async def login(
        session,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[TokenPair, User, uuid.UUID | None]:
        lock_status = await _lockout_op(auth_lockout.check, ip=ip, email=email)
        if lock_status is not None and lock_status.locked:
            raise PermissionDeniedError("too many failed sign-in attempts — try again later")
        user = (
            await session.execute(select(User).where(User.email == email.strip().lower()))
        ).scalar_one_or_none()
        password_ok = await verify_password_async(
            password,
            user.password_hash if user is not None else await _dummy_password_hash(),
        )
        if user is None or not password_ok:
            await _record_security_event(
                "login_failure",
                details={"email_domain": email.split("@")[-1] if "@" in email else ""},
                ip=ip,
            )
            await _lockout_op(auth_lockout.record_failure, ip=ip, email=email)
            raise PermissionDeniedError("invalid credentials")

        await _lockout_op(auth_lockout.reset, ip=ip, email=email)

        if not user.is_active:
            await _record_security_event(
                "account_disabled_login",
                details={"email_domain": email.split("@")[-1] if "@" in email else ""},
                ip=ip,
                actor_user_id=user.id,
            )
            raise PermissionDeniedError("account disabled")

        await session.execute(
            sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)}
        )
        membership = (
            await session.execute(
                select(TenantUser)
                .where(TenantUser.user_id == user.id)
                .order_by(TenantUser.is_default.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        tenant_id = membership.tenant_id if membership else None
        if membership is not None:
            try:
                await AuthService._assert_tenant_allows_login(
                    session, tenant_id, user_id=user.id, ip=ip
                )
            except PermissionDeniedError:
                candidates = (
                    (
                        await session.execute(
                            select(TenantUser.tenant_id).where(
                                TenantUser.user_id == user.id,
                                TenantUser.tenant_id != tenant_id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                tenant_id = None
                for candidate in candidates:
                    try:
                        await AuthService._assert_tenant_allows_login(
                            session, candidate, user_id=user.id, ip=ip
                        )
                    except PermissionDeniedError:
                        continue
                    tenant_id = candidate
                    break
                if tenant_id is None:
                    raise
        else:
            await AuthService._assert_tenant_allows_login(session, None, user_id=user.id, ip=ip)
        from app.core.mfa import MfaRequiredError, is_mfa_enabled, start_challenge

        if await is_mfa_enabled(session, user_id=user.id):
            challenge_id = await start_challenge(
                user.id, tenant_id, auth_version=getattr(user, "auth_version", 0)
            )
            raise MfaRequiredError(challenge_id)
        pair = AuthService._issue_pair(session, user, tenant_id, user_agent=user_agent, ip=ip)
        return pair, user, tenant_id

    @staticmethod
    async def mfa_verify(
        session,
        *,
        challenge_id: str,
        code: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[TokenPair, User, uuid.UUID | None]:
        """§146 second step: a verified challenge + TOTP code mints the pair."""
        from app.core.mfa import check_challenge_code

        user_id, tenant_id = await check_challenge_code(
            session, challenge_id=challenge_id, code=code, ip=ip
        )
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None or not user.is_active:
            raise PermissionDeniedError("account not available")
        await AuthService._assert_tenant_allows_login(session, tenant_id, user_id=user.id, ip=ip)
        pair = AuthService._issue_pair(session, user, tenant_id, user_agent=user_agent, ip=ip)
        return pair, user, tenant_id

    @staticmethod
    async def refresh(
        session, *, refresh_token: str, user_agent: str | None = None, ip: str | None = None
    ) -> tuple[TokenPair, User, uuid.UUID | None]:
        token_hash = _hash_token(refresh_token)
        row = (
            await session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise PermissionDeniedError("invalid refresh token")
        if row.revoked_at is not None:
            age_seconds = (_now() - row.revoked_at).total_seconds()
            if age_seconds > _REFRESH_REUSE_GRACE_SECONDS:
                await _revoke_family_on_reuse(row.user_id)
                await _record_security_event(
                    "token_reuse_detected",
                    details={"token_id": str(row.id)},
                    ip=ip,
                    tenant_id=row.tenant_id,
                    actor_user_id=row.user_id,
                )
                raise PermissionDeniedError("refresh token revoked")
            await _record_security_event(
                "token_refresh_race_tolerated",
                details={"token_id": str(row.id), "age_seconds": round(age_seconds, 3)},
                ip=ip,
                tenant_id=row.tenant_id,
                actor_user_id=row.user_id,
            )
        if row.expires_at < _now():
            raise PermissionDeniedError("refresh token expired")

        user = (await session.execute(select(User).where(User.id == row.user_id))).scalar_one()
        if not user.is_active:
            raise PermissionDeniedError("account disabled")
        await AuthService._assert_tenant_allows_login(
            session, row.tenant_id, user_id=user.id, ip=ip
        )
        if row.revoked_at is None:
            row.revoked_at = _now()  # rotation
        pair = AuthService._issue_pair(session, user, row.tenant_id, user_agent=user_agent, ip=ip)
        return pair, user, row.tenant_id

    @staticmethod
    async def logout(session, *, refresh_token: str) -> None:
        token_hash = _hash_token(refresh_token)
        row = (
            await session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
            )
        ).scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = _now()

    @staticmethod
    async def request_password_reset(session, *, email: str) -> None:
        """Queue an account-recovery email without exposing account existence."""
        now = _now()
        user = (
            await session.execute(
                select(User).where(User.email == email.strip().lower()).with_for_update()
            )
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            return

        recent = (
            await session.execute(
                select(PasswordResetToken.id)
                .where(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.requested_at > now - timedelta(seconds=60),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if recent is not None:
            return

        await session.execute(
            sa.update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(consumed_at=now, encrypted_token="", lease_expires_at=None)
        )

        from app.core.secrets import get_envelope_store

        token = secrets.token_urlsafe(32)
        session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_token(token),
                encrypted_token=get_envelope_store().encrypt(token),
                requested_at=now,
                expires_at=now + timedelta(hours=1),
                next_attempt_at=now,
            )
        )
        await session.flush()

    @staticmethod
    async def reset_password(session, *, token: str, password: str) -> None:
        """Consume one valid recovery link and invalidate every old session."""
        now = _now()
        row = (
            await session.execute(
                select(PasswordResetToken)
                .where(PasswordResetToken.token_hash == _hash_token(token))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.consumed_at is not None or row.expires_at <= now:
            raise ValidationError("password reset link is invalid or expired")

        user = (
            await session.execute(select(User).where(User.id == row.user_id).with_for_update())
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            raise ValidationError("password reset link is invalid or expired")

        user.password_hash = await hash_password_async(password)
        user.auth_version = int(user.auth_version or 0) + 1
        user.email_verified = True
        row.consumed_at = now
        row.encrypted_token = ""
        row.lease_expires_at = None

        await session.execute(
            sa.update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await session.execute(
            sa.update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.id != row.id,
                PasswordResetToken.consumed_at.is_(None),
            )
            .values(consumed_at=now, encrypted_token="", lease_expires_at=None)
        )
        await session.flush()

    # -- email verification (audit finding 3: account pre-hijack) -----------

    @staticmethod
    async def queue_email_verification(session, *, user: User) -> bool:
        """Queue a verification email for `user`; False when deliberately skipped."""
        if user.email_verified:
            return False
        now = _now()
        recent = (
            await session.execute(
                select(EmailVerificationToken.id)
                .where(
                    EmailVerificationToken.user_id == user.id,
                    EmailVerificationToken.requested_at > now - timedelta(seconds=60),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if recent is not None:
            return False

        await session.execute(
            sa.update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.consumed_at.is_(None),
            )
            .values(consumed_at=now, encrypted_token="", lease_expires_at=None)
        )

        from app.core.secrets import get_envelope_store

        token = secrets.token_urlsafe(32)
        session.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=_hash_token(token),
                encrypted_token=get_envelope_store().encrypt(token),
                requested_at=now,
                expires_at=now + timedelta(hours=24),
                next_attempt_at=now,
            )
        )
        await session.flush()
        return True

    @staticmethod
    async def request_email_verification(session, *, email: str) -> None:
        """The resend endpoint's engine: neutral, like request_password_reset."""
        user = (
            await session.execute(select(User).where(User.email == email.strip().lower()))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            return
        await AuthService.queue_email_verification(session, user=user)

    @staticmethod
    async def verify_email(session, *, token: str) -> User:
        """Consume one verification link and mark the account's email proven."""
        now = _now()
        row = (
            await session.execute(
                select(EmailVerificationToken)
                .where(EmailVerificationToken.token_hash == _hash_token(token))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.consumed_at is not None or row.expires_at <= now:
            raise ValidationError("email verification link is invalid or expired")

        user = (
            await session.execute(select(User).where(User.id == row.user_id).with_for_update())
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            raise ValidationError("email verification link is invalid or expired")

        user.email_verified = True
        row.consumed_at = now
        row.encrypted_token = ""
        row.lease_expires_at = None
        await session.execute(
            sa.update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.id != row.id,
                EmailVerificationToken.consumed_at.is_(None),
            )
            .values(consumed_at=now, encrypted_token="", lease_expires_at=None)
        )
        await session.flush()
        return user

    @staticmethod
    async def switch_tenant(
        session, *, user: User, tenant_id: uuid.UUID, refresh_token: str
    ) -> TokenPair:
        if not user.is_active:
            raise PermissionDeniedError("account disabled")
        await session.execute(
            sa.text("SELECT set_config(:guc, :user_id, true)"),
            {"guc": "app.user_id", "user_id": str(user.id)},
        )
        membership = (
            await session.execute(
                select(TenantUser).where(
                    TenantUser.user_id == user.id, TenantUser.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            await _record_security_event(
                "cross_tenant_access_denied",
                details={"requested_tenant_id": str(tenant_id)},
                actor_user_id=user.id,
            )
            raise PermissionDeniedError("not a member of this tenant")
        await AuthService._assert_tenant_allows_login(session, tenant_id, user_id=user.id)
        if not refresh_token:
            raise PermissionDeniedError("no refresh token supplied")
        old_hash = _hash_token(refresh_token)
        now = _now()
        row = (
            await session.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == old_hash, RefreshToken.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None or row.expires_at <= now:
            raise PermissionDeniedError("invalid or expired refresh token")
        row.revoked_at = now
        return AuthService._issue_pair(session, user, tenant_id)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _issue_pair(
        session,
        user: User,
        tenant_id: uuid.UUID | None,
        *,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> TokenPair:
        settings = get_settings()
        claims: dict = {"tenant_id": str(tenant_id)} if tenant_id else {}
        claims["auth_version"] = int(getattr(user, "auth_version", 0) or 0)
        if getattr(user, "is_platform_admin", False):
            claims["is_platform_admin"] = True
        access = create_access_token(str(user.id), claims)
        refresh = create_refresh_token(str(user.id), claims)
        session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=_hash_token(refresh),
                tenant_id=tenant_id,
                expires_at=_now() + timedelta(seconds=settings.refresh_token_ttl_seconds),
                user_agent=user_agent,
                ip=ip,
            )
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.access_token_ttl_seconds,
        )

    @staticmethod
    async def _audit(session, actor_user_id, action, resource_type, resource_id, tenant_id=None):
        await _record_audit(session, tenant_id, actor_user_id, action, resource_type, resource_id)
