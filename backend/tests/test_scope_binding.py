"""§151 Q2 — workspace/location scope GUCs and fail-closed scope resolution.

Two layers are proven here:
1. `bind_tenant`/`bind_scope` (core/db): app.workspace_id / app.location_id are
   set transaction-local like app.tenant_id, and bind_scope clears what the
   caller omits so a stale scope can never leak into a later bind.
2. `resolve_scope`/`get_tenant_ctx` (identity/deps): the X-Workspace-Id /
   X-Location-Id headers are validated fail-closed — a workspace must belong to
   the tenant, a location must belong to the tenant AND be explicitly granted
   to the user via user_location_access. Nothing is auto-derived upward.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_scope, bind_tenant
from app.core.errors import PermissionDeniedError
from app.modules.identity.deps import (
    AuthedUser,
    TenantContext,
    get_tenant_ctx,
    resolve_scope,
)
from app.modules.identity.models import (
    Location,
    Tenant,
    UserLocationAccess,
    Workspace,
)


async def _guc(session: AsyncSession, name: str) -> str | None:
    return (
        await session.execute(
            sa.text("SELECT current_setting(:guc, true)"), {"guc": name}
        )
    ).scalar()


def test_tenant_context_defaults_scope_to_none() -> None:
    ctx = TenantContext(
        session=None,  # type[arg-type]
        user=None,  # type[arg-type]
        tenant_id=uuid.uuid4(),
        role_code="owner",
        permission_codes=set(),
    )
    assert ctx.workspace_id is None
    assert ctx.location_id is None


async def test_bind_tenant_binds_optional_scope(db: AsyncSession) -> None:
    w, loc = uuid.uuid4(), uuid.uuid4()
    await bind_tenant(db, uuid.uuid4(), workspace_id=w, location_id=loc)
    assert await _guc(db, "app.workspace_id") == str(w)
    assert await _guc(db, "app.location_id") == str(loc)


async def test_bind_tenant_without_scope_leaves_scope_unbound(db: AsyncSession) -> None:
    await bind_tenant(db, uuid.uuid4())
    assert await _guc(db, "app.workspace_id") is None
    assert await _guc(db, "app.location_id") is None


async def test_bind_scope_sets_and_clears(db: AsyncSession) -> None:
    w, loc = uuid.uuid4(), uuid.uuid4()
    await bind_scope(db, w, loc)
    assert await _guc(db, "app.workspace_id") == str(w)
    assert await _guc(db, "app.location_id") == str(loc)
    # Omitting must CLEAR — a request that binds no scope must not inherit
    # the scope a previous bind in the same transaction left behind.
    await bind_scope(db, None, None)
    assert await _guc(db, "app.workspace_id") is None
    assert await _guc(db, "app.location_id") is None


async def _seed_workspace(db: AsyncSession, tenant_id: uuid.UUID) -> Workspace:
    ws = Workspace(tenant_id=tenant_id, name="HQ", slug=uuid.uuid4().hex[:12])
    db.add(ws)
    await db.flush()
    return ws


async def _seed_location(db: AsyncSession, ws: Workspace) -> Location:
    loc = Location(tenant_id=ws.tenant_id, workspace_id=ws.id, name="Branch 1")
    db.add(loc)
    await db.flush()
    return loc


async def test_resolve_scope_accepts_tenant_workspace(db: AsyncSession, tenant_ctx) -> None:
    ws = await _seed_workspace(db, tenant_ctx.tenant_id)
    resolved = await resolve_scope(
        db,
        tenant_id=tenant_ctx.tenant_id,
        user_id=tenant_ctx.user.id,
        workspace_id=ws.id,
    )
    assert resolved == (ws.id, None)


async def test_resolve_scope_refuses_foreign_workspace(db: AsyncSession, tenant_ctx) -> None:
    other = Tenant(slug=f"other-{uuid.uuid4().hex[:8]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    foreign_ws = await _seed_workspace(db, other.id)
    await bind_tenant(db, tenant_ctx.tenant_id)

    with pytest.raises(PermissionDeniedError):
        await resolve_scope(
            db,
            tenant_id=tenant_ctx.tenant_id,
            user_id=tenant_ctx.user.id,
            workspace_id=foreign_ws.id,
        )


async def test_resolve_scope_refuses_location_without_grant(
    db: AsyncSession, tenant_ctx
) -> None:
    ws = await _seed_workspace(db, tenant_ctx.tenant_id)
    loc = await _seed_location(db, ws)
    with pytest.raises(PermissionDeniedError):
        await resolve_scope(
            db,
            tenant_id=tenant_ctx.tenant_id,
            user_id=tenant_ctx.user.id,
            location_id=loc.id,
        )


async def test_resolve_scope_accepts_granted_location(db: AsyncSession, tenant_ctx) -> None:
    ws = await _seed_workspace(db, tenant_ctx.tenant_id)
    loc = await _seed_location(db, ws)
    # app.user_id is already the owner (tenant_ctx binds it), so the
    # self-keyed location_access policy admits their own grant row.
    db.add(UserLocationAccess(user_id=tenant_ctx.user.id, location_id=loc.id))
    await db.flush()
    resolved = await resolve_scope(
        db,
        tenant_id=tenant_ctx.tenant_id,
        user_id=tenant_ctx.user.id,
        location_id=loc.id,
    )
    # Workspace is derived DOWNWARD from the location, never widened upward.
    assert resolved == (ws.id, loc.id)


async def test_resolve_scope_refuses_location_outside_bound_workspace(
    db: AsyncSession, tenant_ctx
) -> None:
    ws_a = await _seed_workspace(db, tenant_ctx.tenant_id)
    ws_b = await _seed_workspace(db, tenant_ctx.tenant_id)
    loc_b = await _seed_location(db, ws_b)
    db.add(UserLocationAccess(user_id=tenant_ctx.user.id, location_id=loc_b.id))
    await db.flush()
    with pytest.raises(PermissionDeniedError):
        await resolve_scope(
            db,
            tenant_id=tenant_ctx.tenant_id,
            user_id=tenant_ctx.user.id,
            workspace_id=ws_a.id,
            location_id=loc_b.id,
        )


async def test_resolve_scope_refuses_foreign_tenant_location(
    db: AsyncSession, tenant_ctx
) -> None:
    other = Tenant(slug=f"other-{uuid.uuid4().hex[:8]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    foreign_ws = await _seed_workspace(db, other.id)
    foreign_loc = await _seed_location(db, foreign_ws)
    await bind_tenant(db, tenant_ctx.tenant_id)

    with pytest.raises(PermissionDeniedError):
        await resolve_scope(
            db,
            tenant_id=tenant_ctx.tenant_id,
            user_id=tenant_ctx.user.id,
            location_id=foreign_loc.id,
        )


def _fake_request(path: str = "/api/v1/orders") -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path=path))


async def test_get_tenant_ctx_resolves_headers_into_ctx_and_gucs(
    db: AsyncSession, tenant_ctx
) -> None:
    ws = await _seed_workspace(db, tenant_ctx.tenant_id)
    loc = await _seed_location(db, ws)
    db.add(UserLocationAccess(user_id=tenant_ctx.user.id, location_id=loc.id))
    await db.flush()

    user = AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner")
    ctx = await get_tenant_ctx(
        _fake_request(),
        db,
        user,
        x_workspace_id=str(ws.id),
        x_location_id=str(loc.id),
    )
    assert ctx.workspace_id == ws.id
    assert ctx.location_id == loc.id
    assert await _guc(db, "app.workspace_id") == str(ws.id)
    assert await _guc(db, "app.location_id") == str(loc.id)


async def test_get_tenant_ctx_refuses_unganted_location_header(
    db: AsyncSession, tenant_ctx
) -> None:
    ws = await _seed_workspace(db, tenant_ctx.tenant_id)
    loc = await _seed_location(db, ws)

    user = AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner")
    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(
            _fake_request(), db, user, x_location_id=str(loc.id)
        )

    # The failure must not have left a scope bound on the transaction.
    assert await _guc(db, "app.location_id") is None


async def test_get_tenant_ctx_rejects_malformed_scope_headers(
    db: AsyncSession, tenant_ctx
) -> None:
    user = AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner")
    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(
            _fake_request(), db, user, x_workspace_id="not-a-uuid"
        )
    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(
            _fake_request(), db, user, x_location_id="12345"
        )
