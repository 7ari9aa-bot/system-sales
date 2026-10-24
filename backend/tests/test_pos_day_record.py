"""The close is a RECORD of the day, never a count: opening balance + invoices - returns.

The user's own example: the drawer opens with 500, the day sells 20 000 and takes back 1 000,
so the closing balance is 19 500. Nothing is counted, no payment, drawer movement or refund is
written, and the report lists the return and exchange invoices.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.orders.models import OrderPayment, Refund
from app.modules.pos.models import PosCashMovement, PosSessionReconciliation
from app.modules.pos.service import PosService
from tests.test_pos_returns import _register, _sellable_variant

pytestmark = pytest.mark.asyncio


async def _day(db, tenant_ctx, opening="500.00"):
    register = await _register(db, tenant_ctx)
    shift = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opening_float=opening
    )
    return shift


async def _count(db, model, tenant_id) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
        )
    ).scalar_one()


async def test_the_users_example_opening_500_sales_20000_return_1000(db, tenant_ctx):
    shift = await _day(db, tenant_ctx)
    variant = await _sellable_variant(db, tenant_ctx, price="1000.00", stock=50)
    first = None
    for _ in range(20):
        sale = await PosService.record_sale(
            db,
            tenant_ctx.tenant_id,
            shift.register_id,
            items=[{"variant_id": variant.id, "quantity": 1}],
        )
        first = first or sale
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=first["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        restock=True,
    )

    report = await PosService.session_report(db, tenant_ctx.tenant_id, shift.id)
    assert report["opening_balance"] == "500.00"
    assert report["sales"] == {"invoice_count": 20, "total": "20000.00"}
    assert report["returns"]["return_count"] == 1
    assert report["returns"]["total"] == "1000.00"
    assert report["net_sales"] == "19000.00"
    assert report["closing_balance"] == "19500.00"
    # each return invoice is listed with its own summary
    (doc,) = report["returns"]["documents"]
    assert doc["total"] == "1000.00" and doc["units"] == 1 and doc["receipt_number"]

    closed = await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)
    assert closed.expected_cash == Decimal("19500.00")
    assert closed.counted_cash is None and closed.variance is None
    again = await PosService.session_report(db, tenant_ctx.tenant_id, shift.id)
    assert again["closing_balance"] == "19500.00"  # same figure once closed


async def test_an_exchange_is_listed_on_its_own_with_its_value_difference(db, tenant_ctx):
    shift = await _day(db, tenant_ctx, opening="100.00")
    old = await _sellable_variant(db, tenant_ctx, price="100.00", stock=5)
    new = await _sellable_variant(db, tenant_ctx, price="150.00", stock=5)
    sale = await PosService.record_sale(
        db, tenant_ctx.tenant_id, shift.register_id, items=[{"variant_id": old.id, "quantity": 1}]
    )
    await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        order_id=sale["order_id"],
        return_lines=[{"variant_id": str(old.id), "quantity": 1}],
        new_lines=[{"variant_id": str(new.id), "quantity": 1}],
    )

    report = await PosService.session_report(db, tenant_ctx.tenant_id, shift.id)
    assert report["exchanges"]["exchange_count"] == 1
    (doc,) = report["exchanges"]["documents"]
    assert doc["total"] == "100.00" and doc["new_total"] == "150.00"
    assert doc["difference"] == "50.00"
    assert report["exchanges"]["difference_total"] == "50.00"
    assert report["returns"]["documents"] == []  # an exchange is not also a plain return
    # opening 100 + invoices (100 + 150) - returns 100 = 250
    assert report["closing_balance"] == "250.00"


async def test_closing_writes_no_payment_no_drawer_movement_no_refund_no_reconciliation(
    db, tenant_ctx
):
    shift = await _day(db, tenant_ctx)
    variant = await _sellable_variant(db, tenant_ctx, price="40.00", stock=10)
    await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        shift.register_id,
        items=[{"variant_id": variant.id, "quantity": 2}],
    )
    tid = tenant_ctx.tenant_id
    before = [
        await _count(db, m, tid)
        for m in (OrderPayment, PosCashMovement, Refund, PosSessionReconciliation)
    ]

    await PosService.close_session(db, tid, shift.id)

    after = [
        await _count(db, m, tid)
        for m in (OrderPayment, PosCashMovement, Refund, PosSessionReconciliation)
    ]
    assert before == after == [0, 0, 0, 0]
