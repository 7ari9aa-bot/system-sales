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
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_scope, bind_tenant
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.security import decode_token
from app.core.tenancy import DEFAULT_CURRENCY, set_current_scope, set_current_tenant
from app.modules.identity import cookies
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
    if path.startswith(_TENANT_RECOVERY_PREFIXES):
        return True
    # Workspace recovery must remain reachable after offboarding starts, but
    # do not exempt the whole tenants API from the lifecycle gate. POST
    # /tenants/{id}/lifecycle is deliberately NOT exempt (external audit
    # finding 1): with the platform-admin authority split, a suspended tenant
    # has nothing left to negotiate on this route — restoring service is the
    # platform admin's job via the §147 break-glass route, and a blocked
    # tenant must not be able to even probe the transition surface. (The
    # offboarding export/status exemptions below stay: they are read/export
    # hatches for a state the tenant itself is already in.)
    parts = path.rstrip("/").strip("/").split("/")
    if len(parts) == 6 and parts[:3] == ["api", "v1", "tenants"]:
        return parts[4] == "offboarding" and parts[5] in {"export", "status"}
    return False


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
    # Lazy: app.core.db resolves SessionLocal through __getattr__ PER ACCESS,
    # so tests can bind the app's sessions to the test transaction
    # (conftest's app_sessions_on_test_connection). An import-time binding
    # would freeze the pre-patch factory and break that binding forever.
    from app.core.db import SessionLocal

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
    auth_version: int = 0
    # DB-verified per request (the deps query reads it alongside auth_version):
    # services reached with an AuthedUser may rely on it instead of re-querying.
    is_active: bool = False


def _extract_access_token(request: Request, authorization: str | None) -> tuple[str, bool]:
    """The access token + whether it arrived by COOKIE (vs the Bearer header).

    Header wins. The cookie fallback powers the HttpOnly delivery path; the
    boolean drives the CSRF gate, which only cookie callers owe (a Bearer
    header cannot be attached by a cross-site form, so it needs no CSRF).
    """
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip(), False
    cookie_token = request.cookies.get(cookies.ACCESS_COOKIE)
    if cookie_token:
        return cookie_token, True
    raise PermissionDeniedError("missing bearer token")


async def get_current_user(
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthedUser:
    token, cookie_authenticated = _extract_access_token(request, authorization)
    if not cookies.csrf_satisfied(request, cookie_authenticated=cookie_authenticated):
        raise PermissionDeniedError("missing or mismatched csrf token")
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
        auth_state = (
            await session.execute(
                select(User.is_active, User.auth_version, User.is_platform_admin).where(
                    User.id == user_id
                )
            )
        ).one_or_none()
        if auth_state is None or not auth_state.is_active:
            raise PermissionDeniedError("account is inactive")
        if int(payload.get("auth_version", 0)) != int(auth_state.auth_version or 0):
            raise PermissionDeniedError("session revoked by password reset")
        # The platform-admin flag as a transaction-local GUC: RLS policies on
        # the system tables (security_events NULL-tenant rows) read it. It is
        # verified against the users row on EVERY request — a demoted admin
        # loses cross-tenant visibility immediately, never at token expiry,
        # because the JWT claim is not trusted for this gate.
        db_platform_admin = bool(auth_state.is_platform_admin)
        await session.execute(
            sa_text("SELECT set_config('app.is_platform_admin', :v, true)"),
            {"v": "true" if db_platform_admin else "false"},
        )
        return AuthedUser(
            id=user_id,
            tenant_id=uuid.UUID(payload["tenant_id"]) if payload.get("tenant_id") else None,
            role_code=payload.get("role"),
            is_platform_admin=db_platform_admin,
            auth_version=int(auth_state.auth_version or 0),
            is_active=bool(auth_state.is_active),
        )
    except PermissionDeniedError:
        raise
    except sa.exc.SQLAlchemyError:
        # A database failure is a 5xx — the request never reached the token
        # validation verdict, so answering 403 would log every user out on a
        # transient connection blip.
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
    # §47: the currency this tenant trades in, read with the lifecycle state on
    # the same SELECT. Every money write on this request path stamps it, so a
    # price tier or an invoice line in another currency is a refusal rather
    # than a conversion — and no caller has to guess a literal.
    currency: str = DEFAULT_CURRENCY
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
    #
    # The currency (§47) rides the SAME SELECT: it is a property of the same
    # row, the request needs it for every money write, and reading it here is
    # what keeps `orders`/`billing`/`catalog` from importing `identity` to ask —
    # an edge the module-boundary ratchet counts.
    tenant_row = (
        await session.execute(
            sa.select(Tenant.lifecycle_state, Tenant.currency).where(Tenant.id == tenant_id)
        )
    ).first()
    if tenant_row is None:
        raise PermissionDeniedError("tenant not found")
    lifecycle_state, tenant_currency = tenant_row
    if not tenant_may_use_api(lifecycle_state) and not _tenant_recovery_path(request.url.path):
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
    # §151 Q4: publish the resolved scope for the request task — mixin rows and
    # outbox envelopes stamp from it. A contextvars .set() here is visible to
    # the endpoint (same task) and invisible to other requests (per-task copy).
    set_current_scope(scope_workspace_id, scope_location_id)
    return TenantContext(
        session=session,
        user=user,
        tenant_id=tenant_id,
        role_code=role_code,
        permission_codes=perms,
        currency=tenant_currency,
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
    if not authorization and not request.cookies.get(cookies.ACCESS_COOKIE):
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
