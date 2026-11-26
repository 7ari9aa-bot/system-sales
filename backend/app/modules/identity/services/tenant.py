"""TenantService — listing tenants, invitations, and invitation acceptance.

Extracted from the original monolithic service.py.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.security import hash_password_async
from app.modules.identity.models import (
    Invitation,
    Role,
    Tenant,
    TenantUser,
    User,
)
from app.modules.identity.services._common import (
    _now,
    _record_security_event,
)


class TenantService:
    # Tenant role hierarchy — the ORDER of the roles provision.py seeds.
    _ROLE_RANK: dict[str, int] = {"owner": 3, "manager": 2, "staff": 1}

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
        session,
        *,
        tenant_id: uuid.UUID,
        email: str,
        role_code: str | None,
        invited_by: uuid.UUID,
        inviter_role_code: str | None = None,
        inviter_is_platform_admin: bool = False,
    ) -> Invitation:
        email = email.strip().lower()

        # team.allow_member_invites: a tenant that disabled invites rejects
        # here, before any row is written. Reads via app.core.settings_read
        # to avoid the import cycle (identity → settings would grow the SCC).
        from app.core.settings_read import resolve_settings

        settings = await resolve_settings(
            session,
            tenant_id,
            ["team.allow_member_invites", "team.default_role"],
        )
        if settings["team.allow_member_invites"] is False:
            raise PermissionDeniedError("member invitations are disabled for this workspace")

        # team.default_role: when the caller does not specify a role, fall back
        # to the tenant's configured default (registry default: "cashier").
        if not role_code:
            role_code = settings["team.default_role"]

        role = (
            await session.execute(select(Role).where(Role.code == role_code))
        ).scalar_one_or_none()
        if role is None:
            raise ValidationError(f"unknown role: {role_code}")
        if role_code == "owner" and not inviter_is_platform_admin:
            raise PermissionDeniedError("owner invitations require a platform admin")
        if not inviter_is_platform_admin:
            inviter_rank = TenantService._ROLE_RANK.get(inviter_role_code or "")
            invited_rank = TenantService._ROLE_RANK.get(role_code)
            if inviter_rank is None or inviter_rank <= invited_rank:
                raise PermissionDeniedError(
                    f"a {inviter_role_code or 'unknown'} role cannot invite a {role_code}"
                )
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
            status="pending",
            expires_at=_now() + timedelta(days=7),
        )
        session.add(invitation)
        await session.flush()
        return invitation

    @staticmethod
    async def set_member_role(
        session,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        role_code: str,
        actor_role_code: str | None,
        actor_is_platform_admin: bool = False,
    ) -> None:
        """Change one membership's role, under the same rank guard as an invite.

        The rules that make this safe, in order:

        - the owner's role cannot be changed here at all: ownership is handed over,
          not reassigned, so this refuses instead of quietly moving a workspace to
          somebody else;
        - a caller may not touch someone at or above their own rank (the invite
          guard's rule, applied to a different verb);
        - a caller may not hand out a role at or above their own rank either, which
          is how "manager promotes self to owner" would otherwise be possible.
        """
        membership = (
            await session.execute(
                select(TenantUser, Role.code)
                .outerjoin(Role, Role.id == TenantUser.role_id)
                .where(TenantUser.tenant_id == tenant_id, TenantUser.user_id == user_id)
            )
        ).first()
        if membership is None:
            raise NotFoundError("that person is not a member of this workspace")
        membership_row, current_code = membership
        if current_code == "owner":
            raise PermissionDeniedError("ownership is transferred, not reassigned")
        if role_code == "owner" and not actor_is_platform_admin:
            raise PermissionDeniedError("only a platform admin can assign the owner role")

        new_role = (
            await session.execute(select(Role).where(Role.code == role_code))
        ).scalar_one_or_none()
        if new_role is None:
            raise ValidationError(f"unknown role: {role_code}")

        if not actor_is_platform_admin:
            actor_rank = TenantService._ROLE_RANK.get(actor_role_code or "")
            target_rank = TenantService._ROLE_RANK.get(current_code or "")
            new_rank = TenantService._ROLE_RANK.get(role_code)
            if actor_rank is None or new_rank is None:
                raise PermissionDeniedError("unknown role in this request")
            if target_rank is None or actor_rank <= target_rank:
                raise PermissionDeniedError(
                    f"a {actor_role_code or 'unknown'} role cannot change a {current_code} member"
                )
            if actor_rank <= new_rank:
                raise PermissionDeniedError(
                    f"a {actor_role_code or 'unknown'} role cannot assign {role_code}"
                )

        membership_row.role_id = new_role.id
        await session.flush()

    @staticmethod
    async def remove_member(
        session,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_role_code: str | None,
        actor_is_platform_admin: bool = False,
    ) -> None:
        """Take one person out of the workspace.

        Refused for the owner (the workspace would be left unowned), refused for
        yourself (leaving is a different act with its own consequences, and a
        "remove me" button that silently works is how an admin locks themselves
        out), and refused across ranks.
        """
        if user_id == actor_user_id:
            raise PermissionDeniedError("you cannot remove yourself from the workspace")
        membership = (
            await session.execute(
                select(TenantUser, Role.code)
                .outerjoin(Role, Role.id == TenantUser.role_id)
                .where(TenantUser.tenant_id == tenant_id, TenantUser.user_id == user_id)
            )
        ).first()
        if membership is None:
            raise NotFoundError("that person is not a member of this workspace")
        membership_row, current_code = membership
        if current_code == "owner":
            raise PermissionDeniedError("the workspace owner cannot be removed")
        if not actor_is_platform_admin:
            actor_rank = TenantService._ROLE_RANK.get(actor_role_code or "")
            target_rank = TenantService._ROLE_RANK.get(current_code or "")
            if actor_rank is None or target_rank is None or actor_rank <= target_rank:
                raise PermissionDeniedError(
                    f"a {actor_role_code or 'unknown'} role cannot remove a {current_code} member"
                )
        await session.delete(membership_row)
        await session.flush()

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
            await _record_security_event(
                "invitation_expired",
                details={
                    "email_domain": invitation.email.split("@")[-1]
                    if "@" in invitation.email
                    else "",
                    "invitation_id": str(invitation.id),
                },
                tenant_id=invitation.tenant_id,
            )
            raise ValidationError("invitation expired")
        existing = (
            await session.execute(
                select(User).where(User.email == invitation.email.strip().lower())
            )
        ).scalar_one_or_none()

        async def _bind_self_guc(uid: uuid.UUID) -> None:
            await session.execute(
                sa.text("SELECT set_config(:guc, :user_id, true)"),
                {"guc": "app.user_id", "user_id": str(uid)},
            )

        if existing is not None:
            user = existing
            if not user.email_verified:
                raise PermissionDeniedError(
                    "this account's email is not verified — confirm the "
                    "address (or complete a password reset) before accepting "
                    "this invitation"
                )
            await _bind_self_guc(user.id)
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
                email=invitation.email.strip().lower(),
                password_hash=await hash_password_async(password),
                full_name=full_name,
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            await _bind_self_guc(user.id)
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
