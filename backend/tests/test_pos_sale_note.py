"""`POST /pos/registers/{id}/sales` accepts an optional free-text note, kept on the invoice.

The note is a remark ("gift", "deliver tomorrow"), not money: it changes nothing about the total
or the stock. Blank means none, and it is bounded so a client cannot stuff the order row.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.orders.models import Order
from app.modules.pos.service import PosService
from tests._pos_helpers import ctx_for, till, start_day
from tests.test_pos_sale_http import _post

pytestmark = pytest.mark.asyncio


async def _shop(db, tenant_ctx):
    shift, variant, _customer = await till(db, tenant_ctx)
    await PosService.close_session(db, tenant_ctx.tenant_id, shift.id, counted_cash="0.00")
    await start_day(db, tenant_ctx, shift.register_id)
    return shift.register_id, variant


async def _sell(db, tenant_ctx, **extra):
    register_id, variant = await _shop(db, tenant_ctx)
    ctx = await ctx_for(db, tenant_ctx, "owner")
    return await _post(
        ctx,
        f"/api/v1/pos/registers/{register_id}/sales",
        {"items": [{"variant_id": str(variant.id), "quantity": 1}], **extra},
    )


async def _note_of(db, order_id):
    extra = (await db.execute(select(Order.extra).where(Order.id == order_id))).scalar_one()
    return (extra or {}).get("note")


async def test_a_note_is_kept_on_the_invoice(db, tenant_ctx) -> None:
    r = await _sell(db, tenant_ctx, note="  هدية، لف الهدية  ")

    assert r.status_code == 201, r.text
    assert await _note_of(db, r.json()["order_id"]) == "هدية، لف الهدية"


async def test_no_note_or_a_blank_one_means_none(db, tenant_ctx) -> None:
    plain = await _sell(db, tenant_ctx)
    blank = await _sell(db, tenant_ctx, note="   ")

    assert plain.status_code == 201 and blank.status_code == 201
    assert await _note_of(db, plain.json()["order_id"]) is None
    assert await _note_of(db, blank.json()["order_id"]) is None


async def test_a_note_does_not_change_the_total(db, tenant_ctx) -> None:
    with_note = await _sell(db, tenant_ctx, note="x")
    without = await _sell(db, tenant_ctx)

    assert with_note.json()["grand_total"] == without.json()["grand_total"]


async def test_an_oversized_note_is_refused(db, tenant_ctx) -> None:
    r = await _sell(db, tenant_ctx, note="ن" * 513)

    assert r.status_code == 422


async def test_the_receipt_carries_the_note(db, tenant_ctx) -> None:
    from tests.test_pos_sale_http import _post  # noqa: F401  (same app wiring as the sale)

    sold = await _sell(db, tenant_ctx, note="التوصيل بكرة")
    assert sold.status_code == 201, sold.text

    receipt = await PosService.get_receipt(db, tenant_ctx.tenant_id, sold.json()["receipt_id"])

    assert receipt["order"]["note"] == "التوصيل بكرة"
