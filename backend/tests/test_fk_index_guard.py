"""Guard tests for fe2026100803_add_missing_fk_indexes.

The first production deploy of this migration aborted on
`ix_pos_cash_movements_created_by`: production's `pos_cash_movements` predates
its `created_by` column, so the TABLE guard passed and CREATE INDEX died on a
missing COLUMN. The fix guards the table AND every indexed column — and this
file pins the four scenarios that fix must survive (the ones the plan
mandated):

1. table exists + column exists        → index IS created;
2. table exists + column drifted away  → index is NOT created, no error;
3. table missing entirely              → quiet skip, no error;
4. one drifted column feeding SEVERAL indexes → every index on it skipped.

Plus the post-upgrade invariant on a real migrated database: every entry
whose table and columns exist must have its index present — the guard is
allowed to skip drifted schema, never to silently skip healthy schema.

The scenario tests execute the migration's OWN generated DDL
(`_guarded_index_ddl`) as the ADMIN role on purpose: in production the
migration runs as the admin, and sales_app cannot index tables it does not
own. The invariant test likewise reads catalogs as admin; RLS behaviour for
the runtime role is covered by the isolation suite, not here.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"
FK_INDEXES_MIGRATION = VERSIONS_DIR / "fe2026100803_add_missing_fk_indexes.py"


def _migration():
    spec = importlib.util.spec_from_file_location("_fk_indexes_migration", FK_INDEXES_MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _admin_url() -> str:
    url = os.environ.get("DATABASE_URL_ADMIN")
    if not url:
        pytest.skip("DATABASE_URL_ADMIN not configured — the guard runs as the admin role")
    return url


@pytest.fixture()
async def admin_engine():
    engine = create_async_engine(_admin_url())
    try:
        yield engine
    finally:
        await engine.dispose()


async def _table_exists(engine, table: str) -> bool:
    async with engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"})
        ).scalar()
    return row is not None


async def _index_exists(engine, index: str) -> bool:
    async with engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT to_regclass(:i)"), {"i": f"public.{index}"})
        ).scalar()
    return row is not None


# -------------------------------------------------- static (no database) ----


def test_every_entry_keeps_both_guards() -> None:
    """Fail-first: losing `to_regclass` re-introduces the missing-TABLE abort
    (fresh builds have no ai_usage_* partitions); losing the
    information_schema guard re-introduces the missing-COLUMN abort that took
    production down."""
    mig = _migration()
    for idx_name, table, cols in mig._INDEXES:
        ddl = mig._guarded_index_ddl(idx_name, table, cols)
        assert "to_regclass('public.{table}')".replace("{table}", table) in ddl, idx_name
        assert "information_schema.columns" in ddl, idx_name
        assert "CREATE INDEX IF NOT EXISTS" in ddl, idx_name


def test_the_drifted_production_index_is_not_in_the_list() -> None:
    """The index that aborted production (`created_by` alone on a table whose
    column drifted) must never return in its old shape: the replacement
    composite indexes only columns the domain actually
    defines."""
    mig = _migration()
    assert (
        "ix_pos_cash_movements_created_by",
        "pos_cash_movements",
        "created_by",
    ) not in mig._INDEXES


# ------------------------------------- dynamic (admin on a real database) ----


async def test_guard_creates_the_index_when_table_and_column_exist(admin_engine) -> None:
    mig = _migration()
    ddl = mig._guarded_index_ddl("ix__fx_guard_present_a", "_fx_guard_present", "a")
    async with admin_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS _fx_guard_present"))
        await conn.execute(text("CREATE TABLE _fx_guard_present(id int, a int)"))
        await conn.execute(text(ddl))
    # Post-commit: a second connection is the honest witness — the guard's
    # own transaction cannot vouch for what another connection sees.
    assert await _index_exists(admin_engine, "ix__fx_guard_present_a")


async def test_guard_skips_quietly_when_the_column_drifted_away(admin_engine) -> None:
    """The exact production abort scenario, now expected to SKIP: the table
    survived while the indexed column never made it to this database."""
    mig = _migration()
    ddl = mig._guarded_index_ddl("ix__fx_guard_drift_a", "_fx_guard_drift", "a")
    async with admin_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS _fx_guard_drift"))
        await conn.execute(text("CREATE TABLE _fx_guard_drift(id int)"))
        await conn.execute(text(ddl))
    assert not await _index_exists(admin_engine, "ix__fx_guard_drift_a")


async def test_guard_skips_quietly_when_the_table_is_missing(admin_engine) -> None:
    mig = _migration()
    ddl = mig._guarded_index_ddl("ix__fx_guard_absent_a", "_fx_guard_absent", "a")
    async with admin_engine.begin() as conn:
        await conn.execute(text(ddl))
    assert not await _index_exists(admin_engine, "ix__fx_guard_absent_a")


async def test_one_drifted_column_skips_every_index_built_on_it(admin_engine) -> None:
    mig = _migration()
    ddl_present = mig._guarded_index_ddl("ix__fx_guard_multi_b", "_fx_guard_multi", "b")
    ddl_drift = mig._guarded_index_ddl("ix__fx_guard_multi_a", "_fx_guard_multi", "a")
    async with admin_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS _fx_guard_multi"))
        await conn.execute(text("CREATE TABLE _fx_guard_multi(id int, b int)"))
        # The drifted column feeds TWO indexes: both must skip, and the
        # healthy sibling on the same table must still land.
        await conn.execute(text(ddl_drift))
        await conn.execute(text(ddl_present))
    assert not await _index_exists(admin_engine, "ix__fx_guard_multi_a")
    assert await _index_exists(admin_engine, "ix__fx_guard_multi_b")


async def test_every_feasible_entry_exists_after_the_upgrade(admin_engine) -> None:
    """Post-upgrade invariant on the real migrated database: the guard may
    skip drifted schema, but on a database the chain itself built, EVERY
    table and column exists — so every index must exist too. A silent skip
    of healthy schema is the failure mode this pins shut."""
    mig = _migration()
    missing: list[str] = []
    async with admin_engine.connect() as conn:
        for idx_name, table, cols in mig._INDEXES:
            if not await _table_exists(admin_engine, table):
                continue
            for col in (c.strip() for c in cols.split(",")):
                column = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_schema = 'public' AND table_name = :t "
                            "AND column_name = :c"
                        ),
                        {"t": table, "c": col},
                    )
                ).scalar()
                if column is None:
                    break
            else:
                if not await _index_exists(admin_engine, idx_name):
                    missing.append(idx_name)
    assert not missing, f"tables and columns exist but the guard skipped: {missing}"
