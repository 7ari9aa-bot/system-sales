"""A batch that dies halfway leaves nothing half-written, and the retry finishes the job.

Every other import test runs inside the fixture's rolled-back transaction, which cannot show a
crash: nothing was ever committed. This one uses real committed transactions (the way the job
runner does) on a throwaway tenant that it removes afterwards.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.core.model_registry  # noqa: F401  (loads every table so foreign keys resolve)
from app.core.db import bind_tenant
from app.platform.imports.apply import apply_batch
from app.platform.imports.fields import SHEET_PRODUCTS
from app.platform.imports.models import ImportRow, ImportSession
from app.platform.imports.verdicts import encode_values, values_of
from app.workers.import_runner import PORTS

_NAME = "ImportCrashTest"
_ROWS = 7


class _Crash(Exception):
    """Stands in for a worker killed in the middle of a batch."""


async def _purge(admin_url: str, tenant_id: uuid.UUID) -> None:
    engine = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.begin() as conn:
            name = (
                await conn.execute(
                    sa.text("SELECT name FROM tenants WHERE id=:t"), {"t": tenant_id}
                )
            ).scalar()
            if name != _NAME:
                raise AssertionError(f"refusing to purge tenant {tenant_id}: name is {name!r}")
            await conn.execute(sa.text("SET LOCAL session_replication_role = replica"))
            for table in (
                "import_rows",
                "import_sessions",
                "product_variant_option_values",
                "product_variants",
                "product_options",
                "products",
            ):
                await conn.execute(
                    sa.text(f"DELETE FROM {table} WHERE tenant_id=:t"),  # noqa: S608
                    {"t": tenant_id},
                )
            await conn.execute(sa.text("DELETE FROM tenants WHERE id=:t"), {"t": tenant_id})
    finally:
        await engine.dispose()


@pytest.fixture
async def sessions(db_url):
    """Real committed sessions on an engine owned by THIS test.

    The app's own engine is process-wide and tied to the loop that created it, while every test
    gets a new loop (see ``app_sessions_on_test_connection`` in conftest), so reusing it across
    tests fails. Production has one loop; this is only a harness limit.
    """
    engine = create_async_engine(
        db_url, pool_pre_ping=True, connect_args={"statement_cache_size": 0}
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def committed_import(admin_url, sessions):
    """A tenant and a 7-row import that really exist in the database."""
    tenant_id = uuid.uuid4()
    engine = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, :n)"),
            {"i": tenant_id, "s": f"crash-{uuid.uuid4().hex[:8]}", "n": _NAME},
        )
    await engine.dispose()
    try:
        async with sessions() as db, db.begin():
            await bind_tenant(db, tenant_id)
            imp = ImportSession(
                tenant_id=tenant_id, kind="products", file_name="f.xlsx", status="running"
            )
            db.add(imp)
            await db.flush()
            db.add_all(
                ImportRow(
                    tenant_id=tenant_id,
                    session_id=imp.id,
                    sheet=SHEET_PRODUCTS,
                    row_number=i + 2,
                    raw={},
                    status="valid",
                    parsed={
                        "action": "create",
                        "values": encode_values({"product_ref": f"p{i}", "title": f"P{i}"}),
                    },
                )
                for i in range(_ROWS)
            )
            session_id = imp.id
        yield tenant_id, session_id
    finally:
        await _purge(admin_url, tenant_id)


async def _counts(sessions, tenant_id, session_id) -> tuple[int, int, int]:
    async with sessions() as db, db.begin():
        await bind_tenant(db, tenant_id)
        products = (await db.execute(sa.text("select count(*) from products"))).scalar_one()
        applied = (
            await db.execute(
                sa.text(
                    "select count(*) from import_rows where session_id=:s and status='applied'"
                ),
                {"s": session_id},
            )
        ).scalar_one()
        valid = (
            await db.execute(
                sa.text("select count(*) from import_rows where session_id=:s and status='valid'"),
                {"s": session_id},
            )
        ).scalar_one()
    return products, applied, valid


async def test_a_crash_midway_leaves_nothing_and_the_retry_applies_each_row_once(
    committed_import, sessions
):
    tenant_id, session_id = committed_import

    async def dies_on_the_fourth(session, tid, ref, values, action):
        result = await PORTS.upsert_product(session, tid, ref, values, action)
        if ref == "p3":
            raise _Crash  # the process is gone: nothing after this line runs, nothing is committed
        return result

    crashing = replace(PORTS, upsert_product=dies_on_the_fourth)
    with pytest.raises(_Crash):
        async with sessions() as db, db.begin():
            await bind_tenant(db, tenant_id)
            await apply_batch(db, tenant_id, session_id, crashing, values_of=values_of)

    # three rows were written before the crash: all of it rolled back, no half-batch survives
    assert await _counts(sessions, tenant_id, session_id) == (0, 0, _ROWS)

    # the runner claims the job again: same rows are still `valid`, so they are simply taken again
    async with sessions() as db, db.begin():
        await bind_tenant(db, tenant_id)
        retry = await apply_batch(db, tenant_id, session_id, PORTS, values_of=values_of)
    assert (retry.applied, retry.failed, retry.remaining) == (_ROWS, 0, 0)
    assert await _counts(sessions, tenant_id, session_id) == (_ROWS, _ROWS, 0)

    # and a second retry (the job finished but its completion was lost) writes nothing twice
    async with sessions() as db, db.begin():
        await bind_tenant(db, tenant_id)
        again = await apply_batch(db, tenant_id, session_id, PORTS, values_of=values_of)
    assert again.taken == 0
    assert await _counts(sessions, tenant_id, session_id) == (_ROWS, _ROWS, 0)


async def test_two_workers_on_the_same_session_never_take_the_same_row(committed_import, sessions):
    tenant_id, session_id = committed_import

    async with sessions() as first, first.begin():
        await bind_tenant(first, tenant_id)
        a = await apply_batch(first, tenant_id, session_id, PORTS, values_of=values_of, limit=4)
        # the first worker still holds its row locks (it has not committed yet)
        async with sessions() as second, second.begin():
            await bind_tenant(second, tenant_id)
            # without SKIP LOCKED the second worker waits for the first forever, which would hang
            # the suite; a timeout turns that into a plain failure
            b = await asyncio.wait_for(
                apply_batch(second, tenant_id, session_id, PORTS, values_of=values_of), timeout=10
            )

    assert a.taken == 4
    assert b.taken == _ROWS - 4  # skipped the four locked rows, took only the other three
    assert await _counts(sessions, tenant_id, session_id) == (_ROWS, _ROWS, 0)


async def test_the_cleanup_refuses_to_delete_a_tenant_it_did_not_create(admin_url):
    other = uuid.uuid4()
    engine = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, 'Somebody Else')"),
                {"i": other, "s": f"other-{uuid.uuid4().hex[:8]}"},
            )
        with pytest.raises(AssertionError, match="refusing to purge"):
            await _purge(admin_url, other)
        async with engine.begin() as conn:
            still_there = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM tenants WHERE id=:i"), {"i": other}
                )
            ).scalar_one()
            await conn.execute(sa.text("DELETE FROM tenants WHERE id=:i"), {"i": other})
        assert still_there == 1
    finally:
        await engine.dispose()
