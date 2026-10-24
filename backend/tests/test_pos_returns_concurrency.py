"""Real concurrency on the return path: separate committed connections racing for one order.

The per-test `db` fixture is ONE rolled-back connection, so it cannot show a race. This module
commits a throw-away tenant, races real connections, then deletes everything it created (and proves
it).
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.security import hash_password
from app.modules.errors import ConflictError
from app.modules.identity.models import Role, Tenant, TenantUser, User
from app.modules.pos.service import PosService
from tests._pos_sell import sell as pos_sell

RACERS = 6

# The append-only tables (the stock ledger, cost history) refuse DELETE for the app role BY DESIGN,
# so a throw-away tenant is removed through the OWNER connection, behind a guard that makes it
# unable to touch anything but the tenant this module created. Children first.
_TENANT_TABLES = (
    "pos_return_lines",
    "pos_receipts",
    "pos_cash_movements",
    "pos_session_floats",
    "pos_session_reconciliations",
    "pos_session_handovers",
    "order_payments",
    "order_status_history",
    "inventory_reservations",
    "order_items",
    "orders",
    "inventory_movements",
    "inventory_balances",
    "variant_cost_history",
    "variant_costs",
    "product_prices",
    "product_identifiers",
    "product_variants",
    "products",
    "document_counters",
    "pos_sessions",
    "pos_registers",
    "warehouses",
)
_TENANT_NAME = "ReturnsRace"


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


async def _purge_test_tenant(admin_url: str, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    engine = create_async_engine(admin_url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.begin() as conn:
            name = (
                await conn.execute(
                    sa.text("SELECT name FROM tenants WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar()
            if name != _TENANT_NAME:
                raise AssertionError(
                    f"refusing to purge tenant {tenant_id}: its name is {name!r}, not "
                    f"{_TENANT_NAME!r}"
                )
            await conn.execute(sa.text("SET LOCAL session_replication_role = replica"))
            for table in _TENANT_TABLES:
                await conn.execute(
                    sa.text(f"DELETE FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                    {"t": tenant_id},
                )
            await conn.execute(
                sa.text("DELETE FROM tenant_users WHERE tenant_id = :t"), {"t": tenant_id}
            )
            await conn.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
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
        db_url, pool_size=RACERS + 3, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    async with factory() as s:
        role = (await s.execute(sa.select(Role).where(Role.code == "owner"))).scalar_one()
        user = User(
            email=f"r-{uuid.uuid4().hex[:8]}@test.local",
            password_hash=hash_password("x-secret-pw"),
            full_name="R",
        )
        tenant = Tenant(id=tenant_id, slug=f"r-{uuid.uuid4().hex[:8]}", name=_TENANT_NAME)
        s.add_all([tenant, user])
        await s.flush()
        await s.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.id)})
        s.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role_id=role.id))
        await s.commit()
        user_id = user.id
    try:
        yield factory, tenant_id
    finally:
        await engine.dispose()
        await _purge_test_tenant(admin_url, tenant_id, user_id)


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


async def _sell(factory, tenant_id, qty_sold: int):
    """One open shift and one sale of `qty_sold` units. Returns the ids the racers need."""

    async def setup(s):
        from app.modules.catalog.service import CatalogService
        from app.modules.inventory.service import InventoryService

        wh = await InventoryService.get_default_warehouse(s, tenant_id)
        reg = await PosService.create_register(
            s, tenant_id, name="ك", code=f"R-{uuid.uuid4().hex[:6]}", warehouse_id=wh.id
        )
        shift = await PosService.open_session(s, tenant_id, reg.id, opening_float="0.00")
        product = await CatalogService.create_product(
            s, tenant_id, title="سلعة", slug=f"p-{uuid.uuid4().hex[:10]}"
        )
        product = await CatalogService.update_product(s, tenant_id, product.id, status="active")
        variant = await CatalogService.add_variant(
            s, tenant_id, product.id, title="س", price="25.00"
        )
        await InventoryService.move(
            s, tenant_id, variant.id, wh.id, direction="in", quantity=50, reason="purchase"
        )
        sold = await pos_sell(
            s,
            tenant_id,
            shift.id,
            items=[{"variant_id": str(variant.id), "quantity": qty_sold}],
            tenders=[{"method": "cash", "amount": str(Decimal("25.00") * qty_sold)}],
        )
        return shift.id, variant.id, sold["order_id"]

    out = await _in_tx(factory, tenant_id, setup)
    assert not isinstance(out, Exception), out
    return out


async def _refunded_units(factory, tenant_id, order_id) -> int:
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        n = await s.execute(
            sa.text(
                "SELECT COALESCE(SUM(quantity), 0) FROM pos_return_lines "
                "WHERE tenant_id = :t AND order_id = :o"
            ),
            {"t": tenant_id, "o": order_id},
        )
        return int(n.scalar_one())


async def test_two_returns_cannot_both_take_the_last_unit(committed_tenant) -> None:
    factory, tenant_id = committed_tenant
    shift_id, variant_id, order_id = await _sell(factory, tenant_id, qty_sold=1)

    results = await asyncio.gather(
        *[
            _in_tx(
                factory,
                tenant_id,
                lambda s: PosService.return_sale(
                    s,
                    tenant_id,
                    shift_id,
                    order_id=order_id,
                    lines=[{"variant_id": str(variant_id), "quantity": 1}],
                ),
            )
            for _ in range(RACERS)
        ]
    )
    won = [r for r in results if not isinstance(r, Exception)]
    lost = [r for r in results if isinstance(r, ConflictError)]
    other = [r for r in results if isinstance(r, Exception) and not isinstance(r, ConflictError)]

    assert not other, other[:2]
    assert len(won) == 1, f"{len(won)} of {RACERS} cashiers refunded the same single unit"
    assert len(lost) == RACERS - 1
    # Refused for the RIGHT reason: the quantity cap (which the lock lets them see), not the payment
    # backstop that fires late, after the shelf and the drawer were already touched.
    assert all("already returned" in str(e) for e in lost), [str(e)[:80] for e in lost]
    # the books agree with the verdict: one unit refunded, one unit back on the shelf
    assert await _refunded_units(factory, tenant_id, order_id) == 1


async def test_parallel_partial_returns_never_exceed_what_was_sold(committed_tenant) -> None:
    factory, tenant_id = committed_tenant
    sold_qty = 3
    shift_id, variant_id, order_id = await _sell(factory, tenant_id, qty_sold=sold_qty)

    results = await asyncio.gather(
        *[
            _in_tx(
                factory,
                tenant_id,
                lambda s: PosService.return_sale(
                    s,
                    tenant_id,
                    shift_id,
                    order_id=order_id,
                    lines=[{"variant_id": str(variant_id), "quantity": 1}],
                ),
            )
            for _ in range(RACERS)
        ]
    )
    won = [r for r in results if not isinstance(r, Exception)]
    assert len(won) == sold_qty, f"sold {sold_qty}, but {len(won)} one-unit returns were accepted"
    assert await _refunded_units(factory, tenant_id, order_id) == sold_qty


async def _shelf(factory, tenant_id, variant_id) -> int:
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        n = await s.execute(
            sa.text(
                "SELECT COALESCE(SUM(on_hand), 0) FROM inventory_balances "
                "WHERE tenant_id = :t AND variant_id = :v"
            ),
            {"t": tenant_id, "v": variant_id},
        )
        return int(n.scalar_one())


async def test_a_losing_return_leaves_neither_money_nor_shelf_behind(committed_tenant) -> None:
    """A losing return is refused, and must leave NOTHING behind.

    No restocked unit, no return line, and never a drawer pay-out."""
    factory, tenant_id = committed_tenant
    shift_id, variant_id, order_id = await _sell(factory, tenant_id, qty_sold=3)
    shelf_after_sale = await _shelf(factory, tenant_id, variant_id)

    results = await asyncio.gather(
        *[
            _in_tx(
                factory,
                tenant_id,
                lambda s: PosService.return_sale(
                    s,
                    tenant_id,
                    shift_id,
                    order_id=order_id,
                    lines=[{"variant_id": str(variant_id), "quantity": 2}],
                    restock=True,
                ),
            )
            for _ in range(RACERS)
        ]
    )
    won = [r for r in results if not isinstance(r, Exception)]
    assert len(won) == 1, f"{len(won)} cashiers each took 2 of the 3 units sold"
    # one return of 2 units: the shelf gained exactly 2, the books hold exactly 2
    assert await _shelf(factory, tenant_id, variant_id) == shelf_after_sale + 2
    assert await _refunded_units(factory, tenant_id, order_id) == 2
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        paid_out = (
            await s.execute(
                sa.text(
                    "SELECT COALESCE(SUM(amount), 0) FROM pos_cash_movements "
                    "WHERE tenant_id = :t AND session_id = :s AND direction = 'out'"
                ),
                {"t": tenant_id, "s": shift_id},
            )
        ).scalar_one()
    assert Decimal(paid_out) == Decimal("0.00"), f"drawer paid out {paid_out}, expected nothing"


async def _second_variant(factory, tenant_id) -> uuid.UUID:
    async def make(s):
        from app.modules.catalog.service import CatalogService
        from app.modules.inventory.service import InventoryService

        wh = await InventoryService.get_default_warehouse(s, tenant_id)
        product = await CatalogService.create_product(
            s, tenant_id, title="بديل", slug=f"x-{uuid.uuid4().hex[:10]}"
        )
        product = await CatalogService.update_product(s, tenant_id, product.id, status="active")
        variant = await CatalogService.add_variant(
            s, tenant_id, product.id, title="ب", price="25.00"
        )
        await InventoryService.move(
            s, tenant_id, variant.id, wh.id, direction="in", quantity=50, reason="purchase"
        )
        return variant.id

    out = await _in_tx(factory, tenant_id, make)
    assert not isinstance(out, Exception), out
    return out


async def test_two_exchanges_cannot_both_take_the_last_unit(committed_tenant) -> None:
    factory, tenant_id = committed_tenant
    shift_id, variant_id, order_id = await _sell(factory, tenant_id, qty_sold=1)
    other = await _second_variant(factory, tenant_id)

    results = await asyncio.gather(
        *[
            _in_tx(
                factory,
                tenant_id,
                lambda s: PosService.exchange(
                    s,
                    tenant_id,
                    shift_id,
                    order_id=order_id,
                    return_lines=[{"variant_id": str(variant_id), "quantity": 1}],
                    new_lines=[{"variant_id": str(other), "quantity": 1}],
                ),
            )
            for _ in range(RACERS)
        ]
    )
    won = [r for r in results if not isinstance(r, Exception)]
    lost = [r for r in results if isinstance(r, ConflictError)]
    other_errs = [
        r for r in results if isinstance(r, Exception) and not isinstance(r, ConflictError)
    ]
    assert not other_errs, other_errs[:2]
    assert len(won) == 1, f"{len(won)} of {RACERS} exchanges took the same single unit"
    assert all("already returned" in str(e) for e in lost), [str(e)[:80] for e in lost]
    assert await _refunded_units(factory, tenant_id, order_id) == 1


async def test_a_return_and_an_exchange_racing_for_the_same_unit(committed_tenant) -> None:
    factory, tenant_id = committed_tenant
    shift_id, variant_id, order_id = await _sell(factory, tenant_id, qty_sold=1)
    other = await _second_variant(factory, tenant_id)

    def back(s):
        return PosService.return_sale(
            s,
            tenant_id,
            shift_id,
            order_id=order_id,
            lines=[{"variant_id": str(variant_id), "quantity": 1}],
        )

    def swap(s):
        return PosService.exchange(
            s,
            tenant_id,
            shift_id,
            order_id=order_id,
            return_lines=[{"variant_id": str(variant_id), "quantity": 1}],
            new_lines=[{"variant_id": str(other), "quantity": 1}],
        )

    results = await asyncio.gather(
        *[_in_tx(factory, tenant_id, back if i % 2 else swap) for i in range(RACERS)]
    )
    won = [r for r in results if not isinstance(r, Exception)]
    assert len(won) == 1, f"{len(won)} operations took the one unit that was sold"
    assert await _refunded_units(factory, tenant_id, order_id) == 1
