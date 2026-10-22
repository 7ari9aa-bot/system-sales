"""A till scoped to some categories must refuse the others on EVERY path that takes variant ids.

``scan`` and ``browse`` already hid what a scoped terminal does not carry. ``quote``, ``sell`` and
the new half of an exchange took variant ids straight from the wire and priced them without
asking, so a client that skipped the grid could sell anything. These tests send the id directly,
the way such a client would.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.modules.errors import ValidationError
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from tests.test_pos_phase6 import _customer, _register, _sellable_variant, _warehouse

pytestmark = pytest.mark.asyncio

OUTSIDE = "outside this terminal's catalog"


async def _scoped_till(db, tenant_ctx):
    """A till serving ONE category: a variant inside it, one outside, one with no category."""
    from app.modules.catalog.service import CatalogService

    wh = await _warehouse(db, tenant_ctx)
    inside = await CatalogService.create_category(db, tenant_ctx.tenant_id, name="in")
    other = await CatalogService.create_category(db, tenant_ctx.tenant_id, name="out")
    v_in = await _sellable_variant(db, tenant_ctx, category_id=inside.id, price="50.00")
    v_out = await _sellable_variant(db, tenant_ctx, category_id=other.id, price="50.00")
    v_none = await _sellable_variant(db, tenant_ctx, category_id=None, price="50.00")
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="scoped",
        code=f"P{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        item_group_ids=[str(inside.id)],
        allowed_payment_methods=["cash"],
    )
    register = await _register(db, tenant_ctx)
    shift = await PosService.open_session(
        db,
        tenant_ctx.tenant_id,
        register.id,
        profile_id=profile.id,
        opened_by=tenant_ctx.user.id,
        cashier_user_id=tenant_ctx.user.id,
    )
    return shift, v_in, v_out, v_none


def _line(variant, quantity=1):
    return {"variant_id": str(variant.id), "quantity": quantity}


async def _orders(db, tenant_ctx):
    return (
        await db.execute(
            sa.text("SELECT count(*) FROM orders WHERE tenant_id = :t"),
            {"t": tenant_ctx.tenant_id},
        )
    ).scalar_one()


# ----------------------------------------------------------------------------- quote --


async def test_quote_refuses_a_variant_outside_the_categories(db, tenant_ctx):
    shift, _v_in, v_out, _none = await _scoped_till(db, tenant_ctx)
    with pytest.raises(ValidationError, match=OUTSIDE) as exc:
        await PosService.quote(db, tenant_ctx.tenant_id, shift.id, items=[_line(v_out)])
    assert str(v_out.id) in str(exc.value)  # the cashier is told WHICH line


async def test_quote_refuses_a_variant_with_no_category_like_scan_does(db, tenant_ctx):
    shift, _v_in, _out, v_none = await _scoped_till(db, tenant_ctx)
    with pytest.raises(ValidationError, match=OUTSIDE):
        await PosService.quote(db, tenant_ctx.tenant_id, shift.id, items=[_line(v_none)])


async def test_one_bad_line_in_a_mixed_cart_refuses_the_whole_quote(db, tenant_ctx):
    shift, v_in, v_out, _none = await _scoped_till(db, tenant_ctx)
    with pytest.raises(ValidationError, match=OUTSIDE):
        await PosService.quote(
            db, tenant_ctx.tenant_id, shift.id, items=[_line(v_in), _line(v_out, 2)]
        )


async def test_quote_still_prices_what_the_till_does_serve(db, tenant_ctx):
    shift, v_in, _out, _none = await _scoped_till(db, tenant_ctx)
    out = await PosService.quote(db, tenant_ctx.tenant_id, shift.id, items=[_line(v_in, 2)])
    assert out["grand_total"] == "100.00"


# ------------------------------------------------------------------------------ sell --


async def test_sell_refuses_a_variant_outside_the_categories_and_writes_nothing(db, tenant_ctx):
    shift, _in, v_out, _none = await _scoped_till(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    before = await _orders(db, tenant_ctx)
    with pytest.raises(ValidationError, match=OUTSIDE):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            customer_id=customer.id,
            actor_user_id=tenant_ctx.user.id,
            items=[_line(v_out)],
            tenders=[{"method": "cash", "amount": "50.00"}],
        )
    assert await _orders(db, tenant_ctx) == before


async def test_sell_refuses_a_variant_with_no_category(db, tenant_ctx):
    shift, _in, _out, v_none = await _scoped_till(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    with pytest.raises(ValidationError, match=OUTSIDE):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            customer_id=customer.id,
            actor_user_id=tenant_ctx.user.id,
            items=[_line(v_none)],
            tenders=[{"method": "cash", "amount": "50.00"}],
        )


async def test_a_manager_override_does_not_open_the_catalog(db, tenant_ctx):
    """pos:override lifts the drawer lock. It is not a catalog key."""
    shift, _in, v_out, _none = await _scoped_till(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    with pytest.raises(ValidationError, match=OUTSIDE):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            customer_id=customer.id,
            actor_user_id=tenant_ctx.user.id,
            items=[_line(v_out)],
            tenders=[{"method": "cash", "amount": "50.00"}],
            shift_override=True,
        )


async def test_sell_still_works_for_a_variant_the_till_serves(db, tenant_ctx):
    shift, v_in, _out, _none = await _scoped_till(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    out = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
        items=[_line(v_in)],
        tenders=[{"method": "cash", "amount": "50.00"}],
    )
    assert out["grand_total"] == "50.00"


async def test_a_held_cart_cannot_smuggle_a_variant_past_the_scope(db, tenant_ctx):
    """Resuming a parked cart replaces ``items`` inside sell, so the check must run after that."""
    shift, v_in, v_out, _none = await _scoped_till(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    # Park a cart while the till still served both, by widening then narrowing the scope.
    held = await PosService.hold_cart(
        db, tenant_ctx.tenant_id, shift.id, items=[_line(v_in)], customer_id=customer.id
    )
    await db.execute(
        sa.text("UPDATE pos_held_carts SET items = CAST(:i AS jsonb) WHERE id = :h"),
        {"i": f'[{{"variant_id": "{v_out.id}", "quantity": 1}}]', "h": held.id},
    )
    await db.refresh(held)  # the ORM still holds the cart it parked; read what the row says now
    with pytest.raises(ValidationError, match=OUTSIDE):
        await PosService.sell(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            held_cart_id=held.id,
            actor_user_id=tenant_ctx.user.id,
            tenders=[{"method": "cash", "amount": "50.00"}],
        )


# -------------------------------------------------------------------------- exchange --


async def test_an_exchange_cannot_take_a_variant_outside_the_categories(db, tenant_ctx):
    shift, v_in, v_out, _none = await _scoped_till(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
        items=[_line(v_in)],
        tenders=[{"method": "cash", "amount": "50.00"}],
    )
    with pytest.raises(ValidationError, match=OUTSIDE):
        await PosService.exchange(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            actor_user_id=tenant_ctx.user.id,
            order_id=sold["order_id"],
            return_lines=[_line(v_in)],
            new_lines=[_line(v_out)],
        )


# ---------------------------------------------------------------------- unscoped till --


async def test_an_unscoped_till_serves_everything_as_before(db, tenant_ctx):
    """No item_group_ids means no restriction: the new check must not turn into a default deny."""
    register = await _register(db, tenant_ctx)
    shift = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    v_none = await _sellable_variant(db, tenant_ctx, category_id=None, price="50.00")
    out = await PosService.quote(db, tenant_ctx.tenant_id, shift.id, items=[_line(v_none)])
    assert out["grand_total"] == "50.00"
