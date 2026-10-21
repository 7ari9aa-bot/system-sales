"""The money-only refund and the exchange obey the same safety rules as /returns.

Three gaps an audit found: a refund could restock the whole basket, the drawer movement followed
the ``method`` the caller sent rather than the cash legs actually refunded, and neither the refund
nor the exchange honoured the owner's refund ceiling.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.modules.inventory.service import InventoryService
from app.modules.pos.models import PosCashMovement
from app.modules.pos.profiles import ApprovalRequiredError, PosProfileService
from app.modules.pos.service import PosService
from tests.test_pos_money_ceilings import _till
from tests.test_pos_returns import _customer, _register, _sellable_variant, _warehouse

pytestmark = pytest.mark.asyncio


async def _mixed_till(db, tenant_ctx):
    """A till that accepts cash AND card, so one sale can be paid half and half."""
    register = await _register(db, tenant_ctx)
    wh = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="mixed",
        code=f"M{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        discount_ceiling_pct="100",
        allowed_payment_methods=["cash", "card"],
    )
    return await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, profile_id=profile.id
    )


async def _sale(db, tenant_ctx, shift, *, price="100.00", qty=1, tenders=None):
    variant = await _sellable_variant(db, tenant_ctx, price=price, stock=50)
    customer = await _customer(db, tenant_ctx)
    total = str(Decimal(price) * qty)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        tenders=tenders or [{"method": "cash", "amount": total}],
    )
    return variant, sold["order_id"]


async def _on_hand(db, tenant_ctx, variant) -> int:
    rows = await InventoryService.list_balances(db, tenant_ctx.tenant_id)
    return sum(b.on_hand for b in rows if b.variant_id == variant.id)


async def _cash_refund_total(db, shift) -> Decimal:
    return Decimal(
        str(
            (
                await db.execute(
                    sa.select(sa.func.coalesce(sa.func.sum(PosCashMovement.amount), 0)).where(
                        PosCashMovement.session_id == shift.id,
                        PosCashMovement.reason == "cash_refund",
                    )
                )
            ).scalar_one()
        )
    )


async def test_a_partial_money_refund_with_restock_flag_leaves_the_shelf_alone(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx)
    variant, order_id = await _sale(db, tenant_ctx, shift, price="10.00", qty=5)
    before = await _on_hand(db, tenant_ctx, variant)

    done = await PosService.refund(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=order_id,
        amount="10.00",  # one unit's worth of the five
        restock=True,
    )

    assert done["restocked"] is False
    assert await _on_hand(db, tenant_ctx, variant) == before  # not +5


async def test_drawer_follows_the_cash_legs_not_the_claimed_method(db, tenant_ctx):
    """Paid 60 cash + 40 card. A 100 refund claimed as "card" still takes 60 out of the drawer."""
    shift = await _mixed_till(db, tenant_ctx)
    _, order_id = await _sale(
        db,
        tenant_ctx,
        shift,
        tenders=[{"method": "cash", "amount": "60.00"}, {"method": "card", "amount": "40.00"}],
    )

    done = await PosService.refund(
        db, tenant_ctx.tenant_id, shift.id, order_id=order_id, amount="100.00", method="card"
    )

    assert Decimal(done["cash_out"]) == Decimal("60.00")
    assert await _cash_refund_total(db, shift) == Decimal("60.00")


async def test_a_card_only_sale_takes_nothing_from_the_drawer_even_if_cash_is_claimed(
    db, tenant_ctx
):
    shift = await _mixed_till(db, tenant_ctx)
    _, order_id = await _sale(
        db, tenant_ctx, shift, tenders=[{"method": "card", "amount": "100.00"}]
    )

    done = await PosService.refund(
        db, tenant_ctx.tenant_id, shift.id, order_id=order_id, amount="100.00", method="cash"
    )

    assert Decimal(done["cash_out"]) == Decimal("0")
    assert await _cash_refund_total(db, shift) == Decimal("0")


async def test_refund_above_the_ceiling_needs_a_manager(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx, refund_ceiling="50.00")
    _, order_id = await _sale(db, tenant_ctx, shift)

    with pytest.raises(ApprovalRequiredError):
        await PosService.refund(
            db, tenant_ctx.tenant_id, shift.id, order_id=order_id, amount="60.00"
        )
    assert await _cash_refund_total(db, shift) == Decimal("0")  # nothing was written

    done = await PosService.refund(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=order_id,
        amount="60.00",
        ceiling_override=True,
    )
    assert Decimal(done["amount"]) == Decimal("60.00")


async def test_refund_at_the_ceiling_and_with_no_ceiling_goes_through(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx, refund_ceiling="50.00")
    _, order_id = await _sale(db, tenant_ctx, shift)
    done = await PosService.refund(
        db, tenant_ctx.tenant_id, shift.id, order_id=order_id, amount="50.00"
    )
    assert Decimal(done["amount"]) == Decimal("50.00")

    free, _ = await _till(db, tenant_ctx)  # no ceiling set
    _, order_2 = await _sale(db, tenant_ctx, free)
    done = await PosService.refund(
        db, tenant_ctx.tenant_id, free.id, order_id=order_2, amount="100.00"
    )
    assert Decimal(done["amount"]) == Decimal("100.00")


async def test_exchange_above_the_ceiling_needs_a_manager_and_writes_nothing(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx, refund_ceiling="50.00")
    variant, order_id = await _sale(db, tenant_ctx, shift)
    other = await _sellable_variant(db, tenant_ctx, price="100.00", stock=50)
    before = await _on_hand(db, tenant_ctx, variant)

    kwargs = dict(
        order_id=order_id,
        return_lines=[{"variant_id": str(variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(other.id), "quantity": 1}],
    )
    with pytest.raises(ApprovalRequiredError):
        await PosService.exchange(db, tenant_ctx.tenant_id, shift.id, **kwargs)
    assert await _on_hand(db, tenant_ctx, variant) == before  # shelf untouched

    done = await PosService.exchange(
        db, tenant_ctx.tenant_id, shift.id, ceiling_override=True, **kwargs
    )
    assert done["return_receipt_id"] and done["new_receipt_id"]
