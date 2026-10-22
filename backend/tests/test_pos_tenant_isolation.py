"""Cross-tenant isolation on the POS: tenant B attacks tenant A's ids through the real services.

The per-test `db` fixture is ONE rolled-back connection, so it cannot show a race. This module
commits a throw-away tenant, races real connections, then deletes everything it created (and proves
it).
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.security import hash_password
from app.modules.identity.models import Role, Tenant, TenantUser, User
from app.modules.pos.service import PosService

RACERS = 2

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
_TENANT_NAME = "IsoRace"


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


async def _make_tenant(db_url, label):
    engine = create_async_engine(db_url, pool_size=4, connect_args={"statement_cache_size": 0})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    async with factory() as s:
        role = (await s.execute(sa.select(Role).where(Role.code == "owner"))).scalar_one()
        user = User(
            email=f"{label}-{uuid.uuid4().hex[:8]}@test.local",
            password_hash=hash_password("x-secret-pw"),
            full_name=label,
        )
        tenant = Tenant(id=tenant_id, slug=f"{label}-{uuid.uuid4().hex[:8]}", name=_TENANT_NAME)
        s.add_all([tenant, user])
        await s.flush()
        await s.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.id)})
        s.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role_id=role.id))
        await s.commit()
        user_id = user.id
    return engine, factory, tenant_id, user_id


@pytest.fixture
async def two_tenants(db_url, admin_url):
    ea, fa, ta, ua = await _make_tenant(db_url, "a")
    eb, fb, tb, ub = await _make_tenant(db_url, "b")
    try:
        yield (fa, ta), (fb, tb)
    finally:
        await ea.dispose()
        await eb.dispose()
        await _purge_test_tenant(admin_url, ta, ua)
        await _purge_test_tenant(admin_url, tb, ub)


async def _in_tx(factory, tenant_id, fn):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        try:
            result = await fn(s)
            await s.commit()
            return result
        except Exception as exc:
            await s.rollback()
            return exc


async def _a_shop(factory, tenant_id):
    """Tenant A: an open shift, one variant with 10 units, one finished sale of 1."""

    async def setup(s):
        from app.modules.catalog.service import CatalogService
        from app.modules.inventory.service import InventoryService

        wh = await InventoryService.get_default_warehouse(s, tenant_id)
        reg = await PosService.create_register(
            s, tenant_id, name="ك", code=f"R-{uuid.uuid4().hex[:6]}", warehouse_id=wh.id
        )
        shift = await PosService.open_session(s, tenant_id, reg.id, opening_float="0.00")
        product = await CatalogService.create_product(
            s, tenant_id, title="سلعة A", slug=f"p-{uuid.uuid4().hex[:10]}"
        )
        product = await CatalogService.update_product(s, tenant_id, product.id, status="active")
        variant = await CatalogService.add_variant(
            s, tenant_id, product.id, title="س", price="25.00"
        )
        await InventoryService.move(
            s, tenant_id, variant.id, wh.id, direction="in", quantity=10, reason="purchase"
        )
        sold = await PosService.sell(
            s,
            tenant_id,
            shift.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
            tenders=[{"method": "cash", "amount": "25.00"}],
        )
        return {
            "register": reg.id,
            "shift": shift.id,
            "variant": variant.id,
            "product": product.id,
            "order": sold["order_id"],
            "receipt": sold.get("receipt_id"),
            "warehouse": wh.id,
        }

    out = await _in_tx(factory, tenant_id, setup)
    assert not isinstance(out, Exception), out
    return out


async def _count(factory, tenant_id, sql, **params):
    async with factory() as s:
        await bind_tenant(s, tenant_id)
        return int((await s.execute(sa.text(sql), {"t": tenant_id, **params})).scalar_one())


def _refused(result) -> bool:
    return isinstance(result, Exception)


async def test_b_cannot_touch_a_through_the_pos_services(two_tenants) -> None:
    (fa, ta), (fb, tb) = two_tenants
    a = await _a_shop(fa, ta)
    on_hand_before = await _count(
        fa, ta, "SELECT COALESCE(SUM(on_hand),0) FROM inventory_balances WHERE tenant_id=:t"
    )

    attacks = {
        "read A's shift": lambda s: PosService.get_session(s, tb, a["shift"]),
        "sell on A's shift": lambda s: PosService.sell(
            s,
            tb,
            a["shift"],
            items=[{"variant_id": str(a["variant"]), "quantity": 1}],
            tenders=[{"method": "cash", "amount": "25.00"}],
        ),
        "return A's order": lambda s: PosService.return_sale(
            s,
            tb,
            a["shift"],
            order_id=a["order"],
            lines=[{"variant_id": str(a["variant"]), "quantity": 1}],
        ),
        "close A's shift": lambda s: PosService.close_session(s, tb, a["shift"]),
        "read A's receipt": lambda s: PosService.get_receipt(s, tb, a["receipt"] or uuid.uuid4()),
    }
    leaked = {}
    for name, fn in attacks.items():
        res = await _in_tx(fb, tb, fn)
        if not _refused(res):
            leaked[name] = str(res)[:80]
    assert not leaked, f"tenant B got through to tenant A: {leaked}"

    # A is untouched: still open, stock unchanged, still exactly one sale.
    assert (
        await _count(
            fa, ta, "SELECT count(*) FROM pos_sessions WHERE tenant_id=:t AND status='OPEN'"
        )
        == 1
    )
    assert (
        await _count(
            fa, ta, "SELECT COALESCE(SUM(on_hand),0) FROM inventory_balances WHERE tenant_id=:t"
        )
        == on_hand_before
    )
    assert await _count(fa, ta, "SELECT count(*) FROM orders WHERE tenant_id=:t") == 1


async def test_b_sees_none_of_a_in_lists_and_search(two_tenants) -> None:
    (fa, ta), (fb, tb) = two_tenants
    await _a_shop(fa, ta)
    # A's REAL receipt number: the search must find it for A and must not find it for B.
    async with fa() as s:
        await bind_tenant(s, ta)
        number = (
            await s.execute(
                sa.text("SELECT number FROM pos_receipts WHERE tenant_id = :t LIMIT 1"),
                {"t": ta},
            )
        ).scalar_one()
    mine = await _in_tx(fa, ta, lambda s: PosService.search_receipts(s, ta, q=number))
    assert not _refused(mine) and len(mine) == 1, f"A cannot find its own receipt: {mine!r}"

    sessions = await _in_tx(fb, tb, lambda s: PosService.list_sessions(s, tb))
    assert not _refused(sessions), sessions
    assert len(sessions) == 0, f"B sees {len(sessions)} of A's shifts"

    found = await _in_tx(fb, tb, lambda s: PosService.search_receipts(s, tb, q=number))
    assert not _refused(found), found
    rows = found.get("items", found) if isinstance(found, dict) else found
    assert len(rows) == 0, f"B sees {len(rows)} of A's receipts"

    # and the raw tables, with B's tenant bound: zero rows of A's, whatever the query asks for
    for table in (
        "orders",
        "pos_sessions",
        "pos_receipts",
        "product_variants",
        "inventory_balances",
    ):
        n = await _count(fb, tb, f"SELECT count(*) FROM {table}")  # noqa: S608
        assert n == 0, f"B can read {n} rows of A's {table}"


async def test_a_forged_tenant_id_is_refused_by_the_database(two_tenants) -> None:
    """Even code that LIES about the tenant (writes A's id while bound as B) is stopped by RLS."""
    (fa, ta), (fb, tb) = two_tenants
    await _a_shop(fa, ta)

    async def forge(s):
        from app.modules.catalog.models import Product

        s.add(
            Product(tenant_id=ta, title="forged", slug=f"f-{uuid.uuid4().hex[:8]}", status="active")
        )
        await s.flush()

    res = await _in_tx(fb, tb, forge)
    assert _refused(res), "B wrote a row stamped with A's tenant id"
