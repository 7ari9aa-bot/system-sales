"""AccountClosureService — the person's own exit from the platform.

Two questions, both answered from rows that already exist:

- Can this person leave? A member can. A SOLE OWNER cannot: the shop would be
  left with nobody able to administer it, so the request is refused and the
  screen names the shop that must be handed over first. The check is the same
  one the API enforces — the service is the only writer, the router only parses.
- What did they ask for? At most one OPEN request exists per person (a partial
  unique index backs that), so the card shows either the pending request or the
  form, never both.

Nothing here deletes anything: ``mode`` records intent (close vs delete) and the
platform decides. That is deliberate — erasing an account that other people's
shops reference is an operation with a handover, not a self-service button.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.identity.models import (
    AccountClosureRequest,
    Role,
    Tenant,
    TenantUser,
)

#: Roles that can administer a shop on their own. A sole holder of any of these
#: blocks closure; the person has to hand the shop over or invite a second one.
_ADMIN_ROLES = ("owner",)


class AccountClosureService:
    @staticmethod
    async def _blockers(session, user_id: uuid.UUID) -> list[dict]:
        """Shops this person administers alone — the reason a closure must wait."""
        memberships = (
            await session.execute(
                select(TenantUser.tenant_id, Tenant.name, Role.code)
                .join(Tenant, Tenant.id == TenantUser.tenant_id)
                .outerjoin(Role, Role.id == TenantUser.role_id)
                .where(
                    TenantUser.user_id == user_id,
                    Tenant.lifecycle_state != "deleted",
                )
                .order_by(Tenant.name.asc())
            )
        ).all()

        admin_tenant_ids = [
            row.tenant_id for row in memberships if (row.code or "") in _ADMIN_ROLES
        ]
        if not admin_tenant_ids:
            return []

        counts = dict(
            (
                await session.execute(
                    select(TenantUser.tenant_id, func.count())
                    .join(Role, Role.id == TenantUser.role_id)
                    .where(
                        TenantUser.tenant_id.in_(admin_tenant_ids),
                        Role.code.in_(_ADMIN_ROLES),
                    )
                    .group_by(TenantUser.tenant_id)
                )
            ).all()
        )

        return [
            {
                "tenant_id": row.tenant_id,
                "tenant_name": row.name,
                "role_code": row.code,
            }
            for row in memberships
            if (row.code or "") in _ADMIN_ROLES and counts.get(row.tenant_id, 0) <= 1
        ]

    @staticmethod
    async def state(session, user_id: uuid.UUID) -> dict:
        """The open (or latest decided) request plus what would block a new one."""
        latest = (
            await session.execute(
                select(AccountClosureRequest)
                .where(AccountClosureRequest.user_id == user_id)
                .order_by(AccountClosureRequest.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        memberships = (
            await session.execute(
                select(func.count())
                .select_from(TenantUser)
                .join(Tenant, Tenant.id == TenantUser.tenant_id)
                .where(
                    TenantUser.user_id == user_id,
                    Tenant.lifecycle_state != "deleted",
                )
            )
        ).scalar_one()
        return {
            "request": latest,
            "blockers": await AccountClosureService._blockers(session, user_id),
            "memberships": int(memberships or 0),
        }

    @staticmethod
    async def open(
        session, user_id: uuid.UUID, *, mode: str, reason: str | None
    ) -> AccountClosureRequest:
        """Record the intent. Refuses a sole owner, and a second open request."""
        blockers = await AccountClosureService._blockers(session, user_id)
        if blockers:
            names = "، ".join(blocker["tenant_name"] for blocker in blockers)
            raise ValidationError(f"hand over or share ownership of these shops first: {names}")

        existing = (
            await session.execute(
                select(AccountClosureRequest).where(
                    AccountClosureRequest.user_id == user_id,
                    AccountClosureRequest.status == "pending",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("a closure request is already open for this account")

        cleaned_reason = " ".join((reason or "").split()) or None
        request = AccountClosureRequest(
            user_id=user_id,
            mode=mode,
            reason=cleaned_reason,
            status="pending",
        )
        session.add(request)
        await session.flush()
        return request

    @staticmethod
    async def cancel(session, user_id: uuid.UUID) -> AccountClosureRequest:
        """Withdraw the open request. A decided one is history, not editable."""
        request = (
            await session.execute(
                select(AccountClosureRequest).where(
                    AccountClosureRequest.user_id == user_id,
                    AccountClosureRequest.status == "pending",
                )
            )
        ).scalar_one_or_none()
        if request is None:
            raise NotFoundError("no open closure request")
        request.status = "cancelled"
        request.decided_at = func.now()
        await session.flush()
        return request
