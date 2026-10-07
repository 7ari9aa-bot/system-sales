"""§176 gate scenario 16 — inventory oversell under REAL concurrency (§140).

The shared `db` fixture runs every test on ONE connection inside a transaction
that is rolled back, so it cannot exercise row locking at all: two "concurrent"
reservations there are just two sequential statements on the same connection.

These tests therefore open N INDEPENDENT connections, commit real rows, and
release all N reservations at the same instant. What they prove is a property of
Postgres + `InventoryService._locked_balance` together:

* stock for one unit is handed to exactly ONE buyer, never two;
* `reserved` ends at exactly the stock that existed — it never overshoots;
* the "balance row does not exist yet" path converges through ON CONFLICT
  instead of surfacing a unique-violation to the caller.

If `.with_for_update()` is removed from `_locked_balance`, the first test fails
(several buyers succeed and `reserved > on_hand`). That mutation was run to
confirm the test can actually fail — see the commit message.

DB-backed: needs PostgreSQL as the `sales_app` role. It skips (loudly, via the
`db_url` fixture) when no application database is configured.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import bind_tenant
from app.modules.catalog.service import CatalogService
from app.modules.identity.models import Tenant
from app.modules.inventory.models import Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.errors import InsufficientStockError

pytestmark = [pytest.mark.gate]

BUYERS = 6  # concurrent connections; comfortably above one pool's default of 5


@pytest.fixture
async def committed_engine(db_url: str):
    engine = create_async_engine(
        db_url,
        pool_size=BUYERS + 2,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed(engine: AsyncEngine, *, on_hand: int) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Commit a tenant, a warehouse and a variant (stocked with `on_hand`).

    Returns plain UUIDs — never ORM objects — so nothing lazy-loads later.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        tenant = Tenant(slug=f"oversell-{uuid.uuid4().hex[:10]}", name="Oversell Gate")
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id
        await bind_tenant(session, tenant_id)

        warehouse = Warehouse(
            tenant_id=tenant_id, name="WH", code=f"W-{uuid.uuid4().hex[:6].upper()}"
        )
        session.add(warehouse)
        await session.flush()
        warehouse_id = warehouse.id

        product = await CatalogService.create_product(
            session, tenant_id, title="Last Unit", slug=f"p-{uuid.uuid4().hex[:10]}"
        )
        variant = await CatalogService.add_variant(session, tenant_id, product.id, price="10.00")
        variant_id = variant.id
        if on_hand:
            await InventoryService.move(
                session,
                tenant_id,
                variant_id,
                warehouse_id,
                direction="in",
                quantity=on_hand,
                reason="purchase",
            )
    return tenant_id, warehouse_id, variant_id


async def _cleanup(engine: AsyncEngine, tenant_id: uuid.UUID) -> None:
    """Best-effort removal so a shared dev database is not littered."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            await bind_tenant(session, tenant_id)
            for table in (
                "inventory_movements",
                "inventory_balances",
                "product_variants",
                "products",
                "warehouses",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
        async with factory() as session, session.begin():
            await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    except Exception:  # noqa: BLE001 — cleanup must never mask the real assertion
        pass


async def _race_reservations(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    variant_id: uuid.UUID,
) -> list[str]:
    """Release BUYERS reservations of 1 unit at the same instant; return outcomes."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # Every buyer opens its transaction FIRST, then all wait here — so the
    # reserve() calls really do collide instead of running back to back.
    barrier = asyncio.Barrier(BUYERS)

    async def buyer() -> str:
        async with factory() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                await barrier.wait()
                try:
                    await InventoryService.reserve(session, tenant_id, variant_id, warehouse_id, 1)
                except InsufficientStockError:
                    return "insufficient"
                return "reserved"

    return list(await asyncio.gather(*(buyer() for _ in range(BUYERS))))


async def _balance(engine: AsyncEngine, tenant_id: uuid.UUID, variant_id: uuid.UUID):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await bind_tenant(session, tenant_id)
        rows = (
            await session.execute(
                text(
                    "SELECT on_hand, reserved FROM inventory_balances "
                    "WHERE tenant_id = :t AND variant_id = :v"
                ),
                {"t": tenant_id, "v": variant_id},
            )
        ).all()
    return [(r.on_hand, r.reserved) for r in rows]


async def test_gate_last_unit_is_sold_exactly_once(committed_engine):
    tenant_id, warehouse_id, variant_id = await _seed(committed_engine, on_hand=1)
    try:
        outcomes = await _race_reservations(committed_engine, tenant_id, warehouse_id, variant_id)
        tally = Counter(outcomes)

        assert tally["reserved"] == 1, f"oversold: {dict(tally)}"
        assert tally["insufficient"] == BUYERS - 1, f"unexpected outcomes: {dict(tally)}"
        # The durable balance agrees with the outcomes: one unit held, none negative.
        assert await _balance(committed_engine, tenant_id, variant_id) == [(1, 1)]
    finally:
        await _cleanup(committed_engine, tenant_id)


async def test_gate_stock_is_split_without_overshoot(committed_engine):
    """3 units, 6 buyers: exactly 3 win, and reserved lands on 3 — not 4, 5 or 6."""
    tenant_id, warehouse_id, variant_id = await _seed(committed_engine, on_hand=3)
    try:
        outcomes = await _race_reservations(committed_engine, tenant_id, warehouse_id, variant_id)
        tally = Counter(outcomes)

        assert tally["reserved"] == 3, f"oversold or undersold: {dict(tally)}"
        assert tally["insufficient"] == BUYERS - 3
        assert await _balance(committed_engine, tenant_id, variant_id) == [(3, 3)]
    finally:
        await _cleanup(committed_engine, tenant_id)


async def test_gate_first_touch_balance_row_converges(committed_engine):
    """No balance row exists yet and BUYERS callers race to create it.

    Every caller must get a clean `InsufficientStockError` (there is no stock),
    NOT a unique-violation from two concurrent INSERTs — and exactly one zeroed
    row must remain afterwards.
    """
    tenant_id, warehouse_id, variant_id = await _seed(committed_engine, on_hand=0)
    try:
        assert await _balance(committed_engine, tenant_id, variant_id) == []

        outcomes = await _race_reservations(committed_engine, tenant_id, warehouse_id, variant_id)

        assert Counter(outcomes) == {"insufficient": BUYERS}
        assert await _balance(committed_engine, tenant_id, variant_id) == [(0, 0)]
    finally:
        await _cleanup(committed_engine, tenant_id)


async def test_gate_uses_a_separate_connection_per_buyer(committed_engine):
    """Guard the guard: the race above is only meaningful with distinct backends.

    If someone "simplifies" the harness onto one shared connection the oversell
    tests would pass vacuously (statements just run in order). Assert that the
    buyers really are separate Postgres backends.
    """
    factory = async_sessionmaker(committed_engine, expire_on_commit=False)
    barrier = asyncio.Barrier(BUYERS)

    async def backend_pid() -> int:
        async with factory() as session:
            async with session.begin():
                # Hold the transaction open until every buyer has its own.
                pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                await barrier.wait()
                return pid

    pids = await asyncio.gather(*(backend_pid() for _ in range(BUYERS)))
    assert len(set(pids)) == BUYERS, f"buyers shared connections: {pids}"
