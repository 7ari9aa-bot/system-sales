"""import_sessions / import_rows: tenant isolation and the idempotency key, on a real database.

Runs as the ``sales_app`` role (no BYPASSRLS), so the policies are actually enforced.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.core.db import bind_tenant
from app.modules.identity.models import Tenant
from app.modules.imports.models import ImportRow, ImportSession


async def _other_tenant(db) -> uuid.UUID:
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Shop")
    db.add(other)
    await db.flush()
    return other.id


async def _session(db, tenant_id: uuid.UUID, name: str = "a.xlsx") -> ImportSession:
    s = ImportSession(tenant_id=tenant_id, kind="products", file_name=name)
    db.add(s)
    await db.flush()
    return s


async def test_defaults_are_applied_by_the_database(db, tenant_ctx):
    s = await _session(db, tenant_ctx.tenant_id)
    row = (
        await db.execute(
            sa.text("select status, mapping, options, stats from import_sessions where id = :i"),
            {"i": s.id},
        )
    ).one()
    assert row.status == "uploaded"
    assert row.mapping == {} and row.options == {} and row.stats == {}


async def test_a_tenant_cannot_see_another_tenants_sessions_or_rows(db, tenant_ctx):
    mine = await _session(db, tenant_ctx.tenant_id, "mine.xlsx")
    db.add(
        ImportRow(
            tenant_id=tenant_ctx.tenant_id,
            session_id=mine.id,
            sheet="Products",
            row_number=2,
            raw={"a": "1"},
        )
    )
    await db.flush()

    other_id = await _other_tenant(db)
    await bind_tenant(db, other_id)
    theirs = await _session(db, other_id, "theirs.xlsx")
    db.add(
        ImportRow(
            tenant_id=other_id, session_id=theirs.id, sheet="Products", row_number=2, raw={"a": "2"}
        )
    )
    await db.flush()

    sessions = (await db.execute(sa.text("select file_name from import_sessions"))).scalars().all()
    rows = (await db.execute(sa.text("select raw->>'a' from import_rows"))).scalars().all()
    assert sessions == ["theirs.xlsx"] and rows == ["2"]

    await bind_tenant(db, tenant_ctx.tenant_id)
    sessions = (await db.execute(sa.text("select file_name from import_sessions"))).scalars().all()
    assert sessions == ["mine.xlsx"]


async def test_a_tenant_cannot_write_a_row_for_another_tenant(db, tenant_ctx):
    other_id = await _other_tenant(db)
    with pytest.raises(sa.exc.DBAPIError, match="row-level security"):
        await _session(db, other_id)


async def test_a_row_position_can_only_exist_once_per_session(db, tenant_ctx):
    s = await _session(db, tenant_ctx.tenant_id)
    db.add(
        ImportRow(
            tenant_id=tenant_ctx.tenant_id, session_id=s.id, sheet="Variants", row_number=5, raw={}
        )
    )
    await db.flush()
    db.add(
        ImportRow(
            tenant_id=tenant_ctx.tenant_id, session_id=s.id, sheet="Variants", row_number=5, raw={}
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_status_and_kind_are_checked_by_the_database(db, tenant_ctx):
    s = ImportSession(tenant_id=tenant_ctx.tenant_id, kind="bogus", file_name="x")
    db.add(s)
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_deleting_a_session_removes_its_rows(db, tenant_ctx):
    s = await _session(db, tenant_ctx.tenant_id)
    db.add(
        ImportRow(
            tenant_id=tenant_ctx.tenant_id, session_id=s.id, sheet="Products", row_number=2, raw={}
        )
    )
    await db.flush()
    await db.execute(sa.text("delete from import_sessions where id = :i"), {"i": s.id})
    left = (await db.execute(sa.text("select count(*) from import_rows"))).scalar_one()
    assert left == 0
