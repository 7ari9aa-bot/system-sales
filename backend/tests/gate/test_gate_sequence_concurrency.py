"""One counter, many cashiers: nobody gets the same number and nobody skips one.

``app.core.sequences.next_sequence`` numbers barcodes, receipts, expenses and purchase orders. Two
people labelling garments at the same moment must receive different numbers, and the numbers
handed out must be a run with no hole in it (a hole in a receipt series is an audit finding).

These tests open ``RACERS`` INDEPENDENT connections that commit real rows and release the racers at
the same instant behind a barrier: the shared ``db`` fixture is one connection in a rolled-back
transaction and cannot exercise row locking at all. The last test guards the harness itself.

DB-backed as the ``sales_app`` role; skips via ``db_url`` when no application database is set.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.sequences import next_sequence
from app.platform.identity.models import Tenant

pytestmark = [pytest.mark.gate]

RACERS = 8
PER_RACER = 5


@pytest.fixture
async def committed_engine(db_url: str):
    engine = create_async_engine(
        db_url,
        pool_size=RACERS + 2,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def _tenant(engine: AsyncEngine) -> uuid.UUID:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        tenant = Tenant(slug=f"seq-{uuid.uuid4().hex[:10]}", name="Sequence Gate")
        session.add(tenant)
        await session.flush()
        return tenant.id


async def _cleanup(engine: AsyncEngine, tenant_id: uuid.UUID) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            await bind_tenant(session, tenant_id)
            await session.execute(
                text("DELETE FROM document_counters WHERE tenant_id = :t"), {"t": tenant_id}
            )
        async with factory() as session, session.begin():
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    except Exception:  # noqa: BLE001 - cleanup must never mask the real assertion
        pass


async def _race(engine: AsyncEngine, tenant_id: uuid.UUID, *, kind: str, year: int) -> list[int]:
    """RACERS connections, released together, each taking PER_RACER numbers in own transactions."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    barrier = asyncio.Barrier(RACERS)

    async def racer() -> list[int]:
        got: list[int] = []
        await barrier.wait()
        for _ in range(PER_RACER):
            async with factory() as session, session.begin():
                await bind_tenant(session, tenant_id)
                got.append(await next_sequence(session, tenant_id, kind, year=year))
        return got

    results = await asyncio.gather(*(racer() for _ in range(RACERS)))
    return [n for r in results for n in r]


async def test_concurrent_takers_never_share_a_number_and_leave_no_hole(committed_engine) -> None:
    tenant_id = await _tenant(committed_engine)
    try:
        numbers = await _race(committed_engine, tenant_id, kind="BC", year=0)
    finally:
        await _cleanup(committed_engine, tenant_id)
    total = RACERS * PER_RACER
    assert len(numbers) == total
    assert len(set(numbers)) == total, "two takers were handed the same number"
    assert sorted(numbers) == list(range(1, total + 1)), "the series has a hole or a restart"


async def test_a_rolled_back_taker_gives_its_number_back(committed_engine) -> None:
    tenant_id = await _tenant(committed_engine)
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            await bind_tenant(session, tenant_id)
            assert await next_sequence(session, tenant_id, "BC", year=0) == 1
        session = factory()
        trans = await session.begin()
        await bind_tenant(session, tenant_id)
        assert await next_sequence(session, tenant_id, "BC", year=0) == 2
        await trans.rollback()  # e.g. the garment's SKU clashed and the whole batch was refused
        await session.close()
        async with factory() as session, session.begin():
            await bind_tenant(session, tenant_id)
            assert await next_sequence(session, tenant_id, "BC", year=0) == 2, "a number was lost"
    finally:
        await _cleanup(committed_engine, tenant_id)


async def test_kinds_years_and_shops_count_independently(committed_engine) -> None:
    a, b = await _tenant(committed_engine), await _tenant(committed_engine)
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            await bind_tenant(session, a)
            assert await next_sequence(session, a, "BC", year=0) == 1
            assert await next_sequence(session, a, "BC", year=0) == 2
            assert await next_sequence(session, a, "EXP", year=2026) == 1  # another kind
            assert await next_sequence(session, a, "EXP", year=2027) == 1  # January restarts it
            assert await next_sequence(session, a, "BC", year=0) == 3  # the barcode run goes on
        async with factory() as session, session.begin():
            await bind_tenant(session, b)
            assert await next_sequence(session, b, "BC", year=0) == 1  # another shop starts at 1
    finally:
        await _cleanup(committed_engine, a)
        await _cleanup(committed_engine, b)


async def test_the_harness_really_races_on_separate_connections(committed_engine) -> None:
    """On one shared connection the race is vacuous; prove these takers are on distinct ones."""
    tenant_id = await _tenant(committed_engine)
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    barrier = asyncio.Barrier(4)

    async def backend_pid() -> int:
        async with factory() as session, session.begin():
            await barrier.wait()  # all four hold a connection open at once
            return (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()

    try:
        pids = await asyncio.gather(*(backend_pid() for _ in range(4)))
    finally:
        await _cleanup(committed_engine, tenant_id)
    assert len(set(pids)) == 4
