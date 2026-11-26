"""WORKSPACES — the account container a person signs in to.

This is the settings map's "مساحة العمل": the organisational container holding the
business, its members and their shared settings. It is NOT the store, and it is NOT
the §151 hierarchy workspace that lives at ``/hierarchy/workspaces`` (tenant →
workspace → location, managed under Locations).

Everything here is self-scoped: a person reads the containers they belong to and the
one they are currently in. Nothing on these routes can widen a membership, which is
why none of them needs an admin role — only the roster of who administers the
workspace does (``settings:read``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.modules.identity import schemas
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

workspaces_router = APIRouter(prefix="/workspaces", tags=["workspaces"])

SettingsReadCtx = Annotated[TenantContext, Depends(require_permission("settings:read"))]


@workspaces_router.get(
    "",
    summary="List the workspaces the caller belongs to",
    response_model=list[schemas.WorkspaceMembershipOut],
)
async def list_my_workspaces(ctx: TenantCtxDep) -> list[schemas.WorkspaceMembershipOut]:
    """Every container this person is a member of, with their role in each.

    The switcher's source. Deliberately not scoped to the current workspace: the
    point of the list is to leave the one you are in.
    """
    from app.modules.identity.services.workspace import WorkspaceService

    rows = await WorkspaceService.memberships(ctx.session, ctx.user.id)
    return [schemas.WorkspaceMembershipOut(**row) for row in rows]


@workspaces_router.get(
    "/current",
    summary="Read the workspace the caller is currently in",
    response_model=schemas.WorkspaceOverviewOut,
)
async def current_workspace(ctx: TenantCtxDep) -> schemas.WorkspaceOverviewOut:
    """The container, its region, its size and the caller's own role in it."""
    from app.modules.identity.services.workspace import WorkspaceService

    data = await WorkspaceService.overview(ctx.session, ctx.tenant_id, ctx.user.id)
    return schemas.WorkspaceOverviewOut(**data)


@workspaces_router.get(
    "/current/admins",
    summary="Who administers the workspace (owner and admins)",
    response_model=schemas.WorkspaceAdminsOut,
)
async def current_workspace_admins(ctx: SettingsReadCtx) -> schemas.WorkspaceAdminsOut:
    """Ids only, resolved against the roster the members screen already shows.

    Reading the team roster is a settings read (it carries everyone's email), so a
    cashier gets a 403 here and the ownership page says so instead of drawing an
    empty list as if the workspace had no owner.
    """
    from app.modules.identity.services.workspace import WorkspaceService

    data = await WorkspaceService.admins(ctx.session, ctx.tenant_id)
    return schemas.WorkspaceAdminsOut(**data)
