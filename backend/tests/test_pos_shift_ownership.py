"""A drawer belongs to the cashier who holds it: nobody else rings, refunds or closes on it.

The open path was already guarded (one open drawer per user, the user must operate the profile), but
every OTHER operation took a session id and trusted it. Cashier A could ring a sale into cashier B's
every OTHER operation took a session id and trusted it. Cashier A could ring a sale into B's
or holds pos:override (a manager closing for an absent cashier).

Two cases are deliberately left alone:
  * a shift with NO holder (legacy, cashier_user_id IS NULL) behaves exactly as before;
  * an unknown actor on a shift that HAS a holder is refused: HTTP always supplies the user, so a
    missing one means an internal caller, and "unknown" must not be a way around the check.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.security import hash_password
from app.modules.errors import PermissionDeniedError
from app.modules.pos.service import PosService
from tests.test_pos_returns import _customer, _register, _sellable_variant

pytestmark = pytest.mark.asyncio


async def _user(db, name):
    from app.modules.identity.models import User

    user = User(
        email=f"{name}-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("secret-password"),
        full_name=name,
    )
    db.add(user)
    await db.flush()
    return user


async def _owned_shift(db, tenant_ctx):
    """B's open drawer, with a sold order on it, plus a stranger A."""
    holder = await _user(db, "holder")
    stranger = await _user(db, "stranger")
    register = await _register(db, tenant_ctx)
    shift = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opened_by=holder.id, cashier_user_id=holder.id
    )
    variant = await _sellable_variant(db, tenant_ctx, price="50.00", stock=20)
    customer = await _customer(db, tenant_ctx)
    return shift, holder, stranger, variant, customer


def _items(variant):
    return [{"variant_id": str(variant.id), "quantity": 1}]


async def _sell(db, tenant_ctx, shift, variant, customer, **kw):
    return await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        customer_id=customer.id,
        items=_items(variant),
        method="cash",
        **kw,
    )


async def test_the_holder_can_sell_on_their_own_drawer(db, tenant_ctx):
    shift, holder, _s, variant, customer = await _owned_shift(db, tenant_ctx)
    sold = await _sell(db, tenant_ctx, shift, variant, customer, actor_user_id=holder.id)
    assert Decimal(sold["grand_total"]) == Decimal("50.00")


async def test_a_stranger_cannot_sell_on_someone_elses_drawer(db, tenant_ctx):
    shift, _h, stranger, variant, customer = await _owned_shift(db, tenant_ctx)
    with pytest.raises(PermissionDeniedError, match="drawer"):
        await _sell(db, tenant_ctx, shift, variant, customer, actor_user_id=stranger.id)


async def test_a_manager_may_work_a_drawer_that_is_not_theirs(db, tenant_ctx):
    shift, _h, stranger, variant, customer = await _owned_shift(db, tenant_ctx)
    sold = await _sell(
        db, tenant_ctx, shift, variant, customer,
        actor_user_id=stranger.id, shift_override=True,
    )  # fmt: skip
    assert Decimal(sold["grand_total"]) == Decimal("50.00")


async def test_an_unknown_actor_cannot_use_a_drawer_that_has_a_holder(db, tenant_ctx):
    shift, _h, _s, variant, customer = await _owned_shift(db, tenant_ctx)
    with pytest.raises(PermissionDeniedError, match="drawer"):
        await _sell(db, tenant_ctx, shift, variant, customer, actor_user_id=None)


async def test_a_drawer_with_no_holder_behaves_as_before(db, tenant_ctx):
    register = await _register(db, tenant_ctx)
    shift = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    assert shift.cashier_user_id is None
    variant = await _sellable_variant(db, tenant_ctx, price="50.00", stock=20)
    customer = await _customer(db, tenant_ctx)
    anyone = await _user(db, "anyone")
    sold = await _sell(db, tenant_ctx, shift, variant, customer, actor_user_id=anyone.id)
    assert Decimal(sold["grand_total"]) == Decimal("50.00")
    again = await _sell(db, tenant_ctx, shift, variant, customer, actor_user_id=None)
    assert Decimal(again["grand_total"]) == Decimal("50.00")


async def test_a_stranger_cannot_move_cash_in_or_out_of_it(db, tenant_ctx):
    shift, _h, stranger, _v, _c = await _owned_shift(db, tenant_ctx)
    with pytest.raises(PermissionDeniedError, match="drawer"):
        await PosService.record_cash_movement(
            db, tenant_ctx.tenant_id, shift.id,
            direction="out", amount="10.00", reason="pay_out", created_by=stranger.id,
        )  # fmt: skip


async def test_a_stranger_cannot_close_it(db, tenant_ctx):
    shift, _h, stranger, _v, _c = await _owned_shift(db, tenant_ctx)
    with pytest.raises(PermissionDeniedError, match="drawer"):
        await PosService.close_session(
            db, tenant_ctx.tenant_id, shift.id, counted_cash="0.00", closed_by=stranger.id
        )


async def test_a_manager_can_close_an_absent_cashiers_drawer(db, tenant_ctx):
    shift, _h, stranger, _v, _c = await _owned_shift(db, tenant_ctx)
    closed = await PosService.close_session(
        db, tenant_ctx.tenant_id, shift.id,
        counted_cash="0.00", closed_by=stranger.id, shift_override=True,
    )  # fmt: skip
    assert closed.status == "CLOSED"


async def test_a_stranger_cannot_refund_return_or_exchange_on_it(db, tenant_ctx):
    shift, holder, stranger, variant, customer = await _owned_shift(db, tenant_ctx)
    sold = await _sell(db, tenant_ctx, shift, variant, customer, actor_user_id=holder.id)
    order_id = sold["order_id"]
    with pytest.raises(PermissionDeniedError, match="drawer"):
        await PosService.return_sale(
            db, tenant_ctx.tenant_id, shift.id, order_id=order_id,
            lines=_items(variant), actor_user_id=stranger.id,
        )  # fmt: skip
    with pytest.raises(PermissionDeniedError, match="drawer"):
        await PosService.refund(
            db, tenant_ctx.tenant_id, shift.id, order_id=order_id,
            amount="10.00", actor_user_id=stranger.id,
        )  # fmt: skip
    with pytest.raises(PermissionDeniedError, match="drawer"):
        await PosService.exchange(
            db, tenant_ctx.tenant_id, shift.id, order_id=order_id,
            return_lines=_items(variant), new_lines=_items(variant),
            actor_user_id=stranger.id,
        )  # fmt: skip


# --------------------------------------------------- cash expenses draw on the same drawer -----


async def _category(db, tenant_ctx):
    from tests.test_expenses import _category as make

    return await make(db, tenant_ctx)


async def _expense(db, tenant_ctx, shift, cat, *, by, **kw):
    from app.modules.expenses.service import ExpenseService

    return await ExpenseService.create(
        db,
        tenant_ctx.tenant_id,
        category_id=cat.id,
        description="أكياس",
        amount="20.00",
        payment_method="cash",
        session_id=shift.id,
        created_by=by,
        **kw,
    )


async def test_a_stranger_cannot_book_a_cash_expense_against_it(db, tenant_ctx):
    shift, _h, stranger, _v, _c = await _owned_shift(db, tenant_ctx)
    cat = await _category(db, tenant_ctx)
    with pytest.raises(PermissionDeniedError, match="drawer"):
        await _expense(db, tenant_ctx, shift, cat, by=stranger.id)


async def test_the_holder_can_book_and_a_manager_can_void_it_on_their_drawer(db, tenant_ctx):
    from app.modules.expenses.service import ExpenseService

    shift, holder, manager, _v, _c = await _owned_shift(db, tenant_ctx)
    cat = await _category(db, tenant_ctx)
    exp = await _expense(db, tenant_ctx, shift, cat, by=holder.id)
    # a stranger without the override cannot void it (that would put cash back in the drawer)
    with pytest.raises(PermissionDeniedError, match="drawer"):
        await ExpenseService.void(
            db, tenant_ctx.tenant_id, exp.id, reason="خطأ", voided_by=manager.id
        )
    voided = await ExpenseService.void(
        db, tenant_ctx.tenant_id, exp.id, reason="خطأ", voided_by=manager.id, shift_override=True
    )
    assert voided.status == "voided"


# --------------------------- the routes, a stranger at the till, with REAL role permissions -----


async def _stranger_ctx(db, tenant_ctx, stranger, role_code):
    from tests._pos_helpers import ctx_for as _ctx_for

    ctx = await _ctx_for(db, tenant_ctx, role_code)
    ctx.user = stranger
    return ctx


async def _grant(ctx, method="POST", path="/pos/test"):
    """What the real dependency makes of this caller (a manager is a grant, a cashier is not)."""
    from app.modules.pos.override import resolve_override

    return await resolve_override(ctx)


async def test_on_the_routes_a_cashier_is_refused_and_a_manager_is_not(db, tenant_ctx):
    from app.modules.pos.router import (
        CashMovementRequest,
        CloseSessionRequest,
        SellRequest,
        close_session,
        record_cash_movement,
        sell,
    )

    shift, _h, stranger, variant, customer = await _owned_shift(db, tenant_ctx)
    staff = await _stranger_ctx(db, tenant_ctx, stranger, "staff")
    manager = await _stranger_ctx(db, tenant_ctx, stranger, "manager")
    sale = SellRequest(
        items=_items(variant), customer_id=customer.id, method="cash", amount="50.00"
    )
    move = CashMovementRequest(direction="out", reason="pay_out", amount="5.00")

    with pytest.raises(PermissionDeniedError):
        await sell(shift.id, sale, staff, await _grant(staff))
    with pytest.raises(PermissionDeniedError):
        await record_cash_movement(shift.id, move, staff, await _grant(staff))
    with pytest.raises(PermissionDeniedError):
        await close_session(
            shift.id, CloseSessionRequest(counted_cash="0.00"), staff, await _grant(staff)
        )

    assert (await sell(shift.id, sale, manager, await _grant(manager)))["grand_total"] == "50.00"
    await record_cash_movement(shift.id, move, manager, await _grant(manager))
    closed = await close_session(
        shift.id, CloseSessionRequest(counted_cash="45.00"), manager, await _grant(manager)
    )
    assert closed["status"] == "CLOSED"
