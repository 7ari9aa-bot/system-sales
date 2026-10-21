"""A return and a cash pay-out above the owner's ceiling need a manager; nothing else changes.

The ceilings are profile settings the shop owner sets. NULL means "no limit" and must change
nothing for a shop that has not set one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.modules.errors import ValidationError
from app.modules.pos.models import PosCashMovement
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from tests.test_pos_returns import _customer, _register, _sellable_variant, _warehouse

pytestmark = pytest.mark.asyncio


async def _till(db, tenant_ctx, **ceilings):
    register = await _register(db, tenant_ctx)
    wh = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="كاشير",
        code=f"P{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        discount_ceiling_pct="100",
        allowed_payment_methods=["cash"],
        **ceilings,
    )
    shift = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, profile_id=profile.id
    )
    return shift, profile


async def _sold_order(db, tenant_ctx, shift, *, price="100.00"):
    variant = await _sellable_variant(db, tenant_ctx, price=price, stock=50)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        tenders=[{"method": "cash", "amount": price}],
    )
    return variant, sold["order_id"]


def _return(db, tenant_ctx, shift, variant, order_id, **kw):
    return PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=order_id,
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        **kw,
    )


async def _cash_rows(db, shift) -> int:
    return (
        await db.execute(
            sa.select(sa.func.count())
            .select_from(PosCashMovement)
            .where(PosCashMovement.session_id == shift.id, PosCashMovement.reason == "pay_out")
        )
    ).scalar_one()


# ------------------------------------------------------------------ returns --


async def test_no_ceiling_set_means_a_return_of_any_size_goes_through(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx)  # the owner set nothing
    variant, order_id = await _sold_order(db, tenant_ctx, shift)
    done = await _return(db, tenant_ctx, shift, variant, order_id)
    assert Decimal(done["refunded_total"]) == Decimal("100.00")


async def test_a_return_at_the_ceiling_goes_through(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx, refund_ceiling="100.00")
    variant, order_id = await _sold_order(db, tenant_ctx, shift)
    done = await _return(db, tenant_ctx, shift, variant, order_id)
    assert Decimal(done["refunded_total"]) == Decimal("100.00")


async def test_a_return_over_the_ceiling_is_refused_and_touches_nothing(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx, refund_ceiling="99.99")
    variant, order_id = await _sold_order(db, tenant_ctx, shift)
    with pytest.raises(ValidationError, match="manager"):
        await _return(db, tenant_ctx, shift, variant, order_id)
    # Nothing was booked: the same return still works once a manager approves it, in full.
    done = await _return(db, tenant_ctx, shift, variant, order_id, ceiling_override=True)
    assert Decimal(done["refunded_total"]) == Decimal("100.00")


async def test_the_ceiling_judges_the_discounted_amount_actually_handed_back(db, tenant_ctx):
    """A 100 item sold at 50% off refunds 50, so a 60 ceiling does not stop it."""
    shift, _ = await _till(db, tenant_ctx, refund_ceiling="60.00")
    variant = await _sellable_variant(db, tenant_ctx, price="100.00", stock=50)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1, "discount_pct": "50"}],
        tenders=[{"method": "cash", "amount": "50.00"}],
        discount_override=True,
    )
    done = await _return(db, tenant_ctx, shift, variant, sold["order_id"])
    assert Decimal(done["refunded_total"]) == Decimal("50.00")


# --------------------------------------------------------------- cash out ----


async def test_no_ceiling_set_means_any_pay_out_goes_through(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx)
    await PosService.record_cash_movement(
        db, tenant_ctx.tenant_id, shift.id, direction="out", reason="pay_out", amount="5000.00"
    )
    assert await _cash_rows(db, shift) == 1


async def test_a_pay_out_over_the_ceiling_is_refused_and_books_nothing(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx, cash_out_ceiling="200.00")
    with pytest.raises(ValidationError, match="manager"):
        await PosService.record_cash_movement(
            db, tenant_ctx.tenant_id, shift.id, direction="out", reason="pay_out", amount="200.01"
        )
    assert await _cash_rows(db, shift) == 0


async def test_a_pay_out_at_the_ceiling_or_approved_goes_through(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx, cash_out_ceiling="200.00")
    await PosService.record_cash_movement(
        db, tenant_ctx.tenant_id, shift.id, direction="out", reason="pay_out", amount="200.00"
    )
    await PosService.record_cash_movement(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        direction="out",
        reason="cash_drop",
        amount="900.00",
        ceiling_override=True,
    )
    assert await _cash_rows(db, shift) == 1  # the pay_out; the drop is a different reason


async def test_money_coming_into_the_drawer_is_never_limited(db, tenant_ctx):
    shift, _ = await _till(db, tenant_ctx, cash_out_ceiling="10.00")
    await PosService.record_cash_movement(
        db, tenant_ctx.tenant_id, shift.id, direction="in", reason="pay_in", amount="9999.00"
    )


# ------------------------------------------------------------ the settings ----


async def test_the_owner_can_set_change_and_remove_a_ceiling(db, tenant_ctx):
    _, profile = await _till(db, tenant_ctx, refund_ceiling="50.00")
    assert profile.refund_ceiling == Decimal("50.00")

    async def change(**kw):
        return await PosProfileService.update(db, tenant_ctx.tenant_id, profile.id, **kw)

    assert (await change(refund_ceiling="75")).refund_ceiling == Decimal("75.00")
    # Leaving the field out keeps it; an explicit None removes the limit.
    assert (await change(name="x")).refund_ceiling == Decimal("75.00")
    assert (await change(refund_ceiling=None)).refund_ceiling is None
    with pytest.raises(ValidationError, match="negative"):
        await change(cash_out_ceiling="-1")
