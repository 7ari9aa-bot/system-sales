"""Find an original sale on ANY shift, and still return it on the current one.

The refund picker only listed the open shift's receipts, so a customer coming back the next day
with yesterday's receipt could not be served from the screen even though the backend accepts the
return. Search is across shifts; the return state comes from the order's whole history; and the
money moves on the shift that is open now.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.errors import ValidationError
from app.modules.pos.service import PosService
from tests.test_pos_returns import _customer, _register, _sellable_variant

pytestmark = pytest.mark.asyncio


async def _sale_on_a_closed_shift(db, tenant_ctx, *, qty=3):
    """Sell on shift 1, close it, open shift 2 on the same register."""
    uid = tenant_ctx.user.id
    register = await _register(db, tenant_ctx)
    first = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opened_by=uid, cashier_user_id=uid
    )
    variant = await _sellable_variant(db, tenant_ctx, price="25.00", stock=20)
    customer = await _customer(db, tenant_ctx)
    paid = str(Decimal("25.00") * qty)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        first.id,
        customer_id=customer.id,
        actor_user_id=uid,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        tenders=[{"method": "cash", "amount": paid}],
    )
    await PosService.close_session(
        db, tenant_ctx.tenant_id, first.id, counted_cash=paid, closed_by=uid
    )
    second = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opened_by=uid, cashier_user_id=uid
    )
    return first, second, variant, sold


async def _number(db, tenant_ctx, session_id):
    rows = await PosService.list_receipts(db, tenant_ctx.tenant_id, session_id)
    return next(r["number"] for r in rows if r["kind"] == "sale")


async def test_the_open_shift_list_misses_yesterdays_receipt_but_search_finds_it(db, tenant_ctx):
    first, second, _v, sold = await _sale_on_a_closed_shift(db, tenant_ctx)
    number = await _number(db, tenant_ctx, first.id)

    assert await PosService.list_receipts(db, tenant_ctx.tenant_id, second.id) == []
    found = await PosService.search_receipts(db, tenant_ctx.tenant_id, q=number)
    assert [r["order_id"] for r in found] == [sold["order_id"]]
    assert found[0]["session_id"] == first.id  # it says which shift took the sale


async def test_a_return_from_the_old_receipt_settles_on_the_current_shift(db, tenant_ctx):
    uid = tenant_ctx.user.id
    first, second, variant, sold = await _sale_on_a_closed_shift(db, tenant_ctx)
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        second.id,
        order_id=sold["order_id"],
        actor_user_id=uid,
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    now = await PosService.list_receipts(db, tenant_ctx.tenant_id, second.id)
    assert [r["kind"] for r in now] == ["return"]
    then = await PosService.list_receipts(db, tenant_ctx.tenant_id, first.id)
    assert [r["kind"] for r in then] == ["sale"]


async def test_returned_units_count_returns_made_on_other_shifts(db, tenant_ctx):
    uid = tenant_ctx.user.id
    first, second, variant, sold = await _sale_on_a_closed_shift(db, tenant_ctx, qty=3)
    number = await _number(db, tenant_ctx, first.id)
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        second.id,
        order_id=sold["order_id"],
        actor_user_id=uid,
        lines=[{"variant_id": str(variant.id), "quantity": 2}],
    )
    # Searching sees the 2 units that came back on a shift other than the one that sold them.
    row = (await PosService.search_receipts(db, tenant_ctx.tenant_id, q=number))[0]
    assert row["returned_units"] == 2
    assert Decimal(row["refunded_total"]) == Decimal("50.00")


async def test_search_returns_sales_only_never_return_receipts(db, tenant_ctx):
    uid = tenant_ctx.user.id
    _first, second, variant, sold = await _sale_on_a_closed_shift(db, tenant_ctx)
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        second.id,
        order_id=sold["order_id"],
        actor_user_id=uid,
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    found = await PosService.search_receipts(db, tenant_ctx.tenant_id, q="POS-")
    assert found
    assert {r["kind"] for r in found} == {"sale"}


async def test_search_never_crosses_tenants(db, tenant_ctx):
    first, _second, _v, _sold = await _sale_on_a_closed_shift(db, tenant_ctx)
    number = await _number(db, tenant_ctx, first.id)
    assert await PosService.search_receipts(db, uuid.uuid4(), q=number) == []


async def test_percent_and_underscore_are_plain_text_not_wildcards(db, tenant_ctx):
    await _sale_on_a_closed_shift(db, tenant_ctx)
    assert await PosService.search_receipts(db, tenant_ctx.tenant_id, q="%%%") == []
    assert await PosService.search_receipts(db, tenant_ctx.tenant_id, q="___") == []


async def test_search_needs_three_characters_and_a_sane_limit(db, tenant_ctx):
    with pytest.raises(ValidationError, match="3 characters"):
        await PosService.search_receipts(db, tenant_ctx.tenant_id, q="ab")
    with pytest.raises(ValidationError, match="limit"):
        await PosService.search_receipts(db, tenant_ctx.tenant_id, q="abc", limit=500)
