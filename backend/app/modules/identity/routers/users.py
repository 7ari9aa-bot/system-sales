"""Identity users HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.identity import schemas, service
from app.modules.identity.deps import TenantCtxDep

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
