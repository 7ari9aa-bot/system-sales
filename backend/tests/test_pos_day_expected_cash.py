"""The day's expected drawer = opening + the day's sales (the shop is cash only).

A sale taken through ``record_sale`` books no drawer row, so the drawer arithmetic alone would say
the drawer still holds only its opening. The expected figure adds the day's recorded sales, and a
sale from the older paid flow (which already wrote its ``cash_sale`` row) is never counted twice.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.pos.service import PosService
from tests._pos_helpers import till

pytestmark = pytest.mark.asyncio


async def _expected(db, tenant_ctx, shift) -> Decimal:
    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, shift.id)
    return Decimal(preview["closing_balance"])


async def _record(db, tenant_ctx, shift, variant, qty=1) -> dict:
    return await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        shift.register_id,
        items=[{"variant_id": variant.id, "quantity": qty}],
    )


async def test_the_expected_drawer_is_the_opening_plus_the_days_sales(db, tenant_ctx) -> None:
    shift, variant, _c = await till(db, tenant_ctx)
    base = await _expected(db, tenant_ctx, shift)

    await _record(db, tenant_ctx, shift, variant, qty=1)
    await _record(db, tenant_ctx, shift, variant, qty=2)

    assert await _expected(db, tenant_ctx, shift) == base + Decimal("300.00")


async def test_the_live_figure_and_the_close_figure_agree(db, tenant_ctx) -> None:
    shift, variant, _c = await till(db, tenant_ctx)
    await _record(db, tenant_ctx, shift, variant, qty=2)
    expected = await _expected(db, tenant_ctx, shift)

    live = await PosService.get_session(db, tenant_ctx.tenant_id, shift.id)
    closed = await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)

    assert Decimal(live["expected_now"]) == expected
    assert Decimal(closed.expected_cash) == expected
    assert closed.variance is None  # nothing is counted, so nothing can be short or over


async def test_closing_never_computes_a_shortage(db, tenant_ctx) -> None:
    shift, variant, _c = await till(db, tenant_ctx)
    await _record(db, tenant_ctx, shift, variant, qty=1)
    expected = await _expected(db, tenant_ctx, shift)

    closed = await PosService.close_session(db, tenant_ctx.tenant_id, shift.id)

    assert closed.variance is None
    assert closed.counted_cash is None
    assert Decimal(closed.expected_cash) == expected


async def test_a_sale_from_the_paid_flow_is_not_counted_twice(db, tenant_ctx) -> None:
    shift, variant, _c = await till(db, tenant_ctx)
    base = await _expected(db, tenant_ctx, shift)

    await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        items=[{"variant_id": variant.id, "quantity": 1}],
        method="cash",
        amount="100.00",
    )

    # The paid sale wrote its own drawer row: +100 once, not +200.
    assert await _expected(db, tenant_ctx, shift) == base + Decimal("100.00")


async def test_every_invoice_counts_in_the_closing_balance_whatever_the_tender(
    db, tenant_ctx
) -> None:
    from tests.test_pos_returns import _register, _sellable_variant

    register = await _register(db, tenant_ctx)
    shift = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    base = await _expected(db, tenant_ctx, shift)

    await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        method="card",
    )

    # The POS records invoices, it does not settle them: a 25.00 invoice adds 25.00 to the day's
    # closing balance whatever tender the older paid flow attached to it.
    assert await _expected(db, tenant_ctx, shift) == base + Decimal("25.00")
