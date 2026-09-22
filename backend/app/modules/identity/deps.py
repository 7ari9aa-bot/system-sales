"""FastAPI dependencies: sessions, auth, tenant binding, RBAC.

Dependency order matters: get_db opens the request transaction; get_current_user
authenticates (no DB); require_tenant binds BOTH GUCs (app.tenant_id,
app.user_id) on that same transaction so every query below runs under RLS.
§151 adds a third pair (app.workspace_id, app.location_id), bound last and only
after the scope headers have been validated fail-closed against the tenant and
the user's location grants.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, bind_scope, bind_tenant
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.security import decode_token
from app.core.tenancy import set_current_tenant
from app.modules.identity.models import (
    Location,
    Permission,
    Role,
    Tenant,
    TenantUser,
    User,
    UserLocationAccess,
    Workspace,
    role_permissions,
)

# §48 — routes a NON-operational tenant (suspended / offboarding / deleted) must
# still reach. Suspension is deliberately not "disable everything": the class
# docstring on TenantCapabilityPolicy is explicit that a suspended admin keeps
# data access so they can export before offboarding deletes it. These are the
# escape hatches that make that possible, not exceptions to the rule.
_TENANT_RECOVERY_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth",  # sign in, refresh, sign out, me
    "/api/v1/billing",  # pay, and get reactivated
    "/api/v1/privacy",  # data-subject export
    "/api/v1/notifications",  # see why the workspace stopped
    "/api/v1/invitations",  # accept an invite into a different tenant
    "/healthz",
)


def _tenant_recovery_path(path: str) -> bool:
    return path.startswith(_TENANT_RECOVERY_PREFIXES)


def _policy_for(state: str):
    """The §48 capability policy for a lifecycle state, or None if unknown.

    Imported lazily: identity.service imports identity.models and is imported by
    the same routers that import this module, so a module-scope import risks a
    cycle. An unknown state returns None so the caller can fail CLOSED — a
    tenant whose state cannot be interpreted must not get more access than an
    active one, and `policy_for` would otherwise raise ValidationError (a 400)
    on every request.
    """
    from app.modules.identity.service import STATE_POLICIES

    return STATE_POLICIES.get(state)


def tenant_may_use_api(state: str | None) -> bool:
    """§48: may a workspace in this lifecycle state use the API surface?

    Public so callers OUTSIDE the request path — the SSE gateway, which opens
    its own short-lived session, and anything else that gates on tenancy — apply
    the SAME policy as `get_tenant_ctx` rather than re-deriving it. That matters
    because the two must not drift: the SSE stream was the one surface that
    never read the state, so a suspended workspace kept its live event firehose
    while every ordinary request was refused.

    Fails CLOSED: an unknown or missing state is not "active".
    """
    if state is None:
        return False
    policy = _policy_for(state)
    return policy is not None and policy.allows_api


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
    is_platform_admin: bool = False  # §146: break-glass claim from JWT


async def get_current_user(
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise PermissionDeniedError("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise PermissionDeniedError("wrong token type")
        user_id = uuid.UUID(str(payload["sub"]))
        # S9: an access token used to be trusted for its full 30-minute life
        # without ever consulting the database, so deactivating (or deleting) a
        # user left them fully operational until expiry. One primary-key lookup
        # per request; `users` is a global table with no RLS, so this runs
        # before any tenant GUC is bound.
        is_active = (
            await session.execute(select(User.is_active).where(User.id == user_id))
        ).scalar_one_or_none()
        if not is_active:
            raise PermissionDeniedError("account is inactive")
        return AuthedUser(
            id=user_id,
            tenant_id=uuid.UUID(payload["tenant_id"]) if payload.get("tenant_id") else None,
            role_code=payload.get("role"),
            is_platform_admin=bool(payload.get("is_platform_admin", False)),  # §146
        )
    except PermissionDeniedError:
        raise
    except Exception as exc:  # malformed/expired tokens → 401, never a 500
        raise PermissionDeniedError("invalid token") from exc


CurrentUserDep = Annotated[AuthedUser, Depends(get_current_user)]


@dataclass(slots=True)
class TenantContext:
    session: AsyncSession
    user: AuthedUser
    tenant_id: uuid.UUID
    role_code: str | None
    permission_codes: set[str]
    # §151 — resolved hierarchy scope for this request (None = tenant-wide).
    # Validated fail-closed by resolve_scope() before they are ever populated.
    workspace_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None


async def resolve_scope(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """§151: validate the requested workspace/location; return (workspace, location).

    Fail-closed on every mismatch — a wrong scope is a 403, never a silent
    widening. Tenancy is checked twice on purpose: the tenant GUC is already
    bound (RLS visibility) AND tenant_id is filtered explicitly. A workspace is
    visible to any member of its tenant; a location additionally requires an
    explicit user_location_access grant. The workspace is never inferred
    upward from the location's absence — when both headers arrive they must
    agree, and when only a location arrives its workspace is derived from it.
    """
    if location_id is not None:
        loc = (
            await session.execute(
                select(Location).where(Location.id == location_id, Location.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if loc is None:
            raise PermissionDeniedError("location not available for this tenant")
        if workspace_id is not None and loc.workspace_id != workspace_id:
            raise PermissionDeniedError("location is not in the requested workspace")
        grant = (
            await session.execute(
                select(UserLocationAccess).where(
                    UserLocationAccess.user_id == user_id,
                    UserLocationAccess.location_id == loc.id,
                )
            )
        ).scalar_one_or_none()
        if grant is None:
            raise PermissionDeniedError("no access grant for this location")
        return loc.workspace_id, loc.id
    if workspace_id is not None:
        ws = (
            await session.execute(
                select(Workspace).where(
                    Workspace.id == workspace_id, Workspace.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if ws is None:
            raise PermissionDeniedError("workspace not available for this tenant")
        return ws.id, None
    return None, None


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
    request: Request,
    session: DbSession,
    user: CurrentUserDep,
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_workspace_id: Annotated[str | None, Header()] = None,
    x_location_id: Annotated[str | None, Header()] = None,
) -> TenantContext:
    """Resolve the active tenant, verify membership, enforce §48, bind RLS GUCs."""
    tenant_id = user.tenant_id
    if x_tenant_id:
        try:
            tenant_id = uuid.UUID(x_tenant_id)
        except ValueError as exc:
            raise PermissionDeniedError("invalid tenant header") from exc
    if tenant_id is None:
        raise PermissionDeniedError("no active tenant — switch or pick a tenant")

    # §151 — the scope headers are only parsed here; whether the caller may USE
    # the scope is decided by resolve_scope() after the tenant GUC is bound.
    workspace_hdr: uuid.UUID | None = None
    location_hdr: uuid.UUID | None = None
    if x_workspace_id:
        try:
            workspace_hdr = uuid.UUID(x_workspace_id)
        except ValueError as exc:
            raise PermissionDeniedError("invalid workspace header") from exc
    if x_location_id:
        try:
            location_hdr = uuid.UUID(x_location_id)
        except ValueError as exc:
            raise PermissionDeniedError("invalid location header") from exc

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

    # §48 — the lifecycle state gates the API. Checked AFTER membership so the
    # state is never disclosed to a non-member, and BEFORE binding the tenant
    # GUC so a blocked tenant never gets a queryable context. Before this,
    # nothing on the request path read the state at all: a suspended tenant
    # kept full API access indefinitely.
    lifecycle_state = (
        await session.execute(
            sa.select(Tenant.lifecycle_state).where(Tenant.id == tenant_id)
        )
    ).scalar_one_or_none()
    if lifecycle_state is None:
        raise PermissionDeniedError("tenant not found")
    if not tenant_may_use_api(lifecycle_state) and not _tenant_recovery_path(
        request.url.path
    ):
        raise PermissionDeniedError(
            f"workspace is {lifecycle_state} — only sign-in, billing, export "
            "and notifications are available"
        )

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
    # Publish the resolved tenant for infrastructure that runs OUTSIDE this
    # session — DatabaseSecretStore (§68) opens its own session and binds the
    # same tenant for RLS from the ambient context.
    set_current_tenant(tenant_id)
    await session.execute(
        sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user.id)}
    )
    # §151 — resolve and bind the workspace/location scope LAST: it needs the
    # tenant GUC (for hierarchy-table visibility) and the user GUC (for the
    # self-keyed user_location_access policy), both bound just above.
    # bind_scope always runs, even with no headers, so a stale scope can never
    # survive into this request from an earlier bind on the same transaction.
    scope_workspace_id, scope_location_id = await resolve_scope(
        session,
        tenant_id=tenant_id,
        user_id=user.id,
        workspace_id=workspace_hdr,
        location_id=location_hdr,
    )
    await bind_scope(session, scope_workspace_id, scope_location_id)
    return TenantContext(
        session=session,
        user=user,
        tenant_id=tenant_id,
        role_code=role_code,
        permission_codes=perms,
        workspace_id=scope_workspace_id,
        location_id=scope_location_id,
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
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthedUser | None:
    """Auth that tolerates anonymous callers (webchat, public webhooks)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        return await get_current_user(request, session, authorization)
    except PermissionDeniedError:
        return None


def require_platform_admin(user: CurrentUserDep) -> AuthedUser:
    """§146/§147: break-glass dependency — only is_platform_admin=True users pass.

    Used by platform-level routes (cross-tenant admin, billing, system audit)
    that no tenant role can access.
    """
    if not user.is_platform_admin:
        raise PermissionDeniedError("platform admin access required")
    return user


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
    "resolve_scope",
    "require_permission",
    "require_platform_admin",
    "NotFoundError",
]
