"""Teams and departments HTTP routes.

A team is a grouping, so everything here needs the settings permissions and
nothing here grants access. Reads need ``settings:read`` (the same permission the
roster needs, because a team page lists people); writes need ``settings:write``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from app.platform.identity import schemas
from app.platform.identity.deps import TenantContext, require_permission
from app.platform.identity.services.teams import TeamService

teams_router = APIRouter(prefix="/teams", tags=["teams"])


@teams_router.get("", response_model=schemas.TeamListOut)
async def list_teams(ctx: TenantContext = Depends(require_permission("settings:read"))):
    return schemas.TeamListOut(items=await TeamService.list_teams(ctx.session, ctx.tenant_id))


@teams_router.post("", response_model=schemas.TeamOut, status_code=201)
async def create_team(
    body: schemas.TeamCreate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    team = await TeamService.create_team(
        ctx.session, ctx.tenant_id, name=body.name, description=body.description
    )
    return schemas.TeamOut(id=team.id, name=team.name, description=team.description, member_count=0)


@teams_router.patch("/{team_id}", response_model=schemas.TeamOut)
async def rename_team(
    team_id: uuid.UUID,
    body: schemas.TeamUpdate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    team = await TeamService.rename_team(
        ctx.session, ctx.tenant_id, team_id, name=body.name, description=body.description
    )
    members = await TeamService.members(ctx.session, ctx.tenant_id, team_id)
    return schemas.TeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        member_count=len(members),
    )


@teams_router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    await TeamService.delete_team(ctx.session, ctx.tenant_id, team_id)
    return Response(status_code=204)


@teams_router.get("/{team_id}/members", response_model=schemas.TeamMemberListOut)
async def list_team_members(
    team_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    rows = await TeamService.members(ctx.session, ctx.tenant_id, team_id)
    return schemas.TeamMemberListOut(items=[schemas.TeamMemberOut(**row) for row in rows])


@teams_router.put("/{team_id}/members/{user_id}", status_code=204)
async def add_team_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    await TeamService.add_member(ctx.session, ctx.tenant_id, team_id, user_id)
    return Response(status_code=204)


@teams_router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    await TeamService.remove_member(ctx.session, ctx.tenant_id, team_id, user_id)
    return Response(status_code=204)
