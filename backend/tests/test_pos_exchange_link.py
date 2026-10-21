"""An exchange's two receipts are tied together by a STORED link, not only by an outbox event.

The NEW sale receipt carries ``exchange_return_receipt_id`` -> its return receipt. An ordinary
sale carries none; the database refuses a link on a return receipt, and a second exchange
claiming the same return receipt.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from tests.test_pos_exchange import (
    _customer,
    _register,
    _sellable_variant,
)


async def _exchanged(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    old = await _sellable_variant(db, tenant_ctx)
    new = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(old.id), "quantity": 1}],
        tenders=[{"method": "cash", "amount": "25.00"}],
    )
    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(old.id), "quantity": 1}],
        new_lines=[{"variant_id": str(new.id), "quantity": 1}],
        restock=True,
    )
    return PosService, pos_session, sold, result


async def test_the_new_sale_receipt_points_at_its_return_receipt(db, tenant_ctx):
    PosService, pos_session, sold, result = await _exchanged(db, tenant_ctx)

    new_detail = await PosService.get_receipt(db, tenant_ctx.tenant_id, result["new_receipt_id"])
    assert new_detail["receipt"]["kind"] == "sale"
    assert new_detail["receipt"]["exchange_return_receipt_id"] == result["return_receipt_id"]

    ret_detail = await PosService.get_receipt(db, tenant_ctx.tenant_id, result["return_receipt_id"])
    assert ret_detail["receipt"]["kind"] == "return"
    assert ret_detail["receipt"]["exchange_return_receipt_id"] is None


async def test_an_ordinary_sale_and_the_original_sale_carry_no_link(db, tenant_ctx):
    PosService, pos_session, sold, result = await _exchanged(db, tenant_ctx)
    original = await PosService.get_receipt(db, tenant_ctx.tenant_id, sold["receipt_id"])
    assert original["receipt"]["exchange_return_receipt_id"] is None


async def test_the_list_exposes_the_link_so_the_log_can_pair_receipts(db, tenant_ctx):
    PosService, pos_session, sold, result = await _exchanged(db, tenant_ctx)
    rows = await PosService.list_receipts(db, tenant_ctx.tenant_id, pos_session.id)
    by_id = {r["id"]: r for r in rows}
    linked = by_id[result["new_receipt_id"]]["exchange_return_receipt_id"]
    assert linked == result["return_receipt_id"]
    assert by_id[sold["receipt_id"]]["exchange_return_receipt_id"] is None


async def test_the_database_refuses_a_link_on_a_return_receipt(db, tenant_ctx):
    from sqlalchemy import text

    PosService, pos_session, sold, result = await _exchanged(db, tenant_ctx)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE pos_receipts SET exchange_return_receipt_id = :o WHERE id = :r"),
                {"o": result["new_receipt_id"], "r": result["return_receipt_id"]},
            )


async def test_one_return_receipt_cannot_belong_to_two_exchanges(db, tenant_ctx):
    from sqlalchemy import text

    PosService, pos_session, sold, result = await _exchanged(db, tenant_ctx)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE pos_receipts SET exchange_return_receipt_id = :ret WHERE id = :orig"),
                {"ret": result["return_receipt_id"], "orig": sold["receipt_id"]},
            )
