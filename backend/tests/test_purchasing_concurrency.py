"""Real concurrency for purchasing: separate committed connections racing for the same rows.

The per-test `db` fixture is one rolled-back connection, so it cannot show a race. This module
commits a
throw-away tenant, races real connections against it, then deletes everything it created.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.core.model_registry  # noqa: F401  (every table must be known: a payment points at pos_sessions)
from app.core.db import bind_tenant
from app.core.security import hash_password
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError
from app.modules.identity.models import Role, Tenant, TenantUser, User
from app.modules.inventory.service import InventoryService
from app.modules.purchasing.service import (
    CostService,
    PurchaseService,
    SupplierPaymentService,
    SupplierService,
)

RACERS = 12
D = Decimal

# The append-only tables (and the stock ledger) refuse DELETE for the app role BY DESIGN, so the app
# connection can
# neither be used to clean them nor should it be. A throw-away test tenant is removed through the
# OWNER connection
# instead, behind a guard that makes it unable to touch anything but the tenant this test created.
_TENANT_TABLES = (
    "variant_cost_history",
    "variant_costs",
    "supplier_return_lines",
    "supplier_returns",
    "supplier_payments",
    "purchase_order_lines",
    "purchase_orders",
    "suppliers",
    "document_counters",
    "inventory_movements",
    "inventory_balances",
    "product_variants",
    "products",
    "warehouses",
)
_TENANT_NAME = "PurchasingRace"


@pytest.fixture
def admin_url() -> str:
    from app.core.config import get_settings

    url = get_settings().database_url_admin
    if not url:
        pytest.skip(
            "no owner database URL (DATABASE_URL_ADMIN): cannot clean up a committed test tenant "
            "safely"
        )
    return url


async def _purge_test_tenant(admin_url: str, tenant_id: uuid.UUID) -> None:
    engine = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.begin() as conn:
            name = (
                await conn.execute(
                    sa.text("SELECT name FROM tenants WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar()
            # The guard: this code path can only ever delete the throw-away tenant this module
            # created.
            if name != _TENANT_NAME:
                raise AssertionError(
                    f"refusing to purge tenant {tenant_id}: its name is {name!r}, not "
                    f"{_TENANT_NAME!r}"
                )
            await conn.execute(
                sa.text("SET LOCAL session_replication_role = replica")
            )  # skip the append-only triggers
            for table in _TENANT_TABLES:
                await conn.execute(
                    sa.text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            await conn.execute(
                sa.text("DELETE FROM tenant_users WHERE tenant_id = :t"), {"t": tenant_id}
            )
            await conn.execute(
                sa.text("DELETE FROM tenants WHERE id = :t AND name = :n"),
                {"t": tenant_id, "n": _TENANT_NAME},
            )
            gone = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM tenants WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar_one()
            assert gone == 0, "cleanup failed: the throw-away tenant is still there"
    finally:
        await engine.dispose()


@pytest.fixture
async def committed_tenant(db_url, admin_url):
    engine = create_async_engine(
        db_url, pool_size=RACERS + 4, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    user_email = f"pc-{uuid.uuid4().hex[:8]}@test.local"
    async with factory() as s:
        role = (await s.execute(sa.select(Role).where(Role.code == "owner"))).scalar_one()
        user = User(email=user_email, password_hash=hash_password("x-secret-pw-1"), full_name="PC")
        s.add_all(
            [Tenant(id=tenant_id, slug=f"pc-{uuid.uuid4().hex[:8]}", name=_TENANT_NAME), user]
        )
        await s.flush()
        await s.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.id)})
        s.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role_id=role.id))
        await s.commit()
    try:
        yield factory, tenant_id
    finally:
        await engine.dispose()
        await _purge_test_tenant(admin_url, tenant_id)
        cleanup = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
        try:
            async with cleanup.begin() as conn:
                await conn.execute(sa.text("DELETE FROM users WHERE email = :e"), {"e": user_email})
        finally:
            await cleanup.dispose()


async def _in_tx(factory, tenant_id, fn):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        try:
            result = await fn(s)
            await s.commit()
            return result
        except Exception as exc:  # the caller inspects it
            await s.rollback()
            return exc


async def _setup_variant(factory, tenant_id):
    async def go(s):
        product = await CatalogService.create_product(
            s, tenant_id, title="سباق", slug=f"r-{uuid.uuid4().hex[:8]}"
        )
        variant = await CatalogService.add_variant(s, tenant_id, product.id, price="100.00")
        supplier = await SupplierService.create(s, tenant_id, name=f"مورد {uuid.uuid4().hex[:6]}")
        await InventoryService.get_default_warehouse(s, tenant_id)
        return variant.id, supplier.id

    return await _in_tx(factory, tenant_id, go)


async def test_parallel_receipts_of_one_variant_average_as_if_they_happened_one_by_one(
    committed_tenant,
) -> None:
    """RACERS deliveries of one variant at different prices, all at once.

    The final average must equal the plain weighted mean of ALL of them and the shelf must hold
    every unit: neither may be lost."""
    factory, tenant_id = committed_tenant
    variant_id, supplier_id = await _setup_variant(factory, tenant_id)
    prices = [D(str(100 + 10 * i)) for i in range(RACERS)]  # 100, 110, ... 210
    qty = 5

    def receive(price):
        async def go(s):
            return await PurchaseService.create(
                s,
                tenant_id,
                supplier_id=supplier_id,
                receive_now=True,
                lines=[
                    {"variant_id": str(variant_id), "quantity": qty, "unit_cost": f"{price:.2f}"}
                ],
            )

        return go

    results = await asyncio.gather(*[_in_tx(factory, tenant_id, receive(p)) for p in prices])
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, errors[:2]

    async def read(s):
        return (
            await InventoryService.total_on_hand(s, tenant_id, variant_id),
            await CostService.get(s, tenant_id, variant_id),
        )

    on_hand, avg = await _in_tx(factory, tenant_id, read)
    assert on_hand == RACERS * qty  # no receipt lost its stock
    expected = (sum(prices) / RACERS).quantize(
        D("0.0001")
    )  # equal quantities: the mean of the prices
    # The average is rounded to 4 places after EVERY receipt and the receipts land in a different
    # order each run, so the last digit can drift by a couple of units (155.0001 vs 155.0000).
    # A receipt averaged against a stale quantity misses by whole money units, so a 0.001
    # tolerance still catches it.
    assert abs(avg - expected) <= D("0.001"), (
        f"average {avg} != {expected}: a receipt averaged against a stale quantity"
    )

    async def history(s):
        rows = (
            await s.execute(
                sa.text(
                    "select on_hand_before from variant_cost_history where variant_id=:v order by"
                    " on_hand_before"
                ),
                {"v": variant_id},
            )
        ).all()
        return [r[0] for r in rows]

    # each receipt saw a DIFFERENT shelf, 0, 5, 10, ... : they queued instead of all reading the
    # same stale number
    assert await _in_tx(factory, tenant_id, history) == [qty * i for i in range(RACERS)]


async def test_parallel_payments_never_overpay_an_order(committed_tenant) -> None:
    """The order owes 1000; RACERS payers each try 300.

    Exactly three can succeed (900), the rest are refused,
    and the total paid is never above what was owed."""
    factory, tenant_id = committed_tenant
    variant_id, supplier_id = await _setup_variant(factory, tenant_id)

    async def mk(s):
        order = await PurchaseService.create(
            s,
            tenant_id,
            supplier_id=supplier_id,
            receive_now=True,
            lines=[{"variant_id": str(variant_id), "quantity": 10, "unit_cost": "100.00"}],
        )
        return order.id

    order_id = await _in_tx(factory, tenant_id, mk)

    def pay(s):
        return SupplierPaymentService.create(
            s,
            tenant_id,
            supplier_id=supplier_id,
            purchase_order_id=order_id,
            amount="300",
            method="bank_transfer",
        )

    results = await asyncio.gather(*[_in_tx(factory, tenant_id, pay) for _ in range(RACERS)])
    winners = [r for r in results if not isinstance(r, Exception)]
    refused = [r for r in results if isinstance(r, ConflictError)]
    other = [r for r in results if isinstance(r, Exception) and not isinstance(r, ConflictError)]
    assert not other, other[:2]
    assert len(winners) == 3 and len(refused) == RACERS - 3, f"{len(winners)} payments accepted"

    async def paid(s):
        return await PurchaseService.paid_for(s, tenant_id, order_id)

    assert await _in_tx(factory, tenant_id, paid) == D("900.00")


async def test_parallel_double_receive_of_one_order_adds_stock_once(committed_tenant) -> None:
    factory, tenant_id = committed_tenant
    variant_id, supplier_id = await _setup_variant(factory, tenant_id)

    async def mk(s):
        order = await PurchaseService.create(
            s,
            tenant_id,
            supplier_id=supplier_id,
            receive_now=False,
            lines=[{"variant_id": str(variant_id), "quantity": 7, "unit_cost": "50.00"}],
        )
        return order.id

    order_id = await _in_tx(factory, tenant_id, mk)
    results = await asyncio.gather(
        *[
            _in_tx(factory, tenant_id, lambda s: PurchaseService.receive(s, tenant_id, order_id))
            for _ in range(RACERS)
        ]
    )
    assert len([r for r in results if not isinstance(r, Exception)]) == 1
    assert len([r for r in results if isinstance(r, ConflictError)]) == RACERS - 1

    async def read(s):
        return await InventoryService.total_on_hand(
            s, tenant_id, variant_id
        ), await CostService.get(s, tenant_id, variant_id)

    assert await _in_tx(factory, tenant_id, read) == (
        7,
        D("50.0000"),
    )  # one receipt: 7 units, never 14


async def test_parallel_receive_of_existing_orders_averages_correctly(committed_tenant) -> None:
    """The case the cost-row lock exists for.

    `create(receive_now=True)` is always serialised by the document numbering lock, which would
    hide a missing cost lock. Receiving drafts that ALREADY exist skips numbering, so
    only the cost-row lock stands between two receipts and the same stale quantity."""
    factory, tenant_id = committed_tenant
    variant_id, supplier_id = await _setup_variant(factory, tenant_id)
    prices = [D(str(100 + 10 * i)) for i in range(RACERS)]
    qty = 5

    async def make_draft(s, price):
        order = await PurchaseService.create(
            s,
            tenant_id,
            supplier_id=supplier_id,
            receive_now=False,
            lines=[{"variant_id": str(variant_id), "quantity": qty, "unit_cost": f"{price:.2f}"}],
        )
        return order.id

    ids = [await _in_tx(factory, tenant_id, lambda s, p=p: make_draft(s, p)) for p in prices]
    results = await asyncio.gather(
        *[
            _in_tx(factory, tenant_id, lambda s, i=i: PurchaseService.receive(s, tenant_id, i))
            for i in ids
        ]
    )
    assert not [r for r in results if isinstance(r, Exception)], results

    async def read(s):
        history = (
            await s.execute(
                sa.text(
                    "select on_hand_before from variant_cost_history where variant_id=:v order by"
                    " on_hand_before"
                ),
                {"v": variant_id},
            )
        ).all()
        return (
            await InventoryService.total_on_hand(s, tenant_id, variant_id),
            await CostService.get(s, tenant_id, variant_id),
            [r[0] for r in history],
        )

    on_hand, avg, seen = await _in_tx(factory, tenant_id, read)
    assert on_hand == RACERS * qty
    assert seen == [qty * i for i in range(RACERS)], f"receipts read the same stale stock: {seen}"
    # The average is rounded to 4 places after EVERY receipt, and the receipts land in a
    # different order each run, so the final figure can sit a rounding step or two away from
    # the exact mean (155.0001 / 154.9999 were both seen). A receipt that read a stale quantity
    # misses by whole units, so a 0.001 tolerance still catches it. `seen` above is the exact
    # proof that the lock serialised the receipts.
    expected = sum(prices) / RACERS
    assert abs(avg - expected) <= D("0.001"), f"average {avg}: a receipt used a stale quantity"
