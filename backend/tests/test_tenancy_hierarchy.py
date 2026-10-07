"""Tenancy hierarchy tests (spec §151) — tenant → workspace → location → user.

Two layers:
- metadata-level assertions (no DB writes) — always run;
- DB-backed tests via the shared conftest fixtures (db, tenant_ctx) that
  insert real rows and exercise the unique constraints.

The hierarchy tables are created permanently by the integrator's migration
(and get RLS via scripts/provision.py). When the suite runs against a
pre-migration database, the ``hierarchy`` fixture creates them through the
admin (migrations) DSN, tags them with a marker comment and drops them again
in teardown; migration-created tables are never touched.

NOTE: the ``hierarchy`` fixture MUST be requested BEFORE ``db`` in the test
signature. Its teardown (DROP) has to run after the test transaction rolled
back, otherwise the DROP blocks on locks still held by that transaction.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import get_settings
from app.core.db import bind_tenant
from app.core.model_registry import Base
from app.modules.identity.models import Location, Tenant, UserLocationAccess, Workspace

HIERARCHY_TABLES = (
    Workspace.__table__,
    Location.__table__,
    UserLocationAccess.__table__,
)
_TABLES_BY_NAME = {t.name: t for t in HIERARCHY_TABLES}
# teardown order: children before parents
_DROP_ORDER = ("user_location_access", "locations", "workspaces")
_DDL_MARKER = "tenancy-hierarchy-test-ddl (wave 2A)"

_ADMIN_DSN_UNUSABLE = False  # only ever try the admin DSN once per run


def _admin_engine() -> AsyncEngine | None:
    dsn = get_settings().database_url_admin or ""
    if not dsn:
        return None
    return create_async_engine(dsn, connect_args={"statement_cache_size": 0})


def _hierarchy_state(sync_conn) -> dict[str, tuple[bool, bool]]:
    """Per hierarchy table: (exists, marked as test-created DDL)."""
    out: dict[str, tuple[bool, bool]] = {}
    for name in _DROP_ORDER:
        exists, marked = sync_conn.execute(
            sa.text(
                "SELECT to_regclass(:t) IS NOT NULL,"
                " COALESCE(obj_description(to_regclass(:t), 'pg_class'), '') = :m"
            ),
            {"t": f"public.{name}", "m": _DDL_MARKER},
        ).one()
        out[name] = (bool(exists), bool(marked))
    return out


def _create_missing_hierarchy_tables(sync_conn, missing: list[str]) -> None:
    Base.metadata.create_all(sync_conn, tables=[_TABLES_BY_NAME[n] for n in missing])
    for name in missing:
        # Mark as test-created so teardown (and later runs) can distinguish
        # them from tables the integrator's migration created.
        sync_conn.execute(sa.text(f"COMMENT ON TABLE public.{name} IS '{_DDL_MARKER}'"))


async def _drop_marked_hierarchy_tables(engine) -> None:
    """Drop only marker-commented tables — never migration-created ones."""
    async with engine.connect() as conn:
        state = await conn.run_sync(_hierarchy_state)
    targets = [name for name in _DROP_ORDER if state[name][0] and state[name][1]]
    if not targets:
        return
    for attempt in (1, 2):
        try:
            async with engine.begin() as conn:
                await conn.execute(sa.text("SET lock_timeout = '10s'"))
                for name in targets:
                    await conn.execute(sa.text(f"DROP TABLE IF EXISTS public.{name}"))
            return
        except sa.exc.DBAPIError:
            if attempt == 2:
                raise
            await asyncio.sleep(3)


@pytest.fixture
async def hierarchy() -> AsyncIterator[None]:
    """Ensure the three hierarchy tables exist for the duration of one test."""
    global _ADMIN_DSN_UNUSABLE

    if _ADMIN_DSN_UNUSABLE:
        pytest.skip("admin DSN unusable — hierarchy tables cannot be ensured")
    engine = _admin_engine()
    if engine is None:
        pytest.skip("hierarchy tables not migrated and no admin DSN configured")

    created = False
    try:
        try:
            async with engine.connect() as conn:
                state = await conn.run_sync(_hierarchy_state)
        except sa.exc.DBAPIError:
            _ADMIN_DSN_UNUSABLE = True
            pytest.skip("hierarchy tables not migrated; admin DSN unusable")

        if all(exists and not marked for exists, marked in state.values()):
            yield  # migrated world — nothing to create, nothing to drop
            return

        # Reclaim leftovers of an aborted earlier run (marker-identified only).
        if any(marked for _, marked in state.values()):
            await _drop_marked_hierarchy_tables(engine)
            async with engine.connect() as conn:
                state = await conn.run_sync(_hierarchy_state)

        missing = [name for name, (exists, _) in state.items() if not exists]
        if not missing:
            yield  # everything exists unmarked — migrated world
            return

        async with engine.begin() as conn:
            await conn.run_sync(_create_missing_hierarchy_tables, missing)
        created = True
        yield
    finally:
        if created:
            await _drop_marked_hierarchy_tables(engine)
        await engine.dispose()


# ---------------------------------------------------------------------------
# metadata-level (no DB writes — always run)
# ---------------------------------------------------------------------------


def test_workspace_scope_columns_on_tenant_tables():
    """WorkspaceScopeMixin landed on TenantMixin tables as nullable SET NULL FKs."""
    for name in ("orders", "customers", "conversations", "agents", "warehouses", "leads"):
        table = Base.metadata.tables[name]
        assert "workspace_id" in table.c
        assert "location_id" in table.c
        assert table.c.workspace_id.nullable
        assert table.c.location_id.nullable
        fks = {fk.parent.name: fk for fk in table.foreign_keys}
        assert fks["workspace_id"].column.table.name == "workspaces"
        assert fks["location_id"].column.table.name == "locations"
        assert fks["workspace_id"].ondelete == "SET NULL"
        assert fks["location_id"].ondelete == "SET NULL"


def test_scope_columns_absent_from_exempt_tables():
    """Identity/global/system tables stay untouched by the scope mixin."""
    for name in (
        "tenants",
        "users",
        "roles",
        "refresh_tokens",
        "invitations",
        "plans",
        "audit_logs",
        "outbox_events",
        "idempotency_keys",
        "webhook_events",
        "workspaces",
    ):
        cols = Base.metadata.tables[name].c
        assert "workspace_id" not in cols, name
        assert "location_id" not in cols, name


def test_hierarchy_table_shapes():
    """PKs, unique constraints and uuid7 defaults of the three new tables."""
    ws = Base.metadata.tables["workspaces"]
    loc = Base.metadata.tables["locations"]
    ula = Base.metadata.tables["user_location_access"]

    assert {c.name for c in ws.primary_key.columns} == {"id"}
    assert {c.name for c in loc.primary_key.columns} == {"id"}
    assert {c.name for c in ula.primary_key.columns} == {"user_id", "location_id"}

    ws_uqs = [
        {c.name for c in u.columns} for u in ws.constraints if isinstance(u, sa.UniqueConstraint)
    ]
    assert {"tenant_id", "slug"} in ws_uqs
    loc_uqs = [
        {c.name for c in u.columns} for u in loc.constraints if isinstance(u, sa.UniqueConstraint)
    ]
    assert {"tenant_id", "workspace_id", "code"} in loc_uqs

    # spec §142: new tables use uuid7 PK defaults. Name+module pin the wiring;
    # the version-bit probe is skipped if another wave changed the callable's
    # signature (SQLAlchemy adapts 1-arg defaults with an execution context).
    for col in (ws.c.id, loc.c.id):
        assert col.default.arg.__name__ == "uuid7"
        assert col.default.arg.__module__ == "app.core.ids"
        try:
            probe = uuid.UUID(int=col.default.arg())
        except TypeError:
            continue
        assert (probe.int >> 76) & 0xF == 7


# ---------------------------------------------------------------------------
# DB-backed (real inserts against the sales_app role, rolled back per test)
# ---------------------------------------------------------------------------


async def test_workspace_location_access_flow(hierarchy, db: AsyncSession, tenant_ctx):
    """workspace → location → user_location_access under the bound tenant."""
    ws = Workspace(tenant_id=tenant_ctx.tenant_id, name="HQ", slug="hq")
    db.add(ws)
    await db.flush()

    loc = Location(tenant_id=tenant_ctx.tenant_id, workspace_id=ws.id, name="Branch 1", code="BR1")
    db.add(loc)
    await db.flush()

    db.add(UserLocationAccess(user_id=tenant_ctx.user.id, location_id=loc.id))
    await db.flush()

    got = (await db.execute(sa.select(Location).where(Location.workspace_id == ws.id))).scalar_one()
    assert got.id == loc.id
    assert got.tenant_id == tenant_ctx.tenant_id
    assert ws.is_active is True  # Python-side default visible after flush
    assert loc.is_active is True

    grants = (
        (
            await db.execute(
                sa.select(UserLocationAccess).where(
                    UserLocationAccess.user_id == tenant_ctx.user.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [g.location_id for g in grants] == [loc.id]
    assert all(g.role_override is None and g.created_at is not None for g in grants)


async def test_hierarchy_unique_constraints_fire(hierarchy, db: AsyncSession, tenant_ctx):
    """Duplicate slug / code / (user, location) pairs are rejected."""
    tenant_id = tenant_ctx.tenant_id
    user_id = tenant_ctx.user.id

    ws = Workspace(tenant_id=tenant_id, name="Main", slug="dup-ws")
    other_ws = Workspace(tenant_id=tenant_id, name="Second", slug="dup-loc")
    db.add_all([ws, other_ws])
    await db.flush()

    loc = Location(tenant_id=tenant_id, workspace_id=other_ws.id, name="Store 1", code="SAME")
    db.add(loc)
    await db.flush()  # loc.id must exist before it is referenced below

    db.add(UserLocationAccess(user_id=user_id, location_id=loc.id))
    await db.flush()

    with pytest.raises(sa.exc.IntegrityError):  # duplicate (tenant_id, slug)
        async with db.begin_nested():
            db.add(Workspace(tenant_id=tenant_id, name="Clone", slug="dup-ws"))
            await db.flush()

    with pytest.raises(sa.exc.IntegrityError):  # duplicate (tenant, workspace, code)
        async with db.begin_nested():
            db.add(
                Location(
                    tenant_id=tenant_id,
                    workspace_id=other_ws.id,
                    name="Store 2",
                    code="SAME",
                )
            )
            await db.flush()

    with pytest.raises(sa.exc.IntegrityError):  # duplicate composite PK pair
        async with db.begin_nested():
            db.add(UserLocationAccess(user_id=user_id, location_id=loc.id))
            await db.flush()


async def test_workspace_slug_unique_per_tenant(hierarchy, db: AsyncSession, tenant_ctx):
    """The same slug is allowed across different tenants (per-tenant uniqueness)."""
    tenant_id = tenant_ctx.tenant_id

    first = Workspace(tenant_id=tenant_id, name="One", slug="shared")
    db.add(first)
    await db.flush()

    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Tenant")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)  # needed once the tenant policy is live
    second = Workspace(tenant_id=other.id, name="Two", slug="shared")
    db.add(second)
    await db.flush()
    await bind_tenant(db, tenant_id)

    assert first.slug == second.slug == "shared"
    assert first.tenant_id != second.tenant_id
