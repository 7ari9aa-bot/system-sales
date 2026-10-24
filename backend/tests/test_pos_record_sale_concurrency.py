"""Real concurrency on `record_sale`: no shift, no payment, still no overselling.

Separate committed connections race. Two things must hold with NO shift opened beforehand:
the first sales of the day open exactly ONE working session between them, and the last unit on the
shelf is sold once. The stock is taken at confirmation, so a loser must be refused, never oversold.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.inventory.models import InventoryBalance
from app.modules.orders.models import OrderPayment
from app.modules.pos.models import PosCashMovement, PosSession
from app.modules.pos.service import PosService
from tests._pos_helpers import in_tx, make_tenant, purge_test_tenant

pytestmark = pytest.mark.asyncio

RACERS = 6


@pytest.fixture
async def shop(db_url, admin_url):
    engine, _factory, tenant_id, user_id = await make_tenant(db_url, "rs")
    # Every racer holds its own connection, so the pool is wider than the helper's default.
    big = create_async_engine(
        db_url, pool_size=RACERS + 3, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(big, expire_on_commit=False)
    try:
        yield factory, tenant_id, user_id
    finally:
        await big.dispose()
        await engine.dispose()
        await purge_test_tenant(admin_url, tenant_id, user_id)


async def _shelf(factory, t, stock: int):
    """A register whose day HAS been started (opening balance entered), and one variant with exactly
    `stock` units."""

    async def setup(s):
        from app.modules.catalog.service import CatalogService
        from app.modules.inventory.service import InventoryService

        wh = await InventoryService.get_default_warehouse(s, t)
        reg = await PosService.create_register(
            s, t, name="k", code=f"R-{uuid.uuid4().hex[:6]}", warehouse_id=wh.id
        )
        await PosService.open_day(s, t, reg.id, opening_float="100.00")
        product = await CatalogService.create_product(
            s, t, title="x", slug=f"p-{uuid.uuid4().hex[:10]}"
        )
        product = await CatalogService.update_product(s, t, product.id, status="active")
        variant = await CatalogService.add_variant(s, t, product.id, title="v", price="25.00")
        await InventoryService.move(
            s, t, variant.id, wh.id, direction="in", quantity=stock, reason="purchase"
        )
        return reg.id, variant.id

    out = await in_tx(factory, t, setup)
    assert not isinstance(out, Exception), out
    return out


async def _race(factory, t, register_id, variant_id, who):
    async def one(s):
        return await PosService.record_sale(
            s,
            t,
            register_id,
            items=[{"variant_id": str(variant_id), "quantity": 1}],
            actor_user_id=who,
        )

    return await asyncio.gather(*[in_tx(factory, t, one) for _ in range(RACERS)])


async def _read(factory, t, fn):
    out = await in_tx(factory, t, fn)
    assert not isinstance(out, Exception), out
    return out


async def test_one_unit_six_sales_exactly_one_wins_on_the_one_open_day(shop) -> None:
    factory, t, user = shop
    register_id, variant_id = await _shelf(factory, t, stock=1)

    results = await _race(factory, t, register_id, variant_id, user)

    wins = [r for r in results if isinstance(r, dict)]
    losses = [r for r in results if isinstance(r, Exception)]
    assert len(wins) == 1, f"exactly one sale must win, got {len(wins)}: {losses}"
    assert len(losses) == RACERS - 1

    on_hand = await _read(
        factory,
        t,
        lambda s: s.execute(
            select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant_id)
        ),
    )
    assert on_hand.scalar_one() == 0, "the shelf is empty, never negative"

    sessions = await _read(
        factory,
        t,
        lambda s: s.execute(
            select(func.count())
            .select_from(PosSession)
            .where(PosSession.register_id == register_id)
        ),
    )
    assert sessions.scalar_one() == 1, "the racers must share the ONE session the day opened"


async def test_three_units_six_sales_exactly_three_win_with_no_money_rows(shop) -> None:
    factory, t, user = shop
    register_id, variant_id = await _shelf(factory, t, stock=3)

    results = await _race(factory, t, register_id, variant_id, user)

    assert sum(isinstance(r, dict) for r in results) == 3
    on_hand = await _read(
        factory,
        t,
        lambda s: s.execute(
            select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant_id)
        ),
    )
    assert on_hand.scalar_one() == 0

    async def money(s):
        pay = (await s.execute(select(func.count()).select_from(OrderPayment))).scalar_one()
        cash = (await s.execute(select(func.count()).select_from(PosCashMovement))).scalar_one()
        return pay, cash

    assert await _read(factory, t, money) == (0, 0), "no payment and no drawer row, ever"


async def test_first_sales_on_different_items_still_share_one_session(shop) -> None:
    """Different variants share no stock lock, so ONLY the unique index stops two sessions opening.

    The one-unit race above is serialised by the stock row lock, which would hide a broken
    session-open race. Here every racer sells its own item, so nothing else orders them.
    """
    factory, t, user = shop
    register_id, _v = await _shelf(factory, t, stock=1)
    variants = [(await _shelf(factory, t, stock=1))[1] for _ in range(RACERS)]

    async def one(variant_id):
        async def sale(s):
            return await PosService.record_sale(
                s,
                t,
                register_id,
                items=[{"variant_id": str(variant_id), "quantity": 1}],
                actor_user_id=user,
            )

        return await in_tx(factory, t, sale)

    results = await asyncio.gather(*[one(v) for v in variants])

    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f"every item had stock, so every sale must succeed: {errors}"
    sessions = await _read(
        factory,
        t,
        lambda s: s.execute(
            select(func.count())
            .select_from(PosSession)
            .where(PosSession.register_id == register_id)
        ),
    )
    assert sessions.scalar_one() == 1, "the racers must share the ONE session the day opened"


async def test_a_close_racing_six_sales_never_misses_an_invoice(shop) -> None:
    """The close computes the day's balance, so it must see EVERY invoice that made it in.

    Six sales and one close start together on separate connections. The day row is locked, so
    they queue: whatever committed before the close is inside its balance, and anything that
    queued behind the close finds the day CLOSED and is refused instead of landing after it.
    """
    from app.modules.orders.models import Order

    factory, t, user = shop
    register_id, variant_id = await _shelf(factory, t, stock=20)

    async def session_id(s):
        row = await s.execute(select(PosSession.id).where(PosSession.register_id == register_id))
        return row.scalar_one()

    day_id = await _read(factory, t, session_id)

    async def close(s):
        return await PosService.close_session(s, t, day_id, closed_by=user)

    results = await asyncio.gather(
        *[
            in_tx(factory, t, lambda s: _sale_once(s, t, register_id, variant_id, user))
            for _ in range(RACERS)
        ],
        in_tx(factory, t, close),
    )
    sales, closing = results[:RACERS], results[RACERS]
    assert not isinstance(closing, Exception), closing

    async def totals(s):
        day = (await s.execute(select(PosSession).where(PosSession.id == day_id))).scalar_one()
        invoiced = (
            await s.execute(
                select(func.coalesce(func.sum(Order.grand_total), 0)).where(
                    Order.tenant_id == t, Order.channel == "pos"
                )
            )
        ).scalar_one()
        return day, invoiced

    day, invoiced = await _read(factory, t, totals)
    assert day.status == "CLOSED"
    won = sum(isinstance(r, dict) for r in sales)
    # 25.00 a piece, opening balance 100.00: the stored balance holds the invoices that exist.
    assert invoiced == 25 * won
    assert day.expected_cash == 100 + invoiced, "the close must include every committed invoice"
    for r in sales:
        if isinstance(r, Exception):
            assert "closed" in str(r).lower() or "not been started" in str(r).lower(), r


async def _sale_once(s, t, register_id, variant_id, user):
    return await PosService.record_sale(
        s,
        t,
        register_id,
        items=[{"variant_id": str(variant_id), "quantity": 1}],
        actor_user_id=user,
    )
