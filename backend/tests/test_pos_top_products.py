"""Best sellers: ranked by NET revenue, with what came back in the window taken off.

A product that sells and is returned must not rank as a hit, and the figures must agree with the
day report built from the same receipts. There is no cost or profit here by design.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import text

from tests._pos_sell import sell as pos_sell
from tests.test_pos_exchange import _customer, _register, _sellable_variant

WIDE = {"since": date(2000, 1, 1), "until": date(2100, 1, 1)}


async def _till(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    return PosService, pos_session, await _customer(db, tenant_ctx)


async def _sell(db, tenant_ctx, PosService, pos_session, customer, variant, qty, price):
    return await pos_sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        tenders=[{"method": "cash", "amount": str(Decimal(price) * qty)}],
    )


async def test_ranked_by_net_revenue(db, tenant_ctx):
    PosService, pos_session, customer = await _till(db, tenant_ctx)
    cheap = await _sellable_variant(db, tenant_ctx, price="10.00", stock=50)
    dear = await _sellable_variant(db, tenant_ctx, price="100.00", stock=50)
    await _sell(db, tenant_ctx, PosService, pos_session, customer, cheap, 5, "10.00")  # 50
    await _sell(db, tenant_ctx, PosService, pos_session, customer, dear, 2, "100.00")  # 200

    rows = await PosService.top_products(db, tenant_ctx.tenant_id, **WIDE)
    assert [r["variant_id"] for r in rows] == [str(dear.id), str(cheap.id)]
    assert rows[0]["net_revenue"] == "200.00" and rows[0]["sold_qty"] == 2
    assert rows[1]["net_revenue"] == "50.00" and rows[1]["net_qty"] == 5


async def test_a_return_takes_the_product_down_the_ranking(db, tenant_ctx):
    PosService, pos_session, customer = await _till(db, tenant_ctx)
    a = await _sellable_variant(db, tenant_ctx, price="100.00", stock=50)
    b = await _sellable_variant(db, tenant_ctx, price="60.00", stock=50)
    sold_a = await _sell(db, tenant_ctx, PosService, pos_session, customer, a, 2, "100.00")  # 200
    await _sell(db, tenant_ctx, PosService, pos_session, customer, b, 2, "60.00")  # 120
    # A comes back 2 of 2: its net revenue falls to 0 and B overtakes it.
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold_a["order_id"],
        lines=[{"variant_id": str(a.id), "quantity": 2}],
        restock=True,
    )
    rows = await PosService.top_products(db, tenant_ctx.tenant_id, **WIDE)
    assert [r["variant_id"] for r in rows] == [str(b.id), str(a.id)]
    ra = rows[1]
    assert (ra["sold_qty"], ra["returned_qty"], ra["net_qty"]) == (2, 2, 0)
    assert ra["net_revenue"] == "0.00"


async def test_the_total_matches_the_day_report(db, tenant_ctx):
    PosService, pos_session, customer = await _till(db, tenant_ctx)
    v = await _sellable_variant(db, tenant_ctx, price="40.00", stock=50)
    sold = await _sell(db, tenant_ctx, PosService, pos_session, customer, v, 3, "40.00")
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(v.id), "quantity": 1}],
        restock=True,
    )
    top = await PosService.top_products(db, tenant_ctx.tenant_id, **WIDE)
    day = (await PosService.sales_by_day(db, tenant_ctx.tenant_id, **WIDE))[0]
    assert sum(Decimal(r["net_revenue"]) for r in top) == Decimal(day["net"]) == Decimal("80.00")


async def test_outside_the_window_is_excluded_and_limit_is_respected(db, tenant_ctx):
    PosService, pos_session, customer = await _till(db, tenant_ctx)
    first = await _sellable_variant(db, tenant_ctx, price="30.00", stock=50)
    second = await _sellable_variant(db, tenant_ctx, price="20.00", stock=50)
    await _sell(db, tenant_ctx, PosService, pos_session, customer, first, 1, "30.00")
    await _sell(db, tenant_ctx, PosService, pos_session, customer, second, 1, "20.00")
    assert len(await PosService.top_products(db, tenant_ctx.tenant_id, limit=1, **WIDE)) == 1
    await db.execute(
        text("UPDATE pos_receipts SET issued_at = '2026-03-11 10:00:00+00' WHERE session_id = :s"),
        {"s": pos_session.id},
    )
    assert (
        await PosService.top_products(
            db, tenant_ctx.tenant_id, since=date(2026, 4, 1), until=date(2026, 4, 30)
        )
        == []
    )
    assert (
        len(
            await PosService.top_products(
                db, tenant_ctx.tenant_id, since=date(2026, 3, 11), until=date(2026, 3, 11)
            )
        )
        == 2
    )


async def test_nothing_sold_is_an_empty_list(db, tenant_ctx):
    from app.modules.pos.service import PosService

    assert await PosService.top_products(db, tenant_ctx.tenant_id, **WIDE) == []


async def test_an_invoice_level_discount_is_shared_over_the_lines_and_the_total_still_matches(
    db, tenant_ctx
):
    """The order carries the invoice discount, the lines do not: revenue must still add up.

    Without sharing it out, the best sellers over-state revenue by every invoice discount and
    stop matching the day report. 3 lines and a 10.00 discount do not divide evenly, so this also
    pins that no cent is lost or invented by rounding.
    """
    PosService, pos_session, customer = await _till(db, tenant_ctx)
    a = await _sellable_variant(db, tenant_ctx, price="33.33", stock=50)
    b = await _sellable_variant(db, tenant_ctx, price="33.33", stock=50)
    c = await _sellable_variant(db, tenant_ctx, price="33.34", stock=50)
    sold = await pos_sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[
            {"variant_id": str(a.id), "quantity": 1},
            {"variant_id": str(b.id), "quantity": 1},
            {"variant_id": str(c.id), "quantity": 1},
        ],
        discount_total="10.00",
        tenders=[{"method": "cash", "amount": "90.00"}],
    )
    assert sold is not None
    top = await PosService.top_products(db, tenant_ctx.tenant_id, **WIDE)
    day = (await PosService.sales_by_day(db, tenant_ctx.tenant_id, **WIDE))[0]
    assert Decimal(day["discount"]) == Decimal("10.00")
    assert Decimal(day["net"]) == Decimal("90.00")
    assert sum(Decimal(r["net_revenue"]) for r in top) == Decimal("90.00")  # not 100.00
    assert all(Decimal(r["net_revenue"]) < Decimal("34.00") for r in top)
