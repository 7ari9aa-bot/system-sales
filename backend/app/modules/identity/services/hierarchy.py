"""HierarchyService — §151 workspaces, locations, and location access grants.

Extracted from the original monolithic service.py.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.identity.models import (
    Location,
    TenantUser,
    UserLocationAccess,
    Workspace,
)


class HierarchyService:
    """§151 — workspaces, locations, and location access grants.

    Tenancy is passed in by the caller (the router takes it from the request
    context) and folded into EVERY query's WHERE clause — the second,
    application-layer half of isolation.
    """

    # --- Workspaces ---

    @staticmethod
    async def list_workspaces(session, tenant_id: uuid.UUID) -> list[Workspace]:
        rows = (
            await session.execute(
                sa.select(Workspace)
                .where(Workspace.tenant_id == tenant_id)
                .order_by(Workspace.created_at)
            )
        ).scalars()
        return list(rows)

    @staticmethod
    async def _get_workspace(session, tenant_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace:
        ws = (
            await session.execute(
                sa.select(Workspace).where(
                    Workspace.id == workspace_id, Workspace.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if ws is None:
            raise NotFoundError("workspace not found")
        return ws

    @staticmethod
    async def create_workspace(session, tenant_id: uuid.UUID, *, name: str, slug: str) -> Workspace:
        dup = (
            await session.execute(
                sa.select(Workspace.id).where(
                    Workspace.tenant_id == tenant_id, Workspace.slug == slug
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise ConflictError("a workspace with this slug already exists")
        ws = Workspace(tenant_id=tenant_id, name=name, slug=slug)
        session.add(ws)
        await session.flush()
        return ws

    @staticmethod
    async def get_workspace(session, tenant_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace:
        return await HierarchyService._get_workspace(session, tenant_id, workspace_id)

    @staticmethod
    async def update_workspace(
        session,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        name: str | None = None,
        is_active: bool | None = None,
    ) -> Workspace:
        ws = await HierarchyService._get_workspace(session, tenant_id, workspace_id)
        if name is not None:
            ws.name = name
        if is_active is not None:
            ws.is_active = is_active
        await session.flush()
        return ws

    # --- Locations ---

    @staticmethod
    async def _get_location(session, tenant_id: uuid.UUID, location_id: uuid.UUID) -> Location:
        loc = (
            await session.execute(
                sa.select(Location).where(
                    Location.id == location_id, Location.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if loc is None:
            raise NotFoundError("location not found")
        return loc

    @staticmethod
    async def list_locations(
        session, tenant_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[Location]:
        await HierarchyService._get_workspace(session, tenant_id, workspace_id)
        rows = (
            await session.execute(
                sa.select(Location)
                .where(Location.tenant_id == tenant_id, Location.workspace_id == workspace_id)
                .order_by(Location.created_at)
            )
        ).scalars()
        return list(rows)

    @staticmethod
    async def create_location(
        session,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        name: str,
        code: str | None,
    ) -> Location:
        await HierarchyService._get_workspace(session, tenant_id, workspace_id)
        if code is not None:
            dup = (
                await session.execute(
                    sa.select(Location.id).where(
                        Location.tenant_id == tenant_id,
                        Location.workspace_id == workspace_id,
                        Location.code == code,
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise ConflictError("a location with this code already exists in the workspace")
        loc = Location(tenant_id=tenant_id, workspace_id=workspace_id, name=name, code=code)
        session.add(loc)
        await session.flush()
        return loc

    @staticmethod
    async def update_location(
        session,
        tenant_id: uuid.UUID,
        location_id: uuid.UUID,
        *,
        name: str | None = None,
        code: str | None = None,
        is_active: bool | None = None,
    ) -> Location:
        loc = await HierarchyService._get_location(session, tenant_id, location_id)
        if name is not None:
            loc.name = name
        if code is not None:
            dup = (
                await session.execute(
                    sa.select(Location.id).where(
                        Location.tenant_id == tenant_id,
                        Location.workspace_id == loc.workspace_id,
                        Location.code == code,
                        Location.id != loc.id,
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                raise ConflictError("a location with this code already exists in the workspace")
            loc.code = code
        if is_active is not None:
            loc.is_active = is_active
        await session.flush()
        return loc

    # --- Location access ---

    @staticmethod
    async def list_access(
        session, tenant_id: uuid.UUID, location_id: uuid.UUID
    ) -> list[UserLocationAccess]:
        await HierarchyService._get_location(session, tenant_id, location_id)
        rows = (
            await session.execute(
                sa.select(UserLocationAccess)
                .where(UserLocationAccess.location_id == location_id)
                .order_by(UserLocationAccess.created_at)
            )
        ).scalars()
        return list(rows)

    @staticmethod
    async def grant_access(
        session,
        tenant_id: uuid.UUID,
        location_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        role_override: str | None,
        granted_by: uuid.UUID | None = None,
    ) -> UserLocationAccess:
        await HierarchyService._get_location(session, tenant_id, location_id)
        is_member = (
            await session.execute(
                sa.select(TenantUser.user_id).where(
                    TenantUser.user_id == user_id, TenantUser.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if is_member is None:
            raise ValidationError("user is not a member of this tenant")
        existing = (
            await session.execute(
                sa.select(UserLocationAccess).where(
                    UserLocationAccess.user_id == user_id,
                    UserLocationAccess.location_id == location_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.role_override = role_override
            existing.granted_by = granted_by
            await session.flush()
            return existing
        grant = UserLocationAccess(
            user_id=user_id,
            location_id=location_id,
            role_override=role_override,
            granted_by=granted_by,
        )
        session.add(grant)
        await session.flush()
        return grant

    @staticmethod
    async def revoke_access(
        session,
        tenant_id: uuid.UUID,
        location_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> None:
        await HierarchyService._get_location(session, tenant_id, location_id)
        existing = (
            await session.execute(
                sa.select(UserLocationAccess).where(
                    UserLocationAccess.user_id == user_id,
                    UserLocationAccess.location_id == location_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise NotFoundError("no such access grant")
        await session.delete(existing)
        await session.flush()
