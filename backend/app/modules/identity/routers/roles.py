"""Roles and the permission matrix.

Read-only by design: the matrix is what the server enforces, and the four roles are
seeded by the platform. A writable matrix would be a second permission system that
the guards in ``deps.py`` know nothing about.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.modules.identity import schemas
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.identity.services.roles import RoleService

roles_router = APIRouter(prefix="/roles", tags=["roles"])


@roles_router.get("/matrix", response_model=schemas.PermissionMatrixOut)
async def permission_matrix(ctx: TenantContext = Depends(require_permission("settings:read"))):
    payload = await RoleService.matrix(ctx.session)
    return schemas.PermissionMatrixOut(**payload)
