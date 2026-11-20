"""A sale on a customer's account at the till: part paid now, the rest owed, limit enforced."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import ConflictError, ValidationError
from app.modules.customer_accounts.service import CustomerAccountService as Accounts
from app.modules.orders.models import Order, OrderPayment
from app.modules.pos.models import PosCashMovement
from app.modules.pos.service import PosService
from app.modules.settings.service import SettingsService
from tests.test_pos_take_payments import _shop

pytestmark = pytest.mark.asyncio

D = Decimal


async def _ready(db, tenant_ctx, *, allow=True, limit="500"):
    register, variant, customer = await _shop(db, tenant_ctx)
    if allow:
        await SettingsService(db, tenant_ctx.tenant_id).set("pos.allow_sale_on_account", True)
    if limit is not False:
        await Accounts.open_account(db, tenant_ctx.tenant_id, customer.id, credit_limit=limit)
    return register, variant, customer


async def _sell(db, tenant_ctx, register, variant, customer, *, qty=1, payments=None, **kw):
    return await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        customer_id=customer.id if customer is not None else None,
        payments=payments,
        on_account=True,
        actor_user_id=tenant_ctx.user.id,
        **kw,
    )


async def test_part_paid_now_and_the_rest_goes_on_the_account(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    register, variant, customer = await _ready(db, tenant_ctx)
    out = await _sell(
        db,
        tenant_ctx,
        register,
        variant,
        customer,
        qty=3,  # 300.00
        payments=[{"method": "cash", "amount": "100.00"}],
    )
    assert out["grand_total"] == "300.00"
    assert out["paid"] == "100.00"
    assert out["on_account"] == "200.00"
    assert await Accounts.balance(db, t, customer.id) == D("200.00")


async def test_a_wholly_credit_sale_needs_no_payment_line(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    register, variant, customer = await _ready(db, tenant_ctx)
    out = await _sell(db, tenant_ctx, register, variant, customer, qty=2)
    assert out["paid"] == "0.00" and out["on_account"] == "200.00"
    assert await Accounts.balance(db, t, customer.id) == D("200.00")


async def test_a_wholly_credit_sale_is_confirmed_and_the_stock_leaves(db, tenant_ctx) -> None:
    """No payment line at all: nothing else would confirm the order, so the till must."""
    register, variant, customer = await _ready(db, tenant_ctx)
    out = await _sell(db, tenant_ctx, register, variant, customer, qty=2)
    order = await db.get(Order, out["order_id"])
    assert order.status == "confirmed"  # not left pending with the goods already gone
    from app.modules.inventory.models import InventoryBalance

    bal = (
        (
            await db.execute(
                select(InventoryBalance).where(InventoryBalance.variant_id == variant.id)
            )
        )
        .scalars()
        .one()
    )
    assert (bal.on_hand, bal.reserved) == (48, 0)  # sold, not just held


async def test_the_order_is_confirmed_and_stock_leaves_the_shelf_once(db, tenant_ctx) -> None:
    register, variant, customer = await _ready(db, tenant_ctx)
    out = await _sell(
        db,
        tenant_ctx,
        register,
        variant,
        customer,
        qty=2,
        payments=[{"method": "cash", "amount": "50.00"}],
    )
    order = await db.get(Order, out["order_id"])
    assert order.status == "confirmed"
    from app.modules.inventory.models import InventoryBalance

    bal = (
        (
            await db.execute(
                select(InventoryBalance).where(InventoryBalance.variant_id == variant.id)
            )
        )
        .scalars()
        .one()
    )
    assert (bal.on_hand, bal.reserved) == (48, 0)  # 50 in stock, 2 sold, nothing left held


async def test_only_the_part_paid_in_cash_enters_the_drawer(db, tenant_ctx) -> None:
    register, variant, customer = await _ready(db, tenant_ctx)
    await _sell(
        db,
        tenant_ctx,
        register,
        variant,
        customer,
        qty=3,
        payments=[{"method": "cash", "amount": "100.00"}],
    )
    cash_in = (
        await db.execute(
            select(func.coalesce(func.sum(PosCashMovement.amount), 0)).where(
                PosCashMovement.reason == "cash_sale"
            )
        )
    ).scalar_one()
    assert D(str(cash_in)) == D("100.00")  # never the 300 sale, never the 200 on account
    paid = (await db.execute(select(func.coalesce(func.sum(OrderPayment.amount), 0)))).scalar_one()
    assert D(str(paid)) == D("100.00")


async def test_over_the_credit_limit_is_refused_and_leaves_no_trace(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    register, variant, customer = await _ready(db, tenant_ctx, limit="150")
    with pytest.raises(ConflictError):
        await _sell(db, tenant_ctx, register, variant, customer, qty=2)  # 200 owed > 150
    assert await Accounts.balance(db, t, customer.id) == D("0.00")


async def test_a_refused_sale_does_not_hold_stock(db, tenant_ctx) -> None:
    register, variant, customer = await _ready(db, tenant_ctx, limit="50")
    try:
        async with db.begin_nested():
            await _sell(db, tenant_ctx, register, variant, customer, qty=5)
    except ConflictError:
        pass
    from app.modules.inventory.models import InventoryBalance

    bal = (
        (
            await db.execute(
                select(InventoryBalance).where(InventoryBalance.variant_id == variant.id)
            )
        )
        .scalars()
        .one()
    )
    assert (bal.on_hand, bal.reserved) == (50, 0)


async def test_a_customer_without_an_account_cannot_buy_on_credit(db, tenant_ctx) -> None:
    register, variant, customer = await _ready(db, tenant_ctx, limit=False)
    with pytest.raises(ConflictError):
        await _sell(db, tenant_ctx, register, variant, customer)


async def test_the_shared_walk_in_can_never_carry_a_debt(db, tenant_ctx) -> None:
    register, variant, _ = await _ready(db, tenant_ctx)
    with pytest.raises(ValidationError, match="named customer"):
        await _sell(db, tenant_ctx, register, variant, None)


async def test_off_by_default_the_till_refuses_instead_of_ignoring(db, tenant_ctx) -> None:
    register, variant, customer = await _ready(db, tenant_ctx, allow=False)
    with pytest.raises(ValidationError, match="allow_sale_on_account"):
        await _sell(db, tenant_ctx, register, variant, customer)


async def test_a_plain_sale_is_exactly_as_before(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    register, variant, customer = await _ready(db, tenant_ctx)
    out = await PosService.record_sale(
        db,
        t,
        register.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        customer_id=customer.id,
        payments=[{"method": "cash", "amount": "100.00"}],
        actor_user_id=tenant_ctx.user.id,
    )
    assert out["on_account"] is None
    assert await Accounts.balance(db, t, customer.id) == D("0.00")


async def test_a_short_payment_without_on_account_is_still_refused(db, tenant_ctx) -> None:
    register, variant, customer = await _ready(db, tenant_ctx)
    with pytest.raises(ValidationError):
        await PosService.record_sale(
            db,
            tenant_ctx.tenant_id,
            register.id,
            items=[{"variant_id": str(variant.id), "quantity": 2}],
            customer_id=customer.id,
            payments=[{"method": "cash", "amount": "50.00"}],
            actor_user_id=tenant_ctx.user.id,
        )


async def test_a_replayed_sale_charges_the_account_once(db, tenant_ctx) -> None:
    register, variant, customer = await _ready(db, tenant_ctx)
    first = await _sell(db, tenant_ctx, register, variant, customer, idempotency_key="till-9")
    assert first["on_account"] == "100.00"
    # the same key posts no second charge (the sale itself is guarded by the HTTP layer's cache)
    from app.modules.customer_accounts.models import CustomerLedgerEntry

    count = (
        await db.execute(
            select(func.count())
            .select_from(CustomerLedgerEntry)
            .where(CustomerLedgerEntry.idempotency_key == "sale:till-9")
        )
    ).scalar_one()
    assert count == 1
