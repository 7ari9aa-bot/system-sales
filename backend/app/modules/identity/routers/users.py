"""Identity users HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.modules.identity import schemas, service
from app.modules.identity.deps import TenantCtxDep
from app.modules.identity.models import Role, TenantUser, User

users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("/me", response_model=schemas.CurrentUser)
async def my_profile(ctx: TenantCtxDep):
    full = await service.UserService.get(ctx.session, ctx.user.id)
    tenants = await service.TenantService.list_for_user(ctx.session, ctx.user.id)
    return schemas.CurrentUser(
        id=full.id,
        email=full.email,
        full_name=full.full_name,
        is_platform_admin=full.is_platform_admin,
        tenants=[
            schemas.CurrentTenant(id=t.id, name=t.name, slug=t.slug, role_code=role)
            for t, role in tenants
        ],
    )


@users_router.get("")
async def list_tenant_members(ctx: TenantCtxDep):
    """The tenant's members — the POS profile-grant picker's source.

    Read-only and tenant-scoped: only the members of the caller's own
    tenant, with the role each membership carries.
    """
    rows = (
        (
            await ctx.session.execute(
                select(User.id, User.email, User.full_name, Role.code)
                .select_from(TenantUser)
                .join(User, User.id == TenantUser.user_id)
                .join(Role, Role.id == TenantUser.role_id)
                .where(TenantUser.tenant_id == ctx.tenant_id)
                .order_by(User.full_name.asc())
            )
        )
        .all()
    )
    return [
        {
            "id": str(row.id),
            "email": row.email,
            "full_name": row.full_name,
            "role_code": row.code,
        }
        for row in rows
    ]
