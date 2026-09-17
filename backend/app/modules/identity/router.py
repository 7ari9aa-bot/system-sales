"""Identity + auth HTTP routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response

from app.core.errors import PermissionDeniedError
from app.modules.identity import schemas, service
from app.modules.identity.deps import (
    CurrentUserDep,
    DbSession,
    TenantContext,
    TenantCtxDep,
    require_permission,
)

router = APIRouter(tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])
tenants_router = APIRouter(prefix="/tenants", tags=["tenants"])

_CLIENT_TTL = 60 * 60 * 24 * 30  # refresh cookie life if cookie mode used


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("user-agent"), request.client.host if request.client else None


@router.post("/auth/register", response_model=schemas.CurrentUser, status_code=201)
async def register(body: schemas.RegisterRequest, session: DbSession):
    user, _tenant = await service.AuthService.register(
        session,
        tenant_name=body.tenant_name,
        tenant_slug=body.tenant_slug,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
    )
    return schemas.CurrentUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_platform_admin=user.is_platform_admin,
        tenants=[],
    )


@router.post("/auth/login", response_model=schemas.TokenPair)
async def login(body: schemas.LoginRequest, request: Request, session: DbSession):
    user_agent, ip = _client_meta(request)
    pair, _user, _tenant_id = await service.AuthService.login(
        session, email=body.email, password=body.password, user_agent=user_agent, ip=ip
    )
    return pair


@router.post("/auth/refresh", response_model=schemas.TokenPair)
async def refresh(body: schemas.RefreshRequest, request: Request, session: DbSession):
    user_agent, ip = _client_meta(request)
    pair, _user, _tenant_id = await service.AuthService.refresh(
        session, refresh_token=body.refresh_token, user_agent=user_agent, ip=ip
    )
    return pair


@router.post("/auth/logout", status_code=204)
async def logout(body: schemas.RefreshRequest, session: DbSession, response: Response):
    await service.AuthService.logout(session, refresh_token=body.refresh_token)
    response.status_code = 204
    return None


@router.get("/auth/me", response_model=schemas.CurrentUser)
async def me(user: CurrentUserDep, session: DbSession):
    full = await service.UserService.get(session, user.id)
    tenants = await service.TenantService.list_for_user(session, user.id)
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


@router.post("/auth/switch-tenant", response_model=schemas.TokenPair)
async def switch_tenant(
    body: schemas.RefreshRequest, tenant_id: uuid.UUID, user: CurrentUserDep, session: DbSession
):
    return await service.AuthService.switch_tenant(
        session, user=user, tenant_id=tenant_id, refresh_token=body.refresh_token
    )


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


@tenants_router.post(
    "/{tenant_id}/invitations", response_model=schemas.InvitationOut, status_code=201
)
async def create_invitation(
    tenant_id: uuid.UUID,
    body: schemas.InviteRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    if ctx.tenant_id != tenant_id:
        raise PermissionDeniedError("tenant mismatch")
    invitation = await service.TenantService.invite(
        ctx.session,
        tenant_id=tenant_id,
        email=body.email,
        role_code=body.role_code,
        invited_by=ctx.user.id,
    )
    return invitation
