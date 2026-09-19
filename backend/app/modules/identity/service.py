"""Identity services — auth, users, tenants, invitations.

Rules:
- Services own the rules; routers stay thin.
- Every service takes an AsyncSession and never commits — the request-level
  transaction (or test harness) owns commit/rollback.
- Refresh tokens are stored hashed (sha256); rotation revokes the old row.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import bind_tenant
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.model_kit import AppendOnlyCreatedAtMixin  # noqa: F401  (convention anchor)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.modules.identity.models import (
    Invitation,
    RefreshToken,
    Role,
    Tenant,
    TenantUser,
    User,
)
from app.modules.identity.schemas import TokenPair
from app.modules.platform.models import AuditLog


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing_email is not None:
            raise ConflictError("email already registered")

        if tenant_slug is None:
            # Auto-derived slug from the email local part; dedupe with a short
            # random suffix on collision so minimal signup can never fail here.
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

        owner_role = (
            await session.execute(select(Role).where(Role.code == "owner"))
        ).scalar_one()
        tenant = Tenant(slug=tenant_slug, name=tenant_name)
        user = User(email=email, password_hash=hash_password(password), full_name=full_name)
        session.add_all([tenant, user])
        await session.flush()
        # Bind the user GUC so the self-access policy on tenant_users allows
        # writing the owner's own membership row.
        await session.execute(
            sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)}
        )
        # We just created this tenant — binding it is legitimate and lets the
        # audit row and membership insert pass RLS.
        await bind_tenant(session, tenant.id)
        session.add(
            TenantUser(
                tenant_id=tenant.id, user_id=user.id, role_id=owner_role.id, is_default=True
            )
        )
        await session.flush()
        AuthService._audit(
            session, None, "auth.registered", "user", str(user.id), tenant_id=tenant.id
        )
        return user, tenant

    @staticmethod
    async def login(
        session,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[TokenPair, User, uuid.UUID | None]:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            # §67: security event — login failure (no PII, ip/ua handled by caller)
            from app.modules.platform.models import SecurityEvent

            domain_part = email.split("@")[-1] if "@" in email else ""
            session.add(
                SecurityEvent(
                    event_type="login_failure",
                    details={"email_domain": domain_part},
                    ip=ip,
                )
            )
        if not user.is_active:
            from app.modules.platform.models import SecurityEvent

            session.add(
                SecurityEvent(
                    event_type="account_disabled_login",
                    tenant_id=None,
                    actor_user_id=user.id,
                    details={"email": user.email},
                    ip=ip,
                )
            )
            raise PermissionDeniedError("account disabled")

        # Membership discovery at login: bind the user GUC so the
        # tenant_users self-access policy lets us see our own rows.
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
        pair = AuthService._issue_pair(session, user, tenant_id, user_agent=user_agent, ip=ip)
        return pair, user, tenant_id

    @staticmethod
    async def refresh(
        session, *, refresh_token: str, user_agent: str | None = None, ip: str | None = None
    ) -> tuple[TokenPair, User, uuid.UUID | None]:
        token_hash = _hash_token(refresh_token)
        row = (
            await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if row is None:
            raise PermissionDeniedError("invalid refresh token")
        if row.revoked_at is not None:
            # Reuse of a revoked token → revoke the whole family (all user tokens).
            from app.modules.platform.models import SecurityEvent

            session.add(
                SecurityEvent(
                    event_type="token_reuse_detected",
                    tenant_id=row.tenant_id,
                    actor_user_id=row.user_id,
                    details={"token_id": str(row.id)},
                    ip=ip,
                )
            )
            await session.execute(
                sa.update(RefreshToken)
                .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=_now())
            )
            raise PermissionDeniedError("refresh token revoked")
        if row.expires_at < _now():
            raise PermissionDeniedError("refresh token expired")

        user = (await session.execute(select(User).where(User.id == row.user_id))).scalar_one()
        if not user.is_active:
            raise PermissionDeniedError("account disabled")
        row.revoked_at = _now()  # rotation
        pair = AuthService._issue_pair(session, user, row.tenant_id, user_agent=user_agent, ip=ip)
        return pair, user, row.tenant_id

    @staticmethod
    async def logout(session, *, refresh_token: str) -> None:
        token_hash = _hash_token(refresh_token)
        row = (
            await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = _now()

    @staticmethod
    async def switch_tenant(
        session, *, user: User, tenant_id: uuid.UUID, refresh_token: str
    ) -> TokenPair:
        membership = (
            await session.execute(
                select(TenantUser).where(
                    TenantUser.user_id == user.id, TenantUser.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            raise PermissionDeniedError("not a member of this tenant")
        old_hash = _hash_token(refresh_token)
        row = (
            await session.execute(select(RefreshToken).where(RefreshToken.token_hash == old_hash))
        ).scalar_one_or_none()
        if row is not None:
            row.revoked_at = _now()
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
        claims = {"tenant_id": str(tenant_id)} if tenant_id else {}
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
    def _audit(session, actor_user_id, action, resource_type, resource_id, tenant_id=None):
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id),
            )
        )


class TenantService:
    @staticmethod
    async def list_for_user(session, user_id: uuid.UUID) -> list[tuple[Tenant, str | None]]:
        rows = (
            await session.execute(
                select(Tenant, Role.code)
                .join(TenantUser, TenantUser.tenant_id == Tenant.id)
                .outerjoin(Role, Role.id == TenantUser.role_id)
                .where(TenantUser.user_id == user_id, Tenant.is_active.is_(True))
            )
        ).all()
        return [(tenant, role_code) for tenant, role_code in rows]

    @staticmethod
    async def invite(
        session, *, tenant_id: uuid.UUID, email: str, role_code: str, invited_by: uuid.UUID
    ) -> Invitation:
        role = (
            await session.execute(select(Role).where(Role.code == role_code))
        ).scalar_one_or_none()
        if role is None:
            raise ValidationError(f"unknown role: {role_code}")
        pending = (
            await session.execute(
                select(Invitation).where(
                    Invitation.tenant_id == tenant_id,
                    Invitation.email == email,
                    Invitation.status == "pending",
                )
            )
        ).scalar_one_or_none()
        if pending is not None:
            raise ConflictError("invitation already pending for this email")
        invitation = Invitation(
            tenant_id=tenant_id,
            email=email,
            role_id=role.id,
            invited_by_user_id=invited_by,
            token=secrets.token_urlsafe(24),
            status="pending",  # explicit: server_default is invisible in the identity map
            expires_at=_now() + timedelta(days=7),
        )
        session.add(invitation)
        return invitation

    @staticmethod
    async def revoke_invitation(
        session, *, tenant_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> Invitation:
        invitation = (
            await session.execute(
                select(Invitation).where(
                    Invitation.id == invitation_id,
                    Invitation.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise NotFoundError("invitation not found")
        if invitation.status != "pending":
            raise ConflictError("invitation is not pending")
        invitation.status = "revoked"
        return invitation

    @staticmethod
    async def accept_invitation(
        session, *, token: str, password: str, full_name: str
    ) -> tuple[User, Invitation]:
        invitation = (
            await session.execute(select(Invitation).where(Invitation.token == token))
        ).scalar_one_or_none()
        if invitation is None:
            raise NotFoundError("invitation not found")
        if invitation.status != "pending":
            raise ConflictError("invitation already used or revoked")
        if invitation.expires_at < _now():
            invitation.status = "expired"
            from app.modules.platform.models import SecurityEvent

            session.add(
                SecurityEvent(
                    event_type="invitation_expired",
                    tenant_id=invitation.tenant_id,
                    actor_user_id=None,
                    details={"email": invitation.email, "invitation_id": str(invitation.id)},
                    ip=None,
                )
            )
            raise ValidationError("invitation expired")
        existing = (
            await session.execute(select(User).where(User.email == invitation.email))
        ).scalar_one_or_none()
        if existing is not None:
            user = existing
            membership_exists = (
                await session.execute(
                    select(TenantUser).where(
                        TenantUser.user_id == user.id,
                        TenantUser.tenant_id == invitation.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if membership_exists is not None:
                raise ConflictError("already a member of this tenant")
        else:
            user = User(
                email=invitation.email,
                password_hash=hash_password(password),
                full_name=full_name,
            )
            session.add(user)
            await session.flush()
        session.add(
            TenantUser(
                tenant_id=invitation.tenant_id,
                user_id=user.id,
                role_id=invitation.role_id,
                is_default=False,
            )
        )
        invitation.status = "accepted"
        invitation.accepted_at = _now()
        return user, invitation


class UserService:
    @staticmethod
    async def get(session, user_id: uuid.UUID) -> User:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise NotFoundError("user not found")
        return user

    @staticmethod
    async def update_profile(session, user_id: uuid.UUID, *, full_name: str | None = None) -> User:
        user = await UserService.get(session, user_id)
        if full_name is not None:
            user.full_name = full_name
        return user

    @staticmethod
    async def set_active(session, user_id: uuid.UUID, *, is_active: bool) -> User:
        user = await UserService.get(session, user_id)
        user.is_active = is_active
        return user

    @staticmethod
    async def decode_access(token: str) -> dict:
        """Decode + sanity-check an access token (type claim)."""
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise PermissionDeniedError("wrong token type")
        return payload
