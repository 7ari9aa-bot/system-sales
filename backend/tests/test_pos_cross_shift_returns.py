"""A sale rung on one shift can be returned on a LATER shift (after the first one is closed).

The customer comes back tomorrow; yesterday's drawer was counted and closed. The return is checked
against the ORIGINAL sale (quantities, prices, the tenders the customer paid with) but the money
leaves the drawer that is OPEN NOW: re-opening a counted drawer would falsify its closing, and
booking the payout on it would make a closed report change after the fact.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests._pos_sell import sell as pos_sell
from tests.test_pos_returns import _customer, _register, _sellable_variant

pytestmark = pytest.mark.asyncio


async def _sale_then_next_day(db, tenant_ctx, *, qty=2, price="25.00"):
    """Sell on shift A, count and close A, open shift B on the same register."""
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    first = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx, price=price, stock=10)
    customer = await _customer(db, tenant_ctx)
    sold = await pos_sell(
        db,
        tenant_ctx.tenant_id,
        first.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
    )
    await PosService.close_session(db, tenant_ctx.tenant_id, first.id)
    second = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opening_float="100.00"
    )
    return first, second, variant, sold


async def test_a_closed_shifts_sale_can_be_returned_on_the_open_shift(db, tenant_ctx):
    from app.modules.pos.service import PosService

    first, second, variant, sold = await _sale_then_next_day(db, tenant_ctx)
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        second.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        restock=True,
    )
    assert Decimal(result["refunded_total"]) == Decimal("25.00")

    # the money left TODAY's drawer: float 100 - 25 refund
    today = await PosService.get_session(db, tenant_ctx.tenant_id, second.id)
    assert today["expected_now"] == Decimal("75.00")


async def test_the_closed_shift_is_not_touched_by_a_later_return(db, tenant_ctx):
    from app.modules.pos.service import PosService

    first, second, variant, sold = await _sale_then_next_day(db, tenant_ctx)
    before = await PosService.get_session(db, tenant_ctx.tenant_id, first.id)
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        second.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    after = await PosService.get_session(db, tenant_ctx.tenant_id, first.id)
    # a counted, closed drawer's figures never move after the fact
    assert after["expected_now"] == before["expected_now"]
    assert (after["inflow"], after["outflow"]) == (before["inflow"], before["outflow"])
    assert after["session"].status == "CLOSED"


async def test_the_quantity_cap_still_holds_across_shifts(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    first, second, variant, sold = await _sale_then_next_day(db, tenant_ctx, qty=2)
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        second.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 2}],
    )
    with pytest.raises(ConflictError, match="already returned"):
        await PosService.return_sale(
            db,
            tenant_ctx.tenant_id,
            second.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )


async def test_an_exchange_works_across_shifts_too(db, tenant_ctx):
    from app.modules.pos.service import PosService

    first, second, variant, sold = await _sale_then_next_day(db, tenant_ctx)
    other = await _sellable_variant(db, tenant_ctx, price="25.00", stock=10)
    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        second.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(other.id), "quantity": 1}],
    )
    assert result is not None
    today = await PosService.get_session(db, tenant_ctx.tenant_id, second.id)
    assert today["session"].status == "OPEN"
    # the return (25) funds the replacement (25): nothing physically leaves today's drawer
    assert today["expected_now"] == Decimal("100.00")
