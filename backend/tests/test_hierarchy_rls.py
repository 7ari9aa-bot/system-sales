"""§151 Q1 — the hierarchy tables must obey RLS like everything else.

``workspaces`` and ``locations`` were created (migration 48528b41d6db) AFTER
the b2c3d4e5f6a7 hardening sweep — and unlike tenant_restore_jobs (§164 M7,
fixed by c166dd166dd1), they received NO policy at all: cross-tenant reads
were guarded only by an app-side filter. §151 makes the hierarchy load-bearing
(API + scope GUCs land in Q2/Q3), so the golden rule applies: RLS must reflect
the ownership hierarchy, not the caller's memory of it.

user_location_access already got a user-keyed policy in the sweep; its FORCE
flag is asserted here as a regression guard, and its admin-grant OR-clause is
deliberately NOT added yet — it belongs to Q3's API design (see task board).

DB-backed (CI-only): these tests prove the DATABASE refuses, not the ORM.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Location, UserLocationAccess, Workspace


async def _rebind(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )


async def test_hierarchy_tables_have_enable_and_force_rls(db: AsyncSession) -> None:
    rows = (
        await db.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('workspaces', 'locations', 'user_location_access') "
                "AND relkind = 'r'"
            )
        )
    ).all()
    assert {r[0] for r in rows} == {"workspaces", "locations", "user_location_access"}
    for name, enabled, forced in rows:
        assert enabled and forced, f"{name} must be ENABLE + FORCE ROW LEVEL SECURITY"


async def test_workspace_rows_are_invisible_to_other_tenants(
    db: AsyncSession, tenant_ctx
) -> None:
    ws = Workspace(tenant_id=tenant_ctx.tenant_id, name="North", slug="north")
    db.add(ws)
    await db.flush()

    await _rebind(db, uuid.uuid4())  # a stranger tenant
    rows = (
        await db.execute(select(Workspace).where(Workspace.id == ws.id))
    ).scalars().all()
    assert rows == [], "RLS — not the app filter — must hide the row"

    await _rebind(db, tenant_ctx.tenant_id)
    mine = (
        await db.execute(select(Workspace).where(Workspace.id == ws.id))
    ).scalars().all()
    assert [w.id for w in mine] == [ws.id]


async def test_workspace_insert_for_a_foreign_tenant_is_refused(
    db: AsyncSession, tenant_ctx
) -> None:
    """WITH CHECK: the GUC-bound writer cannot mint rows owned by someone else."""
    stranger = uuid.uuid4()
    db.add(Workspace(tenant_id=stranger, name="stolen", slug="stolen"))
    with pytest.raises(Exception) as excinfo:  # RLS violation → ProgrammedError
        await db.flush()
    assert "row-level security" in str(excinfo.value).lower()
    await db.rollback()
    await _rebind(db, tenant_ctx.tenant_id)


async def test_location_rows_are_isolated_two_levels_deep(
    db: AsyncSession, tenant_ctx
) -> None:
    """locations carry tenant_id directly — the same guard must hold there too."""
    ws = Workspace(
        tenant_id=tenant_ctx.tenant_id, name="Ops", slug=f"ops-{uuid.uuid4().hex[:6]}"
    )
    db.add(ws)
    await db.flush()
    loc = Location(
        tenant_id=tenant_ctx.tenant_id, workspace_id=ws.id, name="Cairo-1", code="CAI1"
    )
    db.add(loc)
    await db.flush()

    await _rebind(db, uuid.uuid4())
    rows = (
        await db.execute(select(Location).where(Location.id == loc.id))
    ).scalars().all()
    assert rows == []

    await _rebind(db, tenant_ctx.tenant_id)
    mine = (
        await db.execute(select(Location).where(Location.id == loc.id))
    ).scalars().all()
    assert [row.id for row in mine] == [loc.id]


async def test_location_access_stays_self_keyed(db: AsyncSession, tenant_ctx) -> None:
    """Regression guard: the sweep's user-keyed policy (app.user_id) must hold.

    A grant row is visible to the member it names — and to nobody else, even
    inside the same tenant. (Admin-grant writes need an OR-clause that only
    exists once the Q3 API defines the authorization shape — asserted there.)
    """
    ws = Workspace(
        tenant_id=tenant_ctx.tenant_id,
        name="Ops2",
        slug=f"ops2-{uuid.uuid4().hex[:6]}",
    )
    db.add(ws)
    await db.flush()
    loc = Location(tenant_id=tenant_ctx.tenant_id, workspace_id=ws.id, name="Giza")
    db.add(loc)
    await db.flush()

    member = uuid.uuid4()
    db.add(UserLocationAccess(user_id=member, location_id=loc.id))
    await db.flush()

    rows = (
        await db.execute(
            select(UserLocationAccess).where(UserLocationAccess.user_id == member)
        )
    ).scalars().all()
    assert rows == [], "app.user_id is bound to the OWNER — not the member"

    await db.execute(
        text("SELECT set_config('app.user_id', :u, true)"), {"u": str(member)}
    )
    mine = (
        await db.execute(
            select(UserLocationAccess).where(UserLocationAccess.user_id == member)
        )
    ).scalars().all()
    assert [g.location_id for g in mine] == [loc.id]
