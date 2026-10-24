"""The sales-by-day report equals what the shifts say, and counts days the way the SHOP does.

A day is the shop's own calendar day (tenants.timezone): a Cairo sale at 00:30 belongs to the new
Cairo day even though it is still the previous day in UTC. Returns are booked on the day the return
happened. A day's totals must equal the shift report's, so the two screens can never disagree.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import text

from tests._pos_sell import sell as pos_sell
from tests.test_pos_exchange import _customer, _register, _sellable_variant


async def _shift_with_sale(db, tenant_ctx, qty=2, price="50.00"):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx, price=price, stock=20)
    customer = await _customer(db, tenant_ctx)
    total = Decimal(price) * qty
    sold = await pos_sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        tenders=[{"method": "cash", "amount": str(total)}],
    )
    return PosService, pos_session, variant, sold


async def _set_tz(db, tenant_ctx, tz):
    await db.execute(
        text("UPDATE tenants SET timezone = :tz WHERE id = :id"),
        {"tz": tz, "id": tenant_ctx.tenant_id},
    )


async def test_a_day_equals_the_shift_report(db, tenant_ctx):
    PosService, pos_session, variant, sold = await _shift_with_sale(db, tenant_ctx)
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        restock=True,
    )

    rows = await PosService.sales_by_day(
        db, tenant_ctx.tenant_id, since=date(2000, 1, 1), until=date(2100, 1, 1)
    )
    shift = await PosService.session_report(db, tenant_ctx.tenant_id, pos_session.id)
    assert len(rows) == 1
    day = rows[0]
    assert Decimal(shift["returns"]["total"]) > 0  # the return really happened
    assert day["invoices"] == shift["sales"]["invoice_count"]
    assert day["returns_count"] == shift["returns"]["return_count"] == 1
    assert Decimal(day["returns"]) == Decimal(shift["returns"]["total"])
    assert Decimal(day["net"]) == Decimal(shift["sales"]["total"]) - Decimal(
        shift["returns"]["total"]
    )


async def test_pieces_and_gross_and_discount(db, tenant_ctx):
    PosService, pos_session, variant, sold = await _shift_with_sale(
        db, tenant_ctx, qty=3, price="40.00"
    )
    day = (
        await PosService.sales_by_day(
            db, tenant_ctx.tenant_id, since=date(2000, 1, 1), until=date(2100, 1, 1)
        )
    )[0]
    assert day["invoices"] == 1
    assert day["pieces"] == 3
    assert Decimal(day["gross"]) == Decimal("120.00")
    assert Decimal(day["discount"]) == Decimal("0.00")
    assert Decimal(day["net"]) == Decimal("120.00")


async def test_a_late_night_cairo_sale_belongs_to_the_cairo_day_not_the_utc_day(db, tenant_ctx):
    await _set_tz(db, tenant_ctx, "Africa/Cairo")
    PosService, pos_session, variant, sold = await _shift_with_sale(db, tenant_ctx)
    # 2026-03-10 22:30 UTC is 2026-03-11 00:30 in Cairo (UTC+2, no DST yet on that date).
    await db.execute(
        text("UPDATE pos_receipts SET issued_at = '2026-03-10 22:30:00+00' WHERE session_id = :s"),
        {"s": pos_session.id},
    )
    rows = await PosService.sales_by_day(
        db, tenant_ctx.tenant_id, since=date(2026, 3, 1), until=date(2026, 3, 31)
    )
    assert [r["date"] for r in rows] == ["2026-03-11"]


async def test_the_range_is_inclusive_and_excludes_other_days(db, tenant_ctx):
    await _set_tz(db, tenant_ctx, "Africa/Cairo")
    PosService, pos_session, variant, sold = await _shift_with_sale(db, tenant_ctx)
    await db.execute(
        text("UPDATE pos_receipts SET issued_at = '2026-03-11 10:00:00+00' WHERE session_id = :s"),
        {"s": pos_session.id},
    )
    inside = await PosService.sales_by_day(
        db, tenant_ctx.tenant_id, since=date(2026, 3, 11), until=date(2026, 3, 11)
    )
    before = await PosService.sales_by_day(
        db, tenant_ctx.tenant_id, since=date(2026, 3, 1), until=date(2026, 3, 10)
    )
    after = await PosService.sales_by_day(
        db, tenant_ctx.tenant_id, since=date(2026, 3, 12), until=date(2026, 3, 31)
    )
    assert len(inside) == 1 and before == [] and after == []


async def test_no_activity_means_no_rows(db, tenant_ctx):
    from app.modules.pos.service import PosService

    assert (
        await PosService.sales_by_day(
            db, tenant_ctx.tenant_id, since=date(2026, 1, 1), until=date(2026, 1, 31)
        )
        == []
    )
