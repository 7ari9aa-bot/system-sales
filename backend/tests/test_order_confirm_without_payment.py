"""A counter sale is RECORDED, not paid for: stock converts and the order confirms, no payment row.

`OrderService.add_payment` does four things at once (record the payment, convert the stock
reservation, confirm the order, refresh the customer's value). The cashier needs the last three
without the first, and the other channels keep `add_payment` exactly as it is.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.modules.inventory.models import InventoryBalance, InventoryReservation
from app.modules.orders.models import Order, OrderPayment
from app.modules.orders.service import OrderService
from app.modules.pos.service import PosService
from tests._pos_helpers import till

pytestmark = pytest.mark.asyncio


async def _order(db, tenant_ctx, qty=2):
    shift, variant, customer = await till(db, tenant_ctx)
    tid = tenant_ctx.tenant_id
    register = await PosService._get_register(db, tid, shift.register_id)
    order = await OrderService.create_order(
        db,
        tid,
        customer.id,
        [{"variant_id": variant.id, "quantity": qty}],
        channel="pos",
        warehouse_id=register.warehouse_id,
    )
    return variant, tid, order


async def test_confirm_sale_converts_stock_and_confirms_without_a_payment_row(
    db, tenant_ctx
) -> None:
    variant, tid, order = await _order(db, tenant_ctx)
    assert order.status == "pending"

    confirmed = await OrderService.confirm_sale(db, tid, order.id)

    assert confirmed.status == "confirmed"
    payments = (
        await db.execute(
            select(func.count()).select_from(OrderPayment).where(OrderPayment.order_id == order.id)
        )
    ).scalar_one()
    assert payments == 0, "recording a sale must not invent a payment"
    statuses = (
        (
            await db.execute(
                select(InventoryReservation.status).where(InventoryReservation.order_id == order.id)
            )
        )
        .scalars()
        .all()
    )
    assert statuses and set(statuses) == {"CONVERTED"}, "the reservation must become a real sale"


async def test_confirm_sale_takes_the_stock_off_the_shelf_once(db, tenant_ctx) -> None:
    variant, tid, order = await _order(db, tenant_ctx, qty=3)
    before = (
        await db.execute(
            select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant.id)
        )
    ).scalar_one()

    await OrderService.confirm_sale(db, tid, order.id)
    await OrderService.confirm_sale(db, tid, order.id)  # a retry must not take it twice

    after = (
        await db.execute(
            select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant.id)
        )
    ).scalar_one()
    assert before - after == 3


async def test_confirm_sale_refuses_a_cancelled_order(db, tenant_ctx) -> None:
    from app.core.errors import ConflictError

    variant, tid, order = await _order(db, tenant_ctx)
    await OrderService.cancel_order(db, tid, order.id)
    with pytest.raises(ConflictError):
        await OrderService.confirm_sale(db, tid, order.id)


async def test_add_payment_for_other_channels_is_untouched(db, tenant_ctx) -> None:
    """The WhatsApp/inbox path still records the payment, converts and confirms."""
    variant, tid, order = await _order(db, tenant_ctx, qty=1)
    await OrderService.add_payment(db, tid, order.id, method="cash", amount=order.grand_total)
    refreshed = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert refreshed.status == "confirmed"
    assert (
        await db.execute(
            select(func.count()).select_from(OrderPayment).where(OrderPayment.order_id == order.id)
        )
    ).scalar_one() == 1
