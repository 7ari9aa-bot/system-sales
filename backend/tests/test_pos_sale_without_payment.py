"""A cashier sells with no shift and no payment: the sale is recorded and the stock moves.

The cashier layer records WHAT was sold and at what price; how the customer paid is not its
business.
So `record_sale` needs no open shift, no tender, no method and no amount, and it never writes an
OrderPayment, a Refund or a drawer movement.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.errors import ConflictError, ValidationError
from app.modules.inventory.models import InventoryBalance
from app.modules.orders.models import Order, OrderPayment, Refund
from app.modules.pos.models import PosCashMovement, PosSession
from app.modules.pos.service import PosService
from tests._pos_helpers import till

pytestmark = pytest.mark.asyncio


async def _shop(db, tenant_ctx):
    shift, variant, customer = await till(db, tenant_ctx)
    # The till helper opens a shift; close it so the test proves a sale needs none.
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, counted_cash="0.00")
    register = await PosService._get_register(db, tenant_ctx.tenant_id, shift.register_id)
    return register, variant, customer


async def _count(db, model, **where):
    q = select(func.count()).select_from(model)
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return (await db.execute(q)).scalar_one()


async def test_sale_with_no_open_shift_and_no_payment_is_recorded(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    tid = tenant_ctx.tenant_id
    on_hand = lambda: db.execute(  # noqa: E731
        select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == variant.id)
    )
    before = (await on_hand()).scalar_one()

    out = await PosService.record_sale(
        db,
        tid,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
    )

    assert out["grand_total"] == "200.00"
    assert out["receipt_number"].startswith("POS-")
    assert before - (await on_hand()).scalar_one() == 2, "the stock must come off the shelf"
    order = (await db.execute(select(Order).where(Order.id == out["order_id"]))).scalar_one()
    assert order.status == "confirmed"
    assert await _count(db, OrderPayment, order_id=order.id) == 0
    assert await _count(db, Refund, tenant_id=tid) == 0
    assert await _count(db, PosCashMovement, tenant_id=tid) == 0


async def test_it_records_who_sold_on_the_receipt(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    out = await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
    )
    receipt = await PosService.get_receipt(db, tenant_ctx.tenant_id, out["receipt_id"])
    assert receipt["receipt"]["sold_by_user_id"] == str(tenant_ctx.user.id)


async def test_two_cashiers_on_one_register_both_sell(db, tenant_ctx) -> None:
    """The old per-user / per-register one-open-shift rules must not block a second seller."""
    register, variant, customer = await _shop(db, tenant_ctx)
    import uuid

    for who in (tenant_ctx.user.id, uuid.uuid4()):
        out = await PosService.record_sale(
            db,
            tenant_ctx.tenant_id,
            register.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
            customer_id=customer.id,
            actor_user_id=who if who == tenant_ctx.user.id else None,
        )
        assert out["receipt_id"]
    open_sessions = await _count(db, PosSession, register_id=register.id, status="OPEN")
    assert open_sessions == 1, "one working session is reused, not one per sale"


async def test_it_ignores_a_stray_payment_and_never_creates_one(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    with pytest.raises(TypeError):
        await PosService.record_sale(  # type: ignore[call-arg]
            db,
            tenant_ctx.tenant_id,
            register.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
            tenders=[{"method": "cash", "amount": "100.00"}],
        )


async def test_sale_still_refuses_what_cannot_be_sold(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    tid = tenant_ctx.tenant_id
    base = {"customer_id": customer.id, "actor_user_id": tenant_ctx.user.id}
    with pytest.raises(ValidationError):
        await PosService.record_sale(db, tid, register.id, items=[], **base)
    with pytest.raises(ValidationError):
        await PosService.record_sale(
            db, tid, register.id, items=[{"variant_id": str(variant.id), "quantity": 0}], **base
        )
    with pytest.raises(Exception, match="(?i)stock|reserve"):
        await PosService.record_sale(
            db, tid, register.id, items=[{"variant_id": str(variant.id), "quantity": 999}], **base
        )


async def test_a_free_sale_with_a_full_discount_is_recorded(db, tenant_ctx) -> None:
    """100% off used to be refused because a 0.01 'payment' never matched a 0.00 total."""
    register, variant, customer = await _shop(db, tenant_ctx)
    out = await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": 1, "discount_pct": "100.00"}],
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
    )
    assert out["grand_total"] == "0.00"


async def test_an_inactive_register_cannot_sell(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    register.is_active = False
    await db.flush()
    with pytest.raises(ConflictError):
        await PosService.record_sale(
            db,
            tenant_ctx.tenant_id,
            register.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
            customer_id=customer.id,
        )
