"""Roles and the permission matrix, read from the tables that actually decide.

The matrix page must never invent a permission: what it shows is exactly what
``role_permissions`` holds, joined to ``permissions`` for the resource/action split.
Editing is deliberately absent — a role's permission set is a platform decision
(the four seeded roles), and a page that could rewrite it would let a workspace
grant itself an action the rest of the code does not expect to exist.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Permission, Role, role_permissions

#: The order roles are shown in: the ones that administer first. Unknown codes keep
#: their alphabetical place after these, so a seeded extra role never disappears.
ROLE_ORDER = ("owner", "admin", "manager", "cashier", "staff")


class RoleService:
    @staticmethod
    async def matrix(session: AsyncSession) -> dict:
        roles = (await session.execute(select(Role))).scalars().all()
        permissions = (
            (await session.execute(select(Permission).order_by(Permission.code.asc())))
            .scalars()
            .all()
        )
        links = (
            await session.execute(
                select(role_permissions.c.role_id, Permission.code).select_from(
                    role_permissions.join(
                        Permission, Permission.id == role_permissions.c.permission_id
                    )
                )
            )
        ).all()
        by_role: dict[object, list[str]] = {}
        for role_id, code in links:
            by_role.setdefault(role_id, []).append(code)

        def order(role: Role) -> tuple[int, str]:
            try:
                return (ROLE_ORDER.index(role.code), role.code)
            except ValueError:
                return (len(ROLE_ORDER), role.code)

        return {
            "roles": [
                {
                    "code": role.code,
                    "name": role.name,
                    "description": role.description,
                    "permissions": sorted(by_role.get(role.id, [])),
                }
                for role in sorted(roles, key=order)
            ],
            "permissions": [
                {"code": item.code, "resource": item.resource, "action": item.action}
                for item in permissions
            ],
        }
