"""FastAPI dependencies: sessions, auth, tenant binding, RBAC.

Dependency order matters: get_db opens the request transaction; get_current_user
authenticates (no DB); require_tenant binds BOTH GUCs (app.tenant_id,
app.user_id) on that same transaction so every query below runs under RLS.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, bind_tenant
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.security import decode_token
from app.modules.identity.models import Permission, Role, TenantUser, role_permissions


async def get_db() -> AsyncSession:
    """One session per request, one transaction: commit on success."""
    async with SessionLocal() as session:
        async with session.begin():
            yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(slots=True)
class AuthedUser:
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    role_code: str | None


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise PermissionDeniedError("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except Exception as exc:  # jwt.PyJWTError and anything odd
        raise PermissionDeniedError("invalid token") from exc
    if payload.get("type") != "access":
        raise PermissionDeniedError("wrong token type")
    tenant_raw = payload.get("tenant_id")
    return AuthedUser(
        id=uuid.UUID(payload["sub"]),
        tenant_id=uuid.UUID(tenant_raw) if tenant_raw else None,
        role_code=payload.get("role"),
    )


CurrentUserDep = Annotated[AuthedUser, Depends(get_current_user)]


@dataclass(slots=True)
class TenantContext:
    session: AsyncSession
    user: AuthedUser
    tenant_id: uuid.UUID
    role_code: str | None
    permission_codes: set[str]


async def _role_permissions(session: AsyncSession, role_id: uuid.UUID) -> set[str]:
    rows = (
        await session.execute(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == role_id)
        )
    ).all()
    return {code for (code,) in rows}


async def get_tenant_ctx(
    session: DbSession,
    user: CurrentUserDep,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> TenantContext:
    """Resolve the active tenant, verify membership, bind RLS GUCs."""
    tenant_id = user.tenant_id
    if x_tenant_id:
        try:
            tenant_id = uuid.UUID(x_tenant_id)
        except ValueError as exc:
            raise PermissionDeniedError("invalid tenant header") from exc
    if tenant_id is None:
        raise PermissionDeniedError("no active tenant — switch or pick a tenant")

    # Bind the user GUC first: the tenant_users self-access policy requires
    # it before any membership row is visible (pre-tenant-context stage).
    await session.execute(
        sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)}
    )
    membership = (
        await session.execute(
            select(TenantUser, Role.code)
            .outerjoin(Role, Role.id == TenantUser.role_id)
            .where(TenantUser.user_id == user.id, TenantUser.tenant_id == tenant_id)
        )
    ).first()
    if membership is None:
        raise PermissionDeniedError("not a member of this tenant")
    _, role_code = membership

    perms: set[str] = set()
    if role_code:
        role_id = (
            await session.execute(
                sa.select(TenantUser.role_id).where(
                    TenantUser.user_id == user.id, TenantUser.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if role_id:
            perms = await _role_permissions(session, role_id)

    await bind_tenant(session, tenant_id)
    await session.execute(
        sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)}
    )
    return TenantContext(
        session=session,
        user=user,
        tenant_id=tenant_id,
        role_code=role_code,
        permission_codes=perms,
    )


TenantCtxDep = Annotated[TenantContext, Depends(get_tenant_ctx)]


class require_permission:
    """RBAC gate: usage — `ctx: TenantContext = Depends(require_permission("orders:write"))`."""

    def __init__(self, code: str) -> None:
        self.code = code

    async def __call__(self, ctx: TenantCtxDep) -> TenantContext:
        if self.code not in ctx.permission_codes:
            raise PermissionDeniedError(f"missing permission: {self.code}")
        return ctx


async def get_optional_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthedUser | None:
    """Auth that tolerates anonymous callers (webchat, public webhooks)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        return await get_current_user(request, authorization)
    except PermissionDeniedError:
        return None


__all__ = [
    "AuthedUser",
    "CurrentUserDep",
    "DbSession",
    "TenantContext",
    "TenantCtxDep",
    "get_current_user",
    "get_db",
    "get_optional_user",
    "get_tenant_ctx",
    "require_permission",
    "NotFoundError",
]
