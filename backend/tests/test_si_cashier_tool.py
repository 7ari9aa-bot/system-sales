"""``si_cashier_summary``: what the till sold, returned and netted, and who is on shift.

The cashier is a sales LEDGER, not a cash settler: it records no payment method, no cash tendered
to the shop's drawer count and no variance (the close stores counted/variance as NULL). So this
tool reports sales, returns, net, tax, per-cashier totals and shifts, and says outright that it
knows nothing about cash versus card or drawer differences. Sales and returns use the same rules
as the shift report: sales on ``kind == 'sale'`` receipts only (a return receipt points at the
same order), returns on the return lines.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.ai.agents.sales_intelligence.tools import _si_cashier_summary
from app.modules.ai.tools import TOOLS
from app.modules.catalog.models import Product, ProductVariant
from app.modules.customers.models import Customer
from app.modules.inventory.models import Warehouse
from app.modules.orders.models import Order
from app.modules.pos.models import (
    PosHeldCart,
    PosProfile,
    PosReceipt,
    PosRegister,
    PosReturnLine,
    PosSession,
)

pytestmark = pytest.mark.usefixtures("db")

NOW = datetime.now(UTC)


def _d(x) -> Decimal:
    return Decimal(str(x))


async def _user(db) -> uuid.UUID:
    """A real user: ``pos_sessions.cashier_user_id`` is a foreign key to users."""
    from app.modules.identity.models import User

    u = User(
        email=f"c-{uuid.uuid4().hex[:10]}@test.local",
        password_hash="x",
        full_name="Cashier",
    )
    db.add(u)
    await db.flush()
    return u.id


async def _register(db, t) -> PosRegister:
    wh = Warehouse(tenant_id=t, name="Main", code=f"W{uuid.uuid4().hex[:4]}")
    db.add(wh)
    await db.flush()
    r = PosRegister(tenant_id=t, name="Till", code=f"R{uuid.uuid4().hex[:4]}", warehouse_id=wh.id)
    db.add(r)
    await db.flush()
    return r


async def _shift(db, t, register=None, *, status="OPEN", days_ago=0, cashier=None):
    register = register or await _register(db, t)
    opened = NOW - timedelta(days=days_ago, hours=2)
    s = PosSession(
        tenant_id=t,
        register_id=register.id,
        status=status,
        opening_float=Decimal("100"),
        opened_at=opened,
        cashier_user_id=cashier,
        closed_at=(opened + timedelta(hours=1)) if status == "CLOSED" else None,
    )
    db.add(s)
    await db.flush()
    return s


async def _sale(db, t, shift, total, *, tax=0, sold_by=None, days_ago=0, hours_ago=1):
    customer = Customer(tenant_id=t, name="C", phone=f"+2010{uuid.uuid4().int % 10**8:08d}")
    db.add(customer)
    await db.flush()
    order = Order(
        tenant_id=t,
        number=f"O-{uuid.uuid4().hex[:8]}",
        customer_id=customer.id,
        status="confirmed",
        grand_total=_d(total),
        tax_total=_d(tax),
    )
    db.add(order)
    await db.flush()
    issued = NOW - timedelta(days=days_ago, hours=hours_ago)
    rc = PosReceipt(
        tenant_id=t,
        order_id=order.id,
        session_id=shift.id,
        number=f"RC-{uuid.uuid4().hex[:8]}",
        kind="sale",
        issued_at=issued,
        sold_by_user_id=sold_by,
    )
    db.add(rc)
    await db.flush()
    return rc


async def _sale_at(db, t, shift, total, issued_at):
    rc = await _sale(db, t, shift, total)
    rc.issued_at = issued_at
    await db.flush()
    return rc


async def _return(db, t, shift, sale_receipt, refund, *, days_ago=0, lines=1):
    """A return receipt for the SAME order, with one refund line."""
    p = Product(tenant_id=t, title="P", slug=f"p-{uuid.uuid4().hex[:8]}", status="active")
    db.add(p)
    await db.flush()
    v = ProductVariant(
        tenant_id=t, product_id=p.id, sku=f"S{uuid.uuid4().hex[:6]}", price=_d(refund)
    )
    db.add(v)
    await db.flush()
    rc = PosReceipt(
        tenant_id=t,
        order_id=sale_receipt.order_id,
        session_id=shift.id,
        number=f"RR-{uuid.uuid4().hex[:8]}",
        kind="return",
        issued_at=NOW - timedelta(days=days_ago, hours=1),
    )
    db.add(rc)
    await db.flush()
    for _ in range(lines):
        db.add(
            PosReturnLine(
                tenant_id=t,
                receipt_id=rc.id,
                order_id=sale_receipt.order_id,
                variant_id=v.id,
                quantity=1,
                unit_price=_d(refund),
                refund_total=_d(refund),
            )
        )
    await db.flush()
    return rc


# ------------------------------ sales, returns, net -----------------------------------------


async def test_sales_count_total_and_tax(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    await _sale(db, t, sh, 100, tax=14)
    await _sale(db, t, sh, 250, tax=35)
    r = await _si_cashier_summary(db, t, days=30)
    s = r["summary"]
    assert s["invoice_count"] == 2
    assert _d(s["sales_total"]) == Decimal("350")
    assert _d(s["taxes_total"]) == Decimal("49")


async def test_a_return_reduces_net_but_is_not_counted_as_a_sale(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    sale = await _sale(db, t, sh, 300)
    await _return(db, t, sh, sale, 80)
    s = (await _si_cashier_summary(db, t, days=30))["summary"]
    assert s["invoice_count"] == 1, "the return receipt shares the order but is not a sale"
    assert _d(s["sales_total"]) == Decimal("300")
    assert s["return_count"] == 1
    assert _d(s["returns_total"]) == Decimal("80")
    assert _d(s["net_sales"]) == Decimal("220")


async def test_a_return_receipt_never_doubles_the_sale_total(db, tenant_ctx):
    """Return and sale receipts point at the same order; joining orders per receipt would count
    its grand_total twice."""
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    sale = await _sale(db, t, sh, 500)
    await _return(db, t, sh, sale, 50)
    await _return(db, t, sh, sale, 25)
    s = (await _si_cashier_summary(db, t, days=30))["summary"]
    assert _d(s["sales_total"]) == Decimal("500")
    assert s["return_count"] == 2


async def test_a_sale_made_a_minute_ago_is_in_todays_numbers(db, tenant_ctx):
    """The owner's first question is "how much did I sell today?". The shared analytics window
    stops at midnight (today is immature for delivery metrics), which would answer 'nothing'."""
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    await _sale(db, t, sh, 123, hours_ago=0)
    s = (await _si_cashier_summary(db, t, days=1))["summary"]
    assert s["invoice_count"] == 1
    assert _d(s["sales_total"]) == Decimal("123")


async def test_a_one_day_window_does_not_reach_back_to_yesterday(db, tenant_ctx):
    from app.modules.ai.agents.sales_intelligence import tools as si

    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    await _sale(db, t, sh, 50, hours_ago=0)
    await _sale(db, t, sh, 900, days_ago=2)
    s = (await si._si_cashier_summary(db, t, days=1))["summary"]
    assert _d(s["sales_total"]) == Decimal("50")


async def test_a_sale_before_the_window_is_left_out(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    await _sale(db, t, sh, 100, days_ago=2)
    await _sale(db, t, sh, 9000, days_ago=90)
    s = (await _si_cashier_summary(db, t, days=30))["summary"]
    assert _d(s["sales_total"]) == Decimal("100")


async def test_a_return_before_the_window_is_left_out(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    sale = await _sale(db, t, sh, 400, days_ago=2)
    await _return(db, t, sh, sale, 60, days_ago=2)
    old = await _sale(db, t, sh, 400, days_ago=90)
    await _return(db, t, sh, old, 999, days_ago=90)
    s = (await _si_cashier_summary(db, t, days=30))["summary"]
    assert _d(s["returns_total"]) == Decimal("60")


async def test_net_can_be_negative_when_returns_exceed_sales_in_the_window(db, tenant_ctx):
    """A refund today for a sale made last month is a real outflow in this window."""
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    old = await _sale(db, t, sh, 500, days_ago=60)
    await _sale(db, t, sh, 100, days_ago=1)
    await _return(db, t, sh, old, 300, days_ago=1)
    r = await _si_cashier_summary(db, t, days=30)
    assert _d(r["summary"]["net_sales"]) == Decimal("-200")
    assert any("negative" in n for n in r["limitations"])


# ------------------------------ per cashier -------------------------------------------------


async def test_sales_are_split_by_who_sold_biggest_first(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    a, b = uuid.uuid4(), uuid.uuid4()
    sh = await _shift(db, t)
    await _sale(db, t, sh, 50, sold_by=a)
    await _sale(db, t, sh, 700, sold_by=b)
    await _sale(db, t, sh, 30, sold_by=a)
    by = (await _si_cashier_summary(db, t, days=30))["summary"]["by_cashier"]
    assert [row["cashier_id"] for row in by] == [str(b), str(a)]
    assert _d(by[0]["sales_total"]) == Decimal("700")
    assert by[1]["invoice_count"] == 2


async def test_old_receipts_without_a_seller_are_unattributed_not_spread(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    a = uuid.uuid4()
    sh = await _shift(db, t)
    await _sale(db, t, sh, 100, sold_by=a)
    await _sale(db, t, sh, 40, sold_by=None)
    r = await _si_cashier_summary(db, t, days=30)
    by = {row["cashier_id"]: row for row in r["summary"]["by_cashier"]}
    assert _d(by["unknown"]["sales_total"]) == Decimal("40")
    assert _d(by[str(a)]["sales_total"]) == Decimal("100")
    assert any("no recorded seller" in n for n in r["limitations"])


# ------------------------------ shifts ------------------------------------------------------


async def test_open_shifts_are_listed_with_who_holds_them(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    u = await _user(db)
    await _shift(db, t, status="OPEN", cashier=u)
    await _shift(db, t, status="CLOSED")
    s = (await _si_cashier_summary(db, t, days=30))["summary"]
    assert len(s["open_shifts"]) == 1
    assert s["open_shifts"][0]["cashier_id"] == str(u)
    assert s["closed_shifts"] == 1


async def test_an_old_open_shift_is_flagged(db, tenant_ctx):
    """A shift left open for days is the thing an owner needs to hear about."""
    t = tenant_ctx.tenant_id
    await _shift(db, t, status="OPEN", days_ago=3)
    r = await _si_cashier_summary(db, t, days=30)
    assert r["summary"]["open_shifts"][0]["open_hours"] >= 24
    assert any("open for more than a day" in n for n in r["limitations"])


async def test_a_fresh_open_shift_is_not_flagged(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _shift(db, t, status="OPEN", days_ago=0)
    r = await _si_cashier_summary(db, t, days=30)
    assert not any("open for more than a day" in n for n in r["limitations"])


async def test_a_shift_closed_before_the_window_is_not_counted(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _shift(db, t, status="CLOSED", days_ago=2)
    await _shift(db, t, status="CLOSED", days_ago=120)
    s = (await _si_cashier_summary(db, t, days=30))["summary"]
    assert s["closed_shifts"] == 1


# ------------------------------ busiest hours -----------------------------------------------


async def test_busiest_hours_use_the_shops_local_time_and_rank_by_sales(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    for _ in range(3):
        await _sale(db, t, sh, 10, hours_ago=5)
    await _sale(db, t, sh, 10, hours_ago=9)
    hours = (await _si_cashier_summary(db, t, days=30))["summary"]["busiest_hours"]
    assert hours[0]["invoice_count"] == 3
    assert hours[0]["invoice_count"] > hours[1]["invoice_count"]
    assert all(0 <= h["hour"] <= 23 for h in hours)


async def test_one_return_receipt_with_several_lines_is_one_return(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    sale = await _sale(db, t, sh, 500)
    await _return(db, t, sh, sale, 40, lines=3)
    s = (await _si_cashier_summary(db, t, days=30))["summary"]
    assert s["return_count"] == 1, "three refunded items on one receipt are one return"
    assert _d(s["returns_total"]) == Decimal("120")


async def test_the_window_is_exactly_the_days_asked_for_counting_today(db, tenant_ctx):
    """days=30 is today plus the 29 days before it. A sale 29 days ago is in; 30 days ago is not.
    Without the one-day shift the window is 31 days long."""
    from zoneinfo import ZoneInfo

    from app.modules.analytics.service import resolve_report_timezone

    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    zone = ZoneInfo(str(await resolve_report_timezone(db, t)))
    midnight = datetime.now(zone).replace(hour=12, minute=0, second=0, microsecond=0)
    await _sale_at(db, t, sh, 10, midnight - timedelta(days=29))
    await _sale_at(db, t, sh, 7000, midnight - timedelta(days=30))
    s = (await _si_cashier_summary(db, t, days=30))["summary"]
    assert _d(s["sales_total"]) == Decimal("10")


async def test_busiest_hours_are_in_the_shops_time_zone_not_utc(db, tenant_ctx):
    from zoneinfo import ZoneInfo

    from sqlalchemy import text

    t = tenant_ctx.tenant_id
    await db.execute(
        text("UPDATE tenants SET timezone = 'Pacific/Auckland' WHERE id = :t"), {"t": str(t)}
    )
    sh = await _shift(db, t)
    at = datetime.now(UTC).replace(hour=3, minute=30, second=0, microsecond=0) - timedelta(days=1)
    await _sale_at(db, t, sh, 10, at)
    hours = (await _si_cashier_summary(db, t, days=30))["summary"]["busiest_hours"]
    assert hours[0]["hour"] == at.astimezone(ZoneInfo("Pacific/Auckland")).hour
    assert hours[0]["hour"] != at.hour, "the test must use a zone whose hour differs from UTC"


async def test_busiest_hours_rank_the_busiest_first_whatever_the_clock_order(db, tenant_ctx):
    """Seeded quiet-hour first, so an unsorted result lists the quiet hour on top."""
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=2)
    await _sale_at(db, t, sh, 10, base.replace(hour=2))
    for _ in range(3):
        await _sale_at(db, t, sh, 10, base.replace(hour=14))
    for _ in range(2):
        await _sale_at(db, t, sh, 10, base.replace(hour=9))
    counts = [
        h["invoice_count"]
        for h in (await _si_cashier_summary(db, t, days=30))["summary"]["busiest_hours"]
    ]
    assert counts == [3, 2, 1]


# ------------------------------ honesty and isolation ---------------------------------------


async def test_it_never_claims_anything_about_payment_methods_or_the_drawer(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    await _sale(db, t, sh, 100)
    r = await _si_cashier_summary(db, t, days=30)
    text = " ".join(r["limitations"]).lower()
    assert "payment method" in text and "drawer" in text
    for forbidden in ("cash_total", "card_total", "variance", "by_method", "counted"):
        assert forbidden not in r["summary"]


async def test_no_register_at_all_says_the_cashier_is_not_set_up(db, tenant_ctx):
    r = await _si_cashier_summary(db, tenant_ctx.tenant_id, days=30)
    assert r["status"] == "no_data"
    assert r["summary"]["invoice_count"] == 0
    assert any("no cashier" in n.lower() for n in r["limitations"])
    assert r["facts"] == []


async def test_a_register_but_no_sales_is_ok_with_zero(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _shift(db, t, status="CLOSED")
    r = await _si_cashier_summary(db, t, days=30)
    assert r["status"] == "ok"
    assert _d(r["summary"]["sales_total"]) == 0


async def test_held_carts_are_not_sales(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    db.add(PosHeldCart(tenant_id=t, session_id=sh.id, label="x", items=[]))
    await db.flush()
    s = (await _si_cashier_summary(db, t, days=30))["summary"]
    assert s["invoice_count"] == 0
    assert _d(s["sales_total"]) == 0


async def test_facts_carry_the_money_and_counts(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    sh = await _shift(db, t)
    await _sale(db, t, sh, 100)
    metrics = {f["metric"] for f in (await _si_cashier_summary(db, t, days=30))["facts"]}
    assert {"pos_sales_total", "pos_invoice_count", "pos_net_sales"} <= metrics


async def test_one_shop_never_sees_another_shops_till(db, tenant_ctx):
    from app.core.db import bind_tenant
    from app.modules.identity.models import Tenant

    mine = tenant_ctx.tenant_id
    sh = await _shift(db, mine)
    await _sale(db, mine, sh, 777)
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    r = await _si_cashier_summary(db, other.id, days=30)
    assert r["status"] == "no_data"
    assert _d(r["summary"]["sales_total"]) == 0


# ------------------------------ wiring ------------------------------------------------------


def test_registered_with_the_same_permission_the_till_reports_use():
    import app.modules.ai.agents.sales_intelligence.tools as si
    from app.core.risk import known_actions
    from app.modules.ai.core.registry import AgentRegistry

    si.register_si_tools()
    spec = TOOLS["si_cashier_summary"]
    assert spec.requires == "orders:read"
    assert spec.risk_level == "LOW"
    assert "si_cashier_summary" in known_actions()
    assert AgentRegistry.is_tool_authorized("sales_intelligence", "si_cashier_summary")


def test_every_cashier_query_is_tenant_scoped():
    from app.modules.ai.agents.sales_intelligence import tools as si

    for name in ("_CASHIER_SALES_SQL", "_CASHIER_RETURNS_SQL", "_CASHIER_SHIFTS_SQL"):
        assert "tenant_id = :tenant_id" in getattr(si, name), name
    assert "o.tenant_id = r.tenant_id" in si._CASHIER_SALES_SQL
    assert "r.tenant_id = rl.tenant_id" in si._CASHIER_RETURNS_SQL


_ = PosProfile  # imported so every FK target is mapped
