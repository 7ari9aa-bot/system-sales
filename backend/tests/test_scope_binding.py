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
    value = (
        await session.execute(sa.text("SELECT current_setting(:guc, true)"), {"guc": name})
    ).scalar()
    # set_config(guc, NULL) stores ''; the canonical NULLIF(...,'') guard
    # treats '' exactly like unset — both mean "unbound", so the test does too.
    return value or None


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


async def test_resolve_scope_refuses_location_without_grant(db: AsyncSession, tenant_ctx) -> None:
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


async def test_resolve_scope_refuses_foreign_tenant_location(db: AsyncSession, tenant_ctx) -> None:
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
    # §151 Q4: the resolved scope is also published to the request context —
    # WorkspaceScopeMixin inserts and outbox envelopes stamp from it there.
    from app.core.tenancy import current_scope, reset_current_scope, set_current_scope

    assert current_scope() == (ws.id, loc.id)
    # Restore the unscoped default so no sibling test inherits this scope.
    reset_current_scope(set_current_scope(None, None))


async def test_get_tenant_ctx_refuses_unganted_location_header(
    db: AsyncSession, tenant_ctx
) -> None:
    ws = await _seed_workspace(db, tenant_ctx.tenant_id)
    loc = await _seed_location(db, ws)

    user = AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner")
    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(_fake_request(), db, user, x_location_id=str(loc.id))

    # The failure must not have left a scope bound on the transaction.
    assert await _guc(db, "app.location_id") is None


async def test_get_tenant_ctx_rejects_malformed_scope_headers(db: AsyncSession, tenant_ctx) -> None:
    user = AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner")
    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(_fake_request(), db, user, x_workspace_id="not-a-uuid")
    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(_fake_request(), db, user, x_location_id="12345")


# ---------------------------------------------------------- bind transport ---
# WP 10.2 verify item 1: the GUC travels as an engine bind parameter on a fixed
# statement, and the binding is transaction-scoped so a pooled connection never
# carries one request's tenant into the next.


async def test_bind_tenant_travels_as_a_bind_parameter_not_interpolated() -> None:
    """Fail-first: if a future edit interpolates the tenant id into the SQL
    text (SET is a utility statement, so someone may "simplify" to it), a
    crafted tenant id becomes SQL injection at the RLS bind site. The tenant
    id must arrive as a bind param, never inside the statement text."""
    captured: list[tuple[str, dict[str, str] | None]] = []

    class _RecordSession:
        async def execute(self, stmt, params=None):  # noqa: ANN001
            captured.append((str(stmt), params))

    tid = uuid.uuid4()
    await bind_tenant(_RecordSession(), tid)
    sql, params = captured[0]
    assert str(tid) not in sql
    assert params == {"guc": "app.tenant_id", "tenant_id": str(tid)}


async def test_bind_tenant_rejects_a_malformed_id_before_any_db_work() -> None:
    """Fail-first: every policy casts current_setting(...)::uuid, so a
    malformed id bound silently would 500 the NEXT query with a Postgres cast
    error instead of failing at the bind site. The session here fakes execute
    (a real session would need a database), so a ValueError can only come
    from the id validation itself."""

    class _NullSession:
        async def execute(self, stmt, params=None):  # noqa: ANN001
            pass

    with pytest.raises(ValueError):
        await bind_tenant(_NullSession(), "not-a-uuid")
    with pytest.raises(ValueError):
        await bind_tenant(_NullSession(), uuid.uuid4(), workspace_id="not-a-uuid")


async def test_a_bound_guc_does_not_survive_commit_or_rollback_on_the_connection(
    db_url,
) -> None:
    """The pooler no-leak half of verify item 1: set_config(..., is_local :=
    true) is transaction-scoped, so the tenant bound for request 1 must be
    UNBOUND for request 2 on the SAME connection — after commit and after
    rollback alike, or the pool would hand one tenant's RLS context to the
    next request. Uses its own engine: the conftest ``db`` fixture nests in
    savepoints, which would mask the transaction boundary this pins."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.db import TENANT_GUC

    def _normalize(value: str | None) -> str | None:
        return value or None  # set_config(guc, NULL) stores '' — same as unset

    engine = create_async_engine(db_url, connect_args={"statement_cache_size": 0})
    a, b = uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.connect() as conn:

            async def setting() -> str | None:
                return _normalize(
                    (
                        await conn.execute(
                            sa.text("SELECT current_setting(:g, true)"),
                            {"g": TENANT_GUC},
                        )
                    ).scalar()
                )

            async with conn.begin():
                await bind_tenant(conn, a)
                assert await setting() == str(a)
            # committed — the next request on this connection starts unbound
            async with conn.begin():
                assert await setting() is None, "GUC leaked across COMMIT"
            async with conn.begin() as tx:
                await bind_tenant(conn, b)
                assert await setting() == str(b)
                await tx.rollback()
            # rolled back — equally unbound for the next request
            async with conn.begin():
                assert await setting() is None, "GUC leaked across ROLLBACK"
    finally:
        await engine.dispose()
