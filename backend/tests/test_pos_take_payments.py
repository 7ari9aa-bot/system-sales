"""A till that takes payments: tender, change, drawer ledger, counted close.

``pos.take_payments`` is OFF by default and every older test relies on that: a sale records
the goods and no money. These tests turn it on and prove the money side, then prove the
switch-off behaviour is refused loudly instead of ignored.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import ConflictError, ValidationError
from app.applications.apparel.modules.orders.models import OrderPayment
from app.applications.apparel.modules.pos.models import PosCashMovement, PosReceipt
from app.applications.apparel.modules.pos.profiles import PosProfileService
from app.applications.apparel.modules.pos.service import PosService
from app.platform.settings.service import SettingsService
from tests._pos_helpers import start_day, till

pytestmark = pytest.mark.asyncio

D = Decimal


async def _shop(db, tenant_ctx, *, take_payments=True, methods=("cash", "card")):
    shift, variant, customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
    await PosProfileService.update(
        db,
        tenant_ctx.tenant_id,
        shift.profile_id,
        allowed_payment_methods=list(methods),
    )
    if take_payments:
        await SettingsService(db, tenant_ctx.tenant_id).set("pos.take_payments", True)
    register = await PosService._get_register(db, tenant_ctx.tenant_id, shift.register_id)
    # The trading day takes its payment methods from the register's profile, so the register is
    # bound to the profile before the day starts.
    register.profile_id = shift.profile_id
    await db.flush()
    await start_day(db, tenant_ctx, shift.register_id, opening="200.00")
    return register, variant, customer


async def _sell(db, tenant_ctx, register, variant, customer, payments, qty=1):
    return await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
        payments=payments,
    )


async def _today(db, tenant_ctx, register):
    return await PosService._today_session(db, tenant_ctx.tenant_id, register)


async def test_cash_sale_gives_change_and_books_the_drawer(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    out = await _sell(
        db,
        tenant_ctx,
        register,
        variant,
        customer,
        [{"method": "cash", "amount": "100.00", "tendered": "150.00"}],
    )
    assert out["paid"] == "100.00"
    assert out["change"] == "50.00"
    receipt = (
        await db.execute(select(PosReceipt).where(PosReceipt.id == out["receipt_id"]))
    ).scalar_one()
    assert receipt.tendered_amount == D("150.00")
    assert receipt.change_amount == D("50.00")
    rows = (
        await db.execute(
            select(PosCashMovement.direction, PosCashMovement.reason, PosCashMovement.amount)
        )
    ).all()
    assert [(r[0], r[1], D(str(r[2]))) for r in rows] == [("in", "cash_sale", D("100.00"))]


async def test_split_cash_and_card_books_only_the_cash(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.reference_required_methods", ["card"])
    out = await _sell(
        db,
        tenant_ctx,
        register,
        variant,
        customer,
        [
            {"method": "cash", "amount": "40.00"},
            {"method": "card", "amount": "60.00", "reference": "RRN123"},
        ],
    )
    assert out["paid"] == "100.00"
    assert out["change"] == "0.00"
    methods = (await db.execute(select(OrderPayment.method, OrderPayment.amount))).all()
    assert sorted((m, D(str(a))) for m, a in methods) == [
        ("card", D("60.00")),
        ("cash", D("40.00")),
    ]
    moved = (await db.execute(select(func.sum(PosCashMovement.amount)))).scalar_one()
    assert D(str(moved)) == D("40.00")


async def test_a_method_the_till_does_not_accept_is_refused(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx, methods=("cash",))
    with pytest.raises(ValidationError, match="not enabled"):
        await _sell(
            db,
            tenant_ctx,
            register,
            variant,
            customer,
            [{"method": "card", "amount": "100.00", "reference": "X"}],
        )
    assert (await db.execute(select(func.count()).select_from(OrderPayment))).scalar_one() == 0


async def test_a_card_without_its_reference_is_refused(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    with pytest.raises(ValidationError, match="reference"):
        await _sell(
            db,
            tenant_ctx,
            register,
            variant,
            customer,
            [{"method": "card", "amount": "100.00"}],
        )


async def test_a_short_payment_is_refused_and_leaves_no_trace(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    with pytest.raises(ValidationError, match="do not cover"):
        await _sell(
            db, tenant_ctx, register, variant, customer, [{"method": "cash", "amount": "40.00"}]
        )


async def test_a_till_that_takes_payments_needs_payment_lines(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    with pytest.raises(ValidationError, match="at least one payment"):
        await _sell(db, tenant_ctx, register, variant, customer, None)


async def test_payments_are_refused_where_the_setting_is_off(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx, take_payments=False)
    with pytest.raises(ValidationError, match="does not record payments"):
        await _sell(
            db, tenant_ctx, register, variant, customer, [{"method": "cash", "amount": "100.00"}]
        )
    assert (await db.execute(select(func.count()).select_from(OrderPayment))).scalar_one() == 0


async def test_close_counts_the_drawer_and_records_the_variance(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    await _sell(
        db, tenant_ctx, register, variant, customer, [{"method": "cash", "amount": "100.00"}]
    )
    shift = await _today(db, tenant_ctx, register)
    summary = await PosService.drawer_summary(db, tenant_ctx.tenant_id, shift.id)
    assert summary["expected_cash"] == "300.00"  # 200 float + 100 cash sale
    assert summary["by_method"] == {"cash": "100.00"}

    closed = await PosService.close_session(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        closed_by=tenant_ctx.user.id,
        counted_cash="295.00",
        variance_reason="باقي ناقص",  # a gap now needs its reason (pos.variance_reason_required)
    )
    assert closed.status == "CLOSED"
    assert closed.counted_cash == D("295.00")
    assert closed.expected_cash == D("300.00")
    assert closed.variance == D("-5.00")


async def test_close_without_a_count_is_refused_when_payments_are_on(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx)
    shift = await _today(db, tenant_ctx, register)
    with pytest.raises(ValidationError, match="counted_cash is required"):
        await PosService.close_session(
            db, tenant_ctx.tenant_id, shift.id, closed_by=tenant_ctx.user.id
        )


async def test_a_count_is_refused_where_the_till_does_not_count(db, tenant_ctx) -> None:
    register, _variant, _customer = await _shop(db, tenant_ctx, take_payments=False)
    shift = await _today(db, tenant_ctx, register)
    with pytest.raises(ValidationError, match="does not count a drawer"):
        await PosService.close_session(
            db, tenant_ctx.tenant_id, shift.id, closed_by=tenant_ctx.user.id, counted_cash="10"
        )


async def test_a_shop_that_never_turned_it_on_closes_as_before(db, tenant_ctx) -> None:
    register, variant, customer = await _shop(db, tenant_ctx, take_payments=False)
    out = await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
    )
    assert out["paid"] is None and out["change"] is None
    shift = await _today(db, tenant_ctx, register)
    closed = await PosService.close_session(
        db, tenant_ctx.tenant_id, shift.id, closed_by=tenant_ctx.user.id
    )
    assert closed.counted_cash is None and closed.variance is None
    assert closed.expected_cash == D("300.00")  # opening 200 + invoice 100: the book balance
    with pytest.raises(ConflictError):
        await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
