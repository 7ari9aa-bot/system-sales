"""Roles and the permission matrix.

Read-only by design: the matrix is what the server enforces, and the four roles are
seeded by the platform. A writable matrix would be a second permission system that
the guards in ``deps.py`` know nothing about.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.platform.identity import schemas
from app.platform.identity.deps import TenantContext, get_tenant_ctx, require_permission
from app.platform.identity.services.roles import RoleService

roles_router = APIRouter(prefix="/roles", tags=["roles"])


@roles_router.get("/matrix", response_model=schemas.PermissionMatrixOut)
async def permission_matrix(ctx: TenantContext = Depends(require_permission("settings:read"))):
    payload = await RoleService.matrix(ctx.session)
    return schemas.PermissionMatrixOut(**payload)


@roles_router.get("/me", response_model=schemas.MyAccessOut)
async def my_access(ctx: TenantContext = Depends(get_tenant_ctx)) -> schemas.MyAccessOut:
    """The caller's own role and permission codes in the active tenant.

    No ``require_permission`` gate, and that is the point: the matrix above needs
    ``settings:read``, so the one account that most needs to know it has no settings grant
    cannot read it there. This answers "what am I" instead of "what does everyone hold".
    """
    return schemas.MyAccessOut(role_code=ctx.role_code, permissions=sorted(ctx.permission_codes))
