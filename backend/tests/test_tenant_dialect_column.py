"""fe2026111209: ``tenants.dialect`` is a closed list the database itself enforces.

The column is NULL for "the owner never chose", which every existing shop is, so there is no
backfill: guessing a dialect for a live shop would be inventing a choice. The CHECK mirrors the
code's list, and a test keeps the two from drifting. Runs as the migration role
(``DATABASE_URL_ADMIN``), everything rolled back, skipped when no admin URL is configured.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.modules.identity.dialects import CHOICES

PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "fe2026111209_tenant_dialect.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("tenant_dialect_migration", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_sits_on_the_current_head() -> None:
    module = _load()
    assert module.revision == "fe2026111209"
    assert module.down_revision == "fe2026111208"


def test_the_check_lists_exactly_the_dialects_the_code_knows() -> None:
    sql = _load()._DIALECT_CHECK
    listed = set(re.findall(r"'([a-z]+)'", sql))
    assert listed == set(CHOICES), "the database list and identity.dialects.CHOICES drifted apart"


def test_the_model_declares_the_column_as_nullable_text() -> None:
    from app.modules.identity.models import Tenant

    column = Tenant.__table__.c.dialect
    assert column.nullable is True
    assert column.server_default is None  # NULL means "never chose": no default, no backfill


@pytest.fixture
async def admin_conn():
    url = get_settings().database_url_admin
    if not url:
        pytest.skip("no DATABASE_URL_ADMIN: the migration role is needed for this test")
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            yield conn
            await trans.rollback()
    finally:
        await engine.dispose()


async def _tenant(conn, dialect: str | None) -> uuid.UUID:
    tid = uuid.uuid4()
    await conn.execute(
        sa.text("INSERT INTO tenants (id, slug, name, dialect) VALUES (:i, :s, 'T', :d)"),
        {"i": tid, "s": f"t-{tid.hex[:12]}", "d": dialect},
    )
    return tid


async def test_null_and_every_listed_dialect_are_accepted(admin_conn) -> None:
    await _tenant(admin_conn, None)
    for key in CHOICES:
        async with admin_conn.begin_nested():
            await _tenant(admin_conn, key)


@pytest.mark.parametrize("bad", ["", "Egyptian", "egyptian ", "klingon", "x" * 64, "<script>"])
async def test_the_database_refuses_anything_off_the_list(admin_conn, bad: str) -> None:
    # a value off the list trips the CHECK (IntegrityError); one too long for the column is refused
    # by the column itself (DBAPIError). Either way the database never stores it.
    with pytest.raises((IntegrityError, DBAPIError)):
        async with admin_conn.begin_nested():
            await _tenant(admin_conn, bad)


async def test_a_new_shop_starts_with_no_choice(admin_conn) -> None:
    tid = uuid.uuid4()
    await admin_conn.execute(
        sa.text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, 'T')"),
        {"i": tid, "s": f"t-{tid.hex[:12]}"},
    )
    got = (
        await admin_conn.execute(sa.text("SELECT dialect FROM tenants WHERE id = :i"), {"i": tid})
    ).scalar_one()
    assert got is None
