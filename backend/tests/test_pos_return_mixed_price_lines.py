"""A return is priced from EVERY line the variant sold on, not from whichever came first.

The same variant can sit on an invoice twice at different unit prices (a tier price, a
cashier-edited price). Returning from it takes the quantity-weighted average of those lines;
pricing the whole return at the first line's price over- or under-refunds the invoice value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.orders.models import Order, OrderItem
from app.modules.pos.service import PosService
from tests._pos_sell import sell as pos_sell
from tests.test_pos_returns import _customer, _register, _sellable_variant

pytestmark = pytest.mark.asyncio


async def _two_priced_lines(db, tenant_ctx):
    """One variant sold as 1 x 10.00 and 3 x 30.00 on the same invoice (weighted average 25.00)."""
    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx, price="25.00", stock=20)
    customer = await _customer(db, tenant_ctx)
    sold = await pos_sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 4}],
    )
    first = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == sold["order_id"])))
        .scalars()
        .one()
    )
    # Split the single line into two priced lines: 1 @ 10.00 and 3 @ 30.00 (invoice 100.00).
    first.quantity, first.unit_price, first.total = 1, Decimal("10.00"), Decimal("10.00")
    db.add(
        OrderItem(
            tenant_id=tenant_ctx.tenant_id,
            order_id=first.order_id,
            variant_id=variant.id,
            title=first.title,
            quantity=3,
            unit_price=Decimal("30.00"),
            total=Decimal("90.00"),
        )
    )
    await db.flush()
    return pos_session, sold, variant


async def test_a_return_is_priced_at_the_weighted_average_of_the_lines(db, tenant_ctx) -> None:
    pos_session, sold, variant = await _two_priced_lines(db, tenant_ctx)
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 2}],
    )
    # (1*10 + 3*30) / 4 = 25.00 per unit -> 2 units = 50.00. The first line alone would say 20.00.
    assert Decimal(result["refunded_total"]) == Decimal("50.00")


async def test_returning_everything_refunds_exactly_the_invoice(db, tenant_ctx) -> None:
    pos_session, sold, variant = await _two_priced_lines(db, tenant_ctx)
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 4}],
    )
    assert Decimal(result["refunded_total"]) == Decimal("100.00")


async def _half_cent_lines(db, tenant_ctx):
    """One variant sold as 1 x 10.00 and 1 x 10.01: the invoice is 20.01, the average 10.005."""
    pos_session, sold, variant = await _two_priced_lines(db, tenant_ctx)
    rows = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == sold["order_id"])))
        .scalars()
        .all()
    )
    a, b = rows
    a.quantity, a.unit_price, a.total = 1, Decimal("10.00"), Decimal("10.00")
    b.quantity, b.unit_price, b.total = 1, Decimal("10.01"), Decimal("10.01")
    order = await db.get(Order, sold["order_id"])
    order.subtotal = order.grand_total = Decimal("20.01")
    await db.flush()
    return pos_session, sold, variant


async def test_a_half_cent_average_never_refunds_more_than_the_invoice(db, tenant_ctx) -> None:
    pos_session, sold, variant = await _half_cent_lines(db, tenant_ctx)
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 2}],
    )
    assert Decimal(result["refunded_total"]) == Decimal("20.01")  # not 20.02


async def test_repeated_partial_returns_add_up_to_exactly_the_invoice(db, tenant_ctx) -> None:
    pos_session, sold, variant = await _half_cent_lines(db, tenant_ctx)
    total = Decimal("0")
    for _ in range(2):
        result = await PosService.return_sale(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )
        total += Decimal(result["refunded_total"])
    assert total == Decimal("20.01")


async def _three_items_one_cent_discount(db, tenant_ctx):
    """Three variants at 10.00 each with a 0.01 order discount: the invoice is 29.99."""
    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    customer = await _customer(db, tenant_ctx)
    variants = [await _sellable_variant(db, tenant_ctx, price="10.00", stock=20) for _ in range(3)]
    sold = await pos_sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(v.id), "quantity": 1} for v in variants],
        discount_total="0.01",
    )
    assert Decimal(sold["grand_total"]) == Decimal("29.99")
    return pos_session, sold, variants


async def test_returning_every_line_of_a_discounted_invoice_refunds_exactly_its_total(
    db, tenant_ctx
) -> None:
    pos_session, sold, variants = await _three_items_one_cent_discount(db, tenant_ctx)
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(v.id), "quantity": 1} for v in variants],
    )
    assert Decimal(result["refunded_total"]) == Decimal("29.99")  # not 30.00


async def test_returning_one_line_at_a_time_never_exceeds_the_invoice(db, tenant_ctx) -> None:
    pos_session, sold, variants = await _three_items_one_cent_discount(db, tenant_ctx)
    total = Decimal("0")
    for v in variants:
        result = await PosService.return_sale(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(v.id), "quantity": 1}],
        )
        total += Decimal(result["refunded_total"])
    assert total == Decimal("29.99")


def test_line_title_names_the_product_and_adds_the_variant_only_when_it_says_something() -> None:
    from app.modules.orders.service import line_title

    assert line_title("قميص قطن", "عادي") == "قميص قطن"  # the default variant adds nothing
    assert line_title("قميص قطن", "") == "قميص قطن"
    assert line_title("قميص قطن", None) == "قميص قطن"
    assert line_title("قميص قطن", "أزرق / L") == "قميص قطن - أزرق / L"
    assert line_title("قميص قطن", "قميص قطن") == "قميص قطن"  # never repeat the same words
    assert line_title(None, "أزرق / L") == "أزرق / L"  # no product row: keep what we have
    assert line_title(None, None) == ""


async def test_the_stored_invoice_line_carries_the_product_name(db, tenant_ctx) -> None:
    from sqlalchemy import select

    from app.modules.orders.models import OrderItem

    pos_session, sold, variants = await _three_items_one_cent_discount(db, tenant_ctx)
    items = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == sold["order_id"])))
        .scalars()
        .all()
    )
    assert items
    for item in items:
        assert item.title not in ("", "سعة كبيرة")  # the variant's own name alone is not enough
        assert item.title.startswith("تيشيرت")  # the product name leads
