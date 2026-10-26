"""A return is priced from EVERY line the variant sold on, not from whichever came first.

The same variant can sit on an invoice twice at different unit prices (a tier price, a
cashier-edited price). Returning from it takes the quantity-weighted average of those lines;
pricing the whole return at the first line's price over- or under-refunds the invoice value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.orders.models import OrderItem
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
