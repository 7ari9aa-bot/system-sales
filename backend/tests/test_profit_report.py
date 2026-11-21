"""Profit by model, colour and size, from the cost the stock ledger already booked at the sale.

Nothing here prices anything: revenue is the order's own net line, cost is the ``cost_value`` the
sale movement carries, and a return gives back its refund. What the books cannot say is said out
loud instead of being folded into a flattering number: a sale whose cost the layers could not cover
is flagged, and the cost given back by a return is an estimate and is labelled as one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.core.profit_report import ProfitReportService
from app.modules.catalog.apparel.matrix import COLOR_AXIS, SIZE_AXIS
from app.modules.catalog.service import CatalogService
from app.modules.inventory.models import InventoryMovement, Warehouse
from app.modules.orders.models import Order, OrderItem
from app.modules.pos.models import PosReceipt, PosReturnLine  # noqa: F401

pytestmark = pytest.mark.asyncio

D = Decimal
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
DAY = NOW.date()


async def _wh(db, tid):
    wh = Warehouse(tenant_id=tid, name="W", code=f"W-{uuid.uuid4().hex[:6].upper()}")
    db.add(wh)
    await db.flush()
    return wh


async def _variant(db, tid, *, title="قميص", size="M", colour="أسود"):
    prod = await CatalogService.create_product(
        db, tid, title=title, slug=f"p-{uuid.uuid4().hex[:8]}"
    )
    opts = {}
    if size is not None:
        opts[SIZE_AXIS] = size
    if colour is not None:
        opts[COLOR_AXIS] = colour
    return prod, await CatalogService.add_variant(
        db, tid, prod.id, price="100.00", option_values=opts
    )


async def _customer(db, tid):
    from tests.test_pos_returns import _customer as mk

    return await mk(db, type("C", (), {"tenant_id": tid})())


async def _sale(
    db,
    tctx,
    wh,
    variant,
    *,
    qty,
    net,
    cost,
    status="completed",
    discount="0",
    channel="pos",
    when=NOW,
):
    """An order line and the sale movement the ledger books for it, as confirm_sale leaves them."""
    from tests.test_pos_returns import _customer as mk

    cust = await mk(db, tctx)
    order = Order(
        tenant_id=tctx.tenant_id,
        number=f"O-{uuid.uuid4().hex[:8]}",
        customer_id=cust.id,
        status=status,
        channel=channel,
        placed_at=when,
        subtotal=D(net),
        discount_total=D(discount),
        grand_total=D(net) - D(discount),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            tenant_id=tctx.tenant_id,
            order_id=order.id,
            variant_id=variant.id,
            title="x",
            quantity=qty,
            unit_price=D(net) / qty,
            total=D(net),
        )
    )
    mv = InventoryMovement(
        tenant_id=tctx.tenant_id,
        variant_id=variant.id,
        warehouse_id=wh.id,
        direction="out",
        quantity=qty,
        reason="sale",
        reference_type="order",
        reference_id=order.id,
        balance_after=0,
        cost_value=None if cost is None else D(cost),
    )
    db.add(mv)
    await db.flush()
    return order


async def _return(db, tctx, wh, order, variant, *, qty, refund, shelved=True):
    from tests._pos_helpers import till

    shift, _, _ = await till(db, tctx)
    receipt = PosReceipt(
        tenant_id=tctx.tenant_id,
        session_id=shift.id,
        order_id=order.id,
        number=f"R-{uuid.uuid4().hex[:6]}",
        kind="return",
    )
    db.add(receipt)
    await db.flush()
    db.add(
        PosReturnLine(
            tenant_id=tctx.tenant_id,
            receipt_id=receipt.id,
            order_id=order.id,
            variant_id=variant.id,
            quantity=qty,
            unit_price=D(refund) / qty,
            refund_total=D(refund),
        )
    )
    if shelved:
        db.add(
            InventoryMovement(
                tenant_id=tctx.tenant_id,
                variant_id=variant.id,
                warehouse_id=wh.id,
                direction="in",
                quantity=qty,
                reason="return",
                reference_type="order",
                reference_id=order.id,
                balance_after=0,
            )
        )
    await db.flush()


async def _expense(db, tid, amount, *, on=DAY, status="posted"):
    """A posted expense with every required column, in a category made for it."""
    from app.modules.expenses.models import Expense, ExpenseCategory

    cat = ExpenseCategory(tenant_id=tid, name=f"c-{uuid.uuid4().hex[:6]}")
    db.add(cat)
    await db.flush()
    db.add(
        Expense(
            tenant_id=tid,
            category_id=cat.id,
            number=f"E-{uuid.uuid4().hex[:6]}",
            description="x",
            amount=D(amount),
            payment_method="cash",
            expense_date=on,
            status=status,
        )
    )
    await db.flush()


async def _report(db, tid, **kw):
    return await ProfitReportService.by_variant(
        db,
        tid,
        start=kw.get("start", DAY - timedelta(days=1)),
        end=kw.get("end", DAY + timedelta(days=1)),
        channel=kw.get("channel"),
    )


def _row(rep, size="M", colour="أسود"):
    return next(r for r in rep["rows"] if r["size"] == size and r["colour"] == colour)


async def test_an_empty_shop_reports_zeroes(db, tenant_ctx) -> None:
    rep = await _report(db, tenant_ctx.tenant_id)
    assert rep["rows"] == []
    assert rep["totals"]["revenue"] == "0.00"
    assert rep["totals"]["gross_profit"] == "0.00"


async def test_one_sale_gives_revenue_cost_profit_and_margin(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=2, net="300.00", cost="120.00")
    r = _row(await _report(db, tid))
    assert r["units_sold"] == 2
    assert r["revenue"] == "300.00"
    assert r["cost"] == "120.00"
    assert r["gross_profit"] == "180.00"
    assert r["margin_pct"] == "60.00"


async def test_rows_are_per_model_colour_and_size(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    prod, v1 = await _variant(db, tid, size="M", colour="أسود")
    v2 = await CatalogService.add_variant(
        db, tid, prod.id, price="100", option_values={SIZE_AXIS: "L", COLOR_AXIS: "أسود"}
    )
    v3 = await CatalogService.add_variant(
        db, tid, prod.id, price="100", option_values={SIZE_AXIS: "M", COLOR_AXIS: "أبيض"}
    )
    for v, net in ((v1, "100"), (v2, "200"), (v3, "50")):
        await _sale(db, tenant_ctx, wh, v, qty=1, net=net, cost="10")
    rep = await _report(db, tid)
    assert len(rep["rows"]) == 3
    assert _row(rep, "L", "أسود")["revenue"] == "200.00"
    assert _row(rep, "M", "أبيض")["revenue"] == "50.00"
    assert all(r["model"] == "قميص" for r in rep["rows"])


async def test_two_sales_of_the_same_variant_are_added(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40")
    await _sale(db, tenant_ctx, wh, v, qty=3, net="270", cost="120")
    r = _row(await _report(db, tid))
    assert (r["units_sold"], r["revenue"], r["cost"], r["gross_profit"]) == (
        4,
        "370.00",
        "160.00",
        "210.00",
    )


async def test_a_product_with_no_size_or_colour_still_appears(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, size=None, colour=None)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="80", cost="30")
    rep = await _report(db, tid)
    assert rep["rows"][0]["size"] is None
    assert rep["rows"][0]["colour"] is None
    assert rep["totals"]["revenue"] == "80.00"


async def test_a_cancelled_or_draft_order_is_not_a_sale(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40", status="cancelled")
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40", status="draft")
    assert (await _report(db, tid))["rows"] == []


async def test_only_sales_inside_the_period_count_start_in_end_out(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40", when=NOW)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="999", cost="1", when=NOW - timedelta(days=10))
    rep = await ProfitReportService.by_variant(db, tid, start=DAY, end=DAY + timedelta(days=1))
    assert _row(rep)["revenue"] == "100.00"
    none = await ProfitReportService.by_variant(db, tid, start=DAY - timedelta(days=1), end=DAY)
    assert none["rows"] == []


async def test_an_order_discount_is_taken_off_the_revenue(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40", discount="10")
    r = _row(await _report(db, tid))
    assert r["revenue"] == "90.00"
    assert r["gross_profit"] == "50.00"


async def test_an_order_discount_is_shared_between_its_lines_in_proportion(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    prod, v1 = await _variant(db, tid, size="M")
    v2 = await CatalogService.add_variant(
        db, tid, prod.id, price="100", option_values={SIZE_AXIS: "L", COLOR_AXIS: "أسود"}
    )
    order = await _sale(db, tenant_ctx, wh, v1, qty=1, net="100", cost="10", discount="30")
    db.add(
        OrderItem(
            tenant_id=tid,
            order_id=order.id,
            variant_id=v2.id,
            title="y",
            quantity=1,
            unit_price=D("200"),
            total=D("200"),
        )
    )
    order.subtotal = D("300")
    order.grand_total = D("270")
    await db.flush()
    rep = await _report(db, tid)
    assert _row(rep, "M")["revenue"] == "90.00"
    assert _row(rep, "L")["revenue"] == "180.00"
    assert rep["totals"]["revenue"] == "270.00"


async def test_a_returned_item_gives_back_its_refund_and_its_cost(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    order = await _sale(db, tenant_ctx, wh, v, qty=4, net="400", cost="160")
    await _return(db, tenant_ctx, wh, order, v, qty=1, refund="100")
    r = _row(await _report(db, tid))
    assert r["units_sold"] == 4
    assert r["units_returned"] == 1
    assert r["revenue"] == "300.00"
    assert r["cost"] == "120.00"
    assert r["gross_profit"] == "180.00"
    assert r["cost_returned_is_estimate"] is True


async def test_a_return_that_did_not_go_back_on_the_shelf_gives_back_no_cost(
    db, tenant_ctx
) -> None:
    """A damaged return is refunded but the piece is gone: its cost stays a cost."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    order = await _sale(db, tenant_ctx, wh, v, qty=2, net="200", cost="80")
    await _return(db, tenant_ctx, wh, order, v, qty=1, refund="100", shelved=False)
    r = _row(await _report(db, tid))
    assert r["revenue"] == "100.00"
    assert r["cost"] == "80.00"
    assert r["gross_profit"] == "20.00"


async def test_a_sale_the_cost_layers_could_not_cover_is_flagged_not_hidden(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=2, net="200", cost=None)
    rep = await _report(db, tid)
    r = _row(rep)
    assert r["units_without_cost"] == 2
    assert rep["totals"]["units_without_cost"] == 2
    assert rep["totals"]["cost_is_complete"] is False


async def test_a_fully_costed_report_says_the_cost_is_complete(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40")
    assert (await _report(db, tid))["totals"]["cost_is_complete"] is True


async def test_a_zero_revenue_row_has_no_margin_not_a_division_error(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="0", cost="40")
    assert _row(await _report(db, tid))["margin_pct"] is None


async def test_a_loss_shows_as_a_negative_profit_and_margin(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="50", cost="80")
    r = _row(await _report(db, tid))
    assert r["gross_profit"] == "-30.00"
    assert r["margin_pct"] == "-60.00"


async def test_the_most_profitable_row_comes_first(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    prod, v1 = await _variant(db, tid, size="S")
    v2 = await CatalogService.add_variant(
        db, tid, prod.id, price="1", option_values={SIZE_AXIS: "M", COLOR_AXIS: "أسود"}
    )
    v3 = await CatalogService.add_variant(
        db, tid, prod.id, price="1", option_values={SIZE_AXIS: "L", COLOR_AXIS: "أسود"}
    )
    for v, net in ((v1, "50"), (v2, "500"), (v3, "200")):
        await _sale(db, tenant_ctx, wh, v, qty=1, net=net, cost="10")
    assert [r["size"] for r in (await _report(db, tid))["rows"]] == ["M", "L", "S"]


async def test_a_channel_filter_keeps_only_that_channel(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40", channel="pos")
    await _sale(db, tenant_ctx, wh, v, qty=1, net="500", cost="40", channel="webchat")
    assert _row(await _report(db, tid, channel="pos"))["revenue"] == "100.00"
    assert _row(await _report(db, tid))["revenue"] == "600.00"


async def test_another_shops_sales_are_never_included(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40")
    assert (await _report(db, uuid.uuid4()))["rows"] == []


async def test_an_inverted_period_is_refused(db, tenant_ctx) -> None:
    with pytest.raises(ValidationError):
        await ProfitReportService.by_variant(
            db, tenant_ctx.tenant_id, start=DAY, end=DAY - timedelta(days=1)
        )


async def test_the_report_runs_the_same_number_of_queries_for_one_row_or_many(
    db, tenant_ctx
) -> None:
    from sqlalchemy import event

    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    counts: list[int] = []

    def count(n):
        def _before(*_a, **_k):
            n[0] += 1

        return _before

    async def measure():
        n = [0]
        sync = db.sync_session.get_bind()
        h = count(n)
        event.listen(sync, "before_cursor_execute", h)
        try:
            await _report(db, tid)
        finally:
            event.remove(sync, "before_cursor_execute", h)
        return n[0]

    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="10", cost="1")
    counts.append(await measure())
    for i in range(6):
        _, vi = await _variant(db, tid, title=f"m{i}", size="L", colour=f"c{i}")
        await _sale(db, tenant_ctx, wh, vi, qty=1, net="10", cost="1")
    counts.append(await measure())
    assert counts[0] == counts[1]


# ── stock value and expenses ───────────────────────────────────────────────────────────────────


async def test_the_summary_adds_posted_expenses_and_gives_net_profit(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="500", cost="200")
    await _expense(db, tid, "100")
    await _expense(db, tid, "50")
    await _expense(db, tid, "999", status="voided")
    s = await ProfitReportService.summary(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1)
    )
    assert s["gross_profit"] == "300.00"
    assert s["expenses"] == "150.00"
    assert s["net_profit"] == "150.00"


async def test_an_expense_outside_the_period_is_not_counted(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _expense(db, tid, "70", on=DAY - timedelta(days=30))
    s = await ProfitReportService.summary(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1)
    )
    assert s["expenses"] == "0.00"


async def test_an_expense_on_the_first_day_counts_and_on_the_end_day_does_not(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    await _expense(db, tid, "10", on=DAY)
    await _expense(db, tid, "20", on=DAY + timedelta(days=1))
    s = await ProfitReportService.summary(db, tid, start=DAY, end=DAY + timedelta(days=1))
    assert s["expenses"] == "10.00"


async def test_a_net_loss_is_negative(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _expense(db, tid, "70")
    s = await ProfitReportService.summary(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1)
    )
    assert s["net_profit"] == "-70.00"


async def test_another_shops_expenses_are_not_counted(db, tenant_ctx) -> None:
    await _expense(db, tenant_ctx.tenant_id, "70")
    s = await ProfitReportService.summary(
        db, uuid.uuid4(), start=DAY - timedelta(days=1), end=DAY + timedelta(days=1)
    )
    assert s["expenses"] == "0.00"


async def test_stock_value_at_cost_comes_from_the_live_cost_layers(db, tenant_ctx) -> None:
    from app.modules.inventory.service import ValuationService

    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await ValuationService.create_cost_layer(
        db, tid, variant_id=v.id, warehouse_id=wh.id, quantity=10, unit_cost="12.50"
    )
    s = await ProfitReportService.summary(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1)
    )
    assert s["stock_value_at_cost"] == "125.00"
    assert s["stock_units"] == 10


async def test_stock_already_sold_out_of_a_layer_is_not_valued(db, tenant_ctx) -> None:
    from app.modules.inventory.service import InventoryService, ValuationService

    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await InventoryService.move(
        db, tid, v.id, wh.id, direction="in", quantity=10, reason="purchase"
    )
    await ValuationService.create_cost_layer(
        db, tid, variant_id=v.id, warehouse_id=wh.id, quantity=10, unit_cost="10.00"
    )
    await ValuationService.consume_fifo(db, tid, variant_id=v.id, warehouse_id=wh.id, quantity=4)
    s = await ProfitReportService.summary(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1)
    )
    assert s["stock_value_at_cost"] == "60.00"
    assert s["stock_units"] == 6


# ── through the real till ──────────────────────────────────────────────────────────────────────


async def test_a_sale_made_on_the_real_till_is_reported_at_the_cost_the_ledger_booked(
    db, tenant_ctx
) -> None:
    """Every test above builds the sale movement by hand. This one sells through the cashier path
    and checks the report reads what that path really stored: a receipt of 50 at 40.00, three
    sold at 100.00, so 300.00 of revenue against 120.00 of cost."""
    from app.modules.inventory.service import ValuationService
    from app.modules.pos.models import PosSession
    from tests._pos_helpers import start_day, till
    from tests._pos_sell import sell

    tid = tenant_ctx.tenant_id
    shift, variant, customer = await till(db, tenant_ctx)
    session = await db.get(PosSession, shift.id)
    await start_day(db, tenant_ctx, session.register_id)
    wh_id = (
        await db.execute(
            __import__("sqlalchemy").text(
                "select warehouse_id from inventory_balances where variant_id = :v"
            ),
            {"v": variant.id},
        )
    ).scalar_one()
    await ValuationService.create_cost_layer(
        db, tid, variant_id=variant.id, warehouse_id=wh_id, quantity=50, unit_cost="40.00"
    )
    await sell(db, tid, shift.id, items=[{"variant_id": variant.id, "quantity": 3}])

    rep = await ProfitReportService.by_variant(
        db,
        tid,
        start=datetime.now(UTC).date() - timedelta(days=1),
        end=datetime.now(UTC).date() + timedelta(days=2),
    )
    assert len(rep["rows"]) == 1
    row = rep["rows"][0]
    assert row["units_sold"] == 3
    assert row["revenue"] == "300.00"
    assert row["cost"] == "120.00"
    assert row["gross_profit"] == "180.00"
    assert rep["totals"]["cost_is_complete"] is True


# ── over HTTP ──────────────────────────────────────────────────────────────────────────────────


def _q(**kw) -> str:
    start = (DAY - timedelta(days=1)).isoformat()
    end = (DAY + timedelta(days=1)).isoformat()
    extra = "".join(f"&{k}={v}" for k, v in kw.items())
    return f"start={start}&end={end}{extra}"


async def test_the_profit_reports_are_manager_only(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import CASHIER, MANAGER, _call

    for path in ("/api/v1/reports/profit", "/api/v1/reports/profit/by-variant"):
        denied = await _call(db, tenant_ctx, "GET", f"{path}?{_q()}", perms=CASHIER)
        assert denied.status_code == 403, path
        ok = await _call(db, tenant_ctx, "GET", f"{path}?{_q()}", perms=MANAGER)
        assert ok.status_code == 200, ok.text


async def test_the_by_variant_route_returns_the_rows_and_totals(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=2, net="300", cost="120")
    r = await _call(
        db, tenant_ctx, "GET", f"/api/v1/reports/profit/by-variant?{_q()}", perms=MANAGER
    )
    body = r.json()
    assert body["rows"][0]["gross_profit"] == "180.00"
    assert body["totals"]["revenue"] == "300.00"


async def test_the_summary_route_returns_net_profit_and_stock_value(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="500", cost="200")
    await _expense(db, tid, "100")
    r = await _call(db, tenant_ctx, "GET", f"/api/v1/reports/profit?{_q()}", perms=MANAGER)
    body = r.json()
    assert body["net_profit"] == "200.00"
    assert "stock_value_at_cost" in body


async def test_the_channel_filter_reaches_the_report_over_http(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40", channel="pos")
    await _sale(db, tenant_ctx, wh, v, qty=1, net="500", cost="40", channel="webchat")
    r = await _call(
        db,
        tenant_ctx,
        "GET",
        f"/api/v1/reports/profit/by-variant?{_q(channel='pos')}",
        perms=MANAGER,
    )
    assert r.json()["totals"]["revenue"] == "100.00"


async def test_a_bad_date_is_a_client_error_not_a_crash(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    r = await _call(
        db, tenant_ctx, "GET", "/api/v1/reports/profit?start=nope&end=2026-12-01", perms=MANAGER
    )
    assert r.status_code in (400, 422)
    r = await _call(
        db,
        tenant_ctx,
        "GET",
        "/api/v1/reports/profit?start=2026-12-02&end=2026-12-01",
        perms=MANAGER,
    )
    assert r.status_code in (400, 422)


# ── gaps found by mutation ─────────────────────────────────────────────────────────────────────


async def test_a_sale_exactly_at_the_start_counts_and_exactly_at_the_end_does_not(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    lo = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    hi = lo + timedelta(days=1)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="10", cost="1", when=lo)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="1000", cost="1", when=hi)
    rep = await ProfitReportService.by_variant(db, tid, start=lo, end=hi)
    assert _row(rep)["revenue"] == "10.00"


async def test_a_period_that_starts_and_ends_at_the_same_instant_is_refused(db, tenant_ctx) -> None:
    with pytest.raises(ValidationError):
        await ProfitReportService.by_variant(db, tenant_ctx.tenant_id, start=NOW, end=NOW)


async def test_a_naive_datetime_is_read_as_utc_not_rejected_or_shifted(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="10", cost="1", when=NOW)
    rep = await ProfitReportService.by_variant(
        db, tid, start=datetime(2026, 11, 20, 0, 0), end=datetime(2026, 11, 21, 0, 0)
    )
    assert _row(rep)["revenue"] == "10.00"
    assert rep["period"]["start"].endswith("+00:00")


async def test_a_naive_date_string_over_http_is_read_as_utc(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="10", cost="1", when=NOW)
    r = await _call(
        db,
        tenant_ctx,
        "GET",
        "/api/v1/reports/profit/by-variant?start=2026-11-20T00:00:00&end=2026-11-21T00:00:00",
        perms=MANAGER,
    )
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["revenue"] == "10.00"
    assert r.json()["period"]["start"].endswith("+00:00")


async def test_an_invoice_discount_larger_than_the_lines_cannot_make_revenue_negative(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40", discount="250")
    assert _row(await _report(db, tid))["revenue"] == "0.00"


async def test_more_pieces_back_on_the_shelf_than_were_returned_give_back_only_the_returned(
    db, tenant_ctx
) -> None:
    """A stray return movement must not hand back more cost than the return itself carried."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    order = await _sale(db, tenant_ctx, wh, v, qty=4, net="400", cost="160")
    await _return(db, tenant_ctx, wh, order, v, qty=1, refund="100")
    db.add(
        InventoryMovement(
            tenant_id=tid,
            variant_id=v.id,
            warehouse_id=wh.id,
            direction="in",
            quantity=3,
            reason="return",
            reference_type="order",
            reference_id=order.id,
            balance_after=0,
        )
    )
    await db.flush()
    r = _row(await _report(db, tid))
    assert r["cost"] == "120.00"  # 160 booked, one piece (40) given back, not four (which is 0)


async def test_the_average_cost_ignores_units_that_carried_no_cost(db, tenant_ctx) -> None:
    """Two pieces costed at 40 each and two with no cost booked: a return gives back 40, not 20."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    order = await _sale(db, tenant_ctx, wh, v, qty=4, net="400", cost="80")
    db.add(
        InventoryMovement(
            tenant_id=tid,
            variant_id=v.id,
            warehouse_id=wh.id,
            direction="out",
            quantity=2,
            reason="sale",
            reference_type="order",
            reference_id=order.id,
            balance_after=0,
            cost_value=None,
        )
    )
    await db.flush()
    order_units_costed = 2
    await _return(db, tenant_ctx, wh, order, v, qty=1, refund="100")
    r = _row(await _report(db, tid))
    assert order_units_costed == 2
    assert r["cost"] == "40.00"  # 80 booked, 40 (one costed piece) given back
    assert r["units_without_cost"] == 2


async def test_a_return_larger_than_the_sale_in_the_period_gives_no_margin(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    order = await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="40")
    await _return(db, tenant_ctx, wh, order, v, qty=1, refund="150")
    r = _row(await _report(db, tid))
    assert r["revenue"] == "-50.00"
    assert r["margin_pct"] is None


async def test_a_layer_sold_out_to_zero_is_not_valued(db, tenant_ctx) -> None:
    from app.modules.inventory.service import InventoryService, ValuationService

    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid)
    await InventoryService.move(db, tid, v.id, wh.id, direction="in", quantity=5, reason="purchase")
    await ValuationService.create_cost_layer(
        db, tid, variant_id=v.id, warehouse_id=wh.id, quantity=5, unit_cost="30.00"
    )
    await ValuationService.consume_fifo(db, tid, variant_id=v.id, warehouse_id=wh.id, quantity=5)
    s = await ProfitReportService.summary(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1)
    )
    assert s["stock_value_at_cost"] == "0.00"
    assert s["stock_units"] == 0


async def test_every_query_names_the_shop_it_is_for(db, tenant_ctx, monkeypatch) -> None:
    """Row-level security is the backstop. Each place the report reads a shop's own table must
    also name the shop, so a missing policy or a privileged connection can never mix two shops'
    books. Checked per read, not per statement: one statement reads the ledger twice."""
    import re

    tid = tenant_ctx.tenant_id
    seen: list[str] = []
    real = db.execute

    async def spy(stmt, *a, **k):
        seen.append(str(stmt.compile()))
        return await real(stmt, *a, **k)

    monkeypatch.setattr(db, "execute", spy)
    await ProfitReportService.summary(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1)
    )
    sql = "\n".join(seen)
    expected_reads = {
        "order_items": 1,
        "orders": 1,
        "inventory_movements": 2,  # the sale cost and the shelved returns
        "pos_return_lines": 1,
        "expenses": 1,
        "inventory_cost_layers": 1,
    }
    for table, reads in expected_reads.items():
        # a read of the table is its FROM, and a read must be matched by its own tenant filter
        froms = len(re.findall(rf"(?:FROM|JOIN) {table}\b", sql))
        filters = len(re.findall(rf"{table}\.tenant_id = ", sql))
        assert froms >= reads, f"{table}: expected {reads} reads, saw {froms}"
        assert filters >= reads, f"{table}: {reads} reads but only {filters} name the shop"
