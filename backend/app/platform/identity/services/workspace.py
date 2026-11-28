"""The ACCOUNT workspace: the container a person signs in to.

Naming, because this module is where two different things could be confused:

- The **account workspace** (this module) is the tenant. It is what the settings
  map calls "مساحة العمل": the organisational container that holds the business,
  its members and their shared settings. It is NOT the store — a store has a
  currency, prices and receipts; the workspace has members and a role per member.
- The **hierarchy workspace** (``services/hierarchy.py``, §151) is an internal
  level inside a tenant: tenant → workspace → location. It is reachable at
  ``/hierarchy/workspaces`` and belongs to the Locations section of the map.

They share a word and nothing else. Everything here is tenant-scoped and answers
"which container am I in, and what can I do in it".
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.identity.models import Role, Tenant, TenantUser

#: The roles that administer a workspace on its own. "Owner" is the single account
#: holder; "admin" is a delegated administrator. Both are shown on the ownership
#: page, because handing the workspace over is a conversation between them.
ADMIN_ROLES = ("owner", "admin")


class WorkspaceService:
    @staticmethod
    async def memberships(session: AsyncSession, user_id: uuid.UUID) -> list[dict]:
        """Every workspace this person belongs to, with their role in each.

        One query over the memberships the person actually holds — this is what the
        switcher lists, so it must not depend on the workspace they are currently in.
        A deleted workspace is not offered: switching into it would land on a wall.
        """
        rows = (
            await session.execute(
                select(
                    Tenant.id,
                    Tenant.name,
                    Tenant.slug,
                    Tenant.lifecycle_state,
                    Tenant.is_active,
                    Role.code,
                )
                .select_from(TenantUser)
                .join(Tenant, Tenant.id == TenantUser.tenant_id)
                .outerjoin(Role, Role.id == TenantUser.role_id)
                .where(
                    TenantUser.user_id == user_id,
                    Tenant.lifecycle_state != "deleted",
                )
                .order_by(Tenant.name.asc())
            )
        ).all()
        return [
            {
                "id": row.id,
                "name": row.name,
                "slug": row.slug,
                "role_code": row.code,
                "lifecycle_state": row.lifecycle_state,
                "is_active": row.is_active,
            }
            for row in rows
        ]

    @staticmethod
    async def overview(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        """The current workspace as the overview page draws it.

        ``member_count`` is the size of the team, not a permission-gated roster: the
        count is harmless, the emails are not (see ``admins``).
        """
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()

        member_count = (
            await session.execute(
                select(func.count())
                .select_from(TenantUser)
                .where(TenantUser.tenant_id == tenant_id)
            )
        ).scalar_one()

        role_code = (
            await session.execute(
                select(Role.code)
                .select_from(TenantUser)
                .outerjoin(Role, Role.id == TenantUser.role_id)
                .where(TenantUser.tenant_id == tenant_id, TenantUser.user_id == user_id)
            )
        ).scalar_one_or_none()

        return {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "role_code": role_code,
            "lifecycle_state": tenant.lifecycle_state,
            "is_active": tenant.is_active,
            "status_reason": tenant.status_reason,
            "currency": tenant.currency,
            "timezone": tenant.timezone,
            "country_code": tenant.country_code,
            "dialect": tenant.dialect,
            "member_count": member_count,
            "created_at": tenant.created_at,
        }

    @staticmethod
    async def admins(session: AsyncSession, tenant_id: uuid.UUID) -> dict:
        """Who runs this workspace: the owner and the delegated admins.

        The owner is returned separately because there is exactly one and it is the
        account that cannot walk away (see ``AccountClosureService``), so the screen
        must not present it as just another row in a list.
        """
        rows = (
            await session.execute(
                select(TenantUser.user_id, Role.code)
                .select_from(TenantUser)
                .join(Role, Role.id == TenantUser.role_id)
                .where(TenantUser.tenant_id == tenant_id, Role.code.in_(ADMIN_ROLES))
            )
        ).all()
        owner_ids = [row.user_id for row in rows if row.code == "owner"]
        return {
            "owner_user_id": owner_ids[0] if owner_ids else None,
            "admin_user_ids": [row.user_id for row in rows if row.code == "admin"],
        }
