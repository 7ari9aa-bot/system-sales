"""Identity hierarchy HTTP routes: workspaces, locations, location access."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response

from app.modules.identity import schemas, service
from app.modules.identity.deps import TenantContext, require_permission

# §151 — the tenant's hierarchy surface. Tenancy comes from the request
# context only (no tenant ids in paths): every handler passes ctx.tenant_id
# into the service, which filters with it AND runs under the bound RLS GUC.
hierarchy_router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])


@hierarchy_router.get("/workspaces", response_model=schemas.WorkspaceListOut)
async def list_workspaces(ctx: TenantContext = Depends(require_permission("settings:read"))):
    rows = await service.HierarchyService.list_workspaces(ctx.session, ctx.tenant_id)
    return schemas.WorkspaceListOut(items=list(rows))


@hierarchy_router.post("/workspaces", response_model=schemas.WorkspaceOut, status_code=201)
async def create_workspace(
    body: schemas.WorkspaceCreate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.create_workspace(
        ctx.session, ctx.tenant_id, name=body.name, slug=body.slug
    )


@hierarchy_router.get("/workspaces/{workspace_id}", response_model=schemas.WorkspaceOut)
async def get_workspace(
    workspace_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    return await service.HierarchyService.get_workspace(ctx.session, ctx.tenant_id, workspace_id)


@hierarchy_router.patch("/workspaces/{workspace_id}", response_model=schemas.WorkspaceOut)
async def update_workspace(
    workspace_id: uuid.UUID,
    body: schemas.WorkspaceUpdate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.update_workspace(
        ctx.session,
        ctx.tenant_id,
        workspace_id,
        name=body.name,
        is_active=body.is_active,
    )


@hierarchy_router.get(
    "/workspaces/{workspace_id}/locations", response_model=schemas.LocationListOut
)
async def list_locations(
    workspace_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    rows = await service.HierarchyService.list_locations(ctx.session, ctx.tenant_id, workspace_id)
    return schemas.LocationListOut(items=list(rows))


@hierarchy_router.post(
    "/workspaces/{workspace_id}/locations",
    response_model=schemas.LocationOut,
    status_code=201,
)
async def create_location(
    workspace_id: uuid.UUID,
    body: schemas.LocationCreate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.create_location(
        ctx.session,
        ctx.tenant_id,
        workspace_id,
        name=body.name,
        code=body.code,
    )


@hierarchy_router.patch("/locations/{location_id}", response_model=schemas.LocationOut)
async def update_location(
    location_id: uuid.UUID,
    body: schemas.LocationUpdate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.update_location(
        ctx.session,
        ctx.tenant_id,
        location_id,
        name=body.name,
        code=body.code,
        is_active=body.is_active,
    )


@hierarchy_router.get(
    "/locations/{location_id}/access", response_model=schemas.LocationAccessListOut
)
async def list_location_access(
    location_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    rows = await service.HierarchyService.list_access(ctx.session, ctx.tenant_id, location_id)
    return schemas.LocationAccessListOut(items=list(rows))


@hierarchy_router.put(
    "/locations/{location_id}/access/{user_id}",
    response_model=schemas.LocationAccessOut,
)
async def grant_location_access(
    location_id: uuid.UUID,
    user_id: uuid.UUID,
    body: schemas.LocationAccessGrant,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    return await service.HierarchyService.grant_access(
        ctx.session,
        ctx.tenant_id,
        location_id,
        user_id=user_id,
        role_override=body.role_override,
        granted_by=ctx.user.id,
    )


@hierarchy_router.delete("/locations/{location_id}/access/{user_id}", status_code=204)
async def revoke_location_access(
    location_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    await service.HierarchyService.revoke_access(
        ctx.session, ctx.tenant_id, location_id, user_id=user_id
    )
    return Response(status_code=204)
