"""A return of a sale that took no payment: the goods come back and the invoice value is recorded.

The cashier layer does not move money, so there is no tender to refund. A sale recorded without a
payment can still be returned: the shelf grows, the return receipt carries the value, and no
Refund, OrderPayment or drawer movement is written. A sale that DID take payments keeps its old
behaviour (the refund is spread over its tenders), so history does not change.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.errors import ConflictError
from app.modules.inventory.models import InventoryBalance
from app.modules.orders.models import OrderPayment, Refund
from app.modules.pos.models import PosCashMovement, PosReturnLine
from app.modules.pos.service import PosService
from tests._pos_helpers import till

pytestmark = pytest.mark.asyncio


async def _sold(db, tenant_ctx, qty=2):
    shift, variant, customer = await till(db, tenant_ctx)
    register = await PosService._get_register(db, tenant_ctx.tenant_id, shift.register_id)
    sale = await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
    )
    return shift, variant, sale


async def _count(db, model, tenant_id):
    q = select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
    return (await db.execute(q)).scalar_one()


async def _on_hand(db, variant):
    return (
        await db.execute(
            select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant.id)
        )
    ).scalar_one()


async def test_returning_a_sale_with_no_payment_restocks_and_records_the_value(
    db, tenant_ctx
) -> None:
    shift, variant, sale = await _sold(db, tenant_ctx, qty=2)
    tid = tenant_ctx.tenant_id
    before = await _on_hand(db, variant)

    out = await PosService.return_sale(
        db,
        tid,
        shift.id,
        order_id=sale["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        restock=True,
        actor_user_id=tenant_ctx.user.id,
    )

    assert out["refunded_total"] == "100.00", (
        "the value of the returned unit, at the sale's own price"
    )
    assert out["by_method"] == [], "there is no tender to name: nothing was paid"
    assert out["restocked"] is True
    assert await _on_hand(db, variant) - before == 1
    assert await _count(db, PosReturnLine, tid) == 1
    assert await _count(db, OrderPayment, tid) == 0
    assert await _count(db, Refund, tid) == 0
    assert await _count(db, PosCashMovement, tid) == 0


async def test_the_quantity_cap_still_holds_without_payments(db, tenant_ctx) -> None:
    shift, variant, sale = await _sold(db, tenant_ctx, qty=1)
    args = dict(
        order_id=sale["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        restock=True,
        actor_user_id=tenant_ctx.user.id,
    )
    await PosService.return_sale(db, tenant_ctx.tenant_id, shift.id, **args)
    after_first = await _on_hand(db, variant)
    with pytest.raises(ConflictError):
        await PosService.return_sale(db, tenant_ctx.tenant_id, shift.id, **args)
    assert await _on_hand(db, variant) == after_first, (
        "a refused second return must not restock again"
    )
    assert await _count(db, PosReturnLine, tenant_ctx.tenant_id) == 1


async def test_a_return_the_next_day_rides_todays_session(db, tenant_ctx) -> None:
    """Yesterday's session was closed for the new day; the return rides TODAY's session, and the
    quantities and prices are still checked against the ORIGINAL sale."""
    from datetime import UTC, datetime, timedelta

    shift, variant, sale = await _sold(db, tenant_ctx, qty=2)
    tid = tenant_ctx.tenant_id
    shift.opened_at = datetime.now(UTC) - timedelta(days=2)  # the sale was rung on an older day
    await db.flush()
    register = await PosService._get_register(db, tid, shift.register_id)

    today = await PosService.working_session(db, tid, register.id)
    assert today.id != shift.id, "the stale session is closed and a fresh one is opened"

    out = await PosService.return_sale(
        db,
        tid,
        today.id,
        order_id=sale["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 2}],
        restock=True,
        actor_user_id=tenant_ctx.user.id,
    )
    assert out["refunded_total"] == "200.00"
    assert await _count(db, Refund, tid) == 0


# ------------------------------------------------------------- exchanges ----


async def _exchange_setup(db, tenant_ctx, *, new_price="150.00"):
    from tests.test_pos_returns import _sellable_variant

    shift, variant_a, sale = await _sold(db, tenant_ctx, qty=1)
    variant_b = await _sellable_variant(db, tenant_ctx, price=new_price, stock=20)
    return shift, variant_a, variant_b, sale


async def test_exchange_of_an_unpaid_sale_shows_the_difference_and_settles_nothing(
    db, tenant_ctx
) -> None:
    """A (100) comes back, B (150) goes out: the difference is 50, shown and never charged."""
    shift, a, b, sale = await _exchange_setup(db, tenant_ctx)
    tid = tenant_ctx.tenant_id
    a_before, b_before = await _on_hand(db, a), await _on_hand(db, b)

    out = await PosService.exchange(
        db,
        tid,
        shift.id,
        order_id=sale["order_id"],
        return_lines=[{"variant_id": str(a.id), "quantity": 1}],
        new_lines=[{"variant_id": str(b.id), "quantity": 1}],
        restock=True,
        actor_user_id=tenant_ctx.user.id,
    )

    assert out["return_total"] == "100.00"
    assert out["new_total"] == "150.00"
    assert out["net"] == "50.00", "the difference is reported"
    assert out["by_method"] == []
    assert await _on_hand(db, a) - a_before == 1, "the returned item is back on the shelf"
    assert b_before - await _on_hand(db, b) == 1, "the new item left the shelf"
    assert await _count(db, OrderPayment, tid) == 0, "nothing is charged, not even the difference"
    assert await _count(db, Refund, tid) == 0
    assert await _count(db, PosCashMovement, tid) == 0


async def test_exchange_where_the_shop_owes_the_customer_is_also_only_shown(db, tenant_ctx) -> None:
    shift, a, b, sale = await _exchange_setup(db, tenant_ctx, new_price="60.00")
    out = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sale["order_id"],
        return_lines=[{"variant_id": str(a.id), "quantity": 1}],
        new_lines=[{"variant_id": str(b.id), "quantity": 1}],
        restock=True,
        actor_user_id=tenant_ctx.user.id,
    )
    assert out["net"] == "-40.00"
    assert await _count(db, Refund, tenant_ctx.tenant_id) == 0
    assert await _count(db, PosCashMovement, tenant_ctx.tenant_id) == 0


async def test_tenders_sent_on_an_unpaid_exchange_are_ignored_not_booked(db, tenant_ctx) -> None:
    """The exchange screen may still send tenders. For an order with no payment they must neither
    fail the exchange nor create a payment."""
    shift, a, b, sale = await _exchange_setup(db, tenant_ctx)
    out = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sale["order_id"],
        return_lines=[{"variant_id": str(a.id), "quantity": 1}],
        new_lines=[{"variant_id": str(b.id), "quantity": 1}],
        restock=True,
        tenders=[{"method": "cash", "amount": "50.00"}],
        tendered_cash="50.00",
        actor_user_id=tenant_ctx.user.id,
    )
    assert out["net"] == "50.00"
    assert await _count(db, OrderPayment, tenant_ctx.tenant_id) == 0
    assert await _count(db, PosCashMovement, tenant_ctx.tenant_id) == 0
