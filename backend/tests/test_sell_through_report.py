"""Sell-through by model, colour and size: sold, left on the shelf, and the share sold.

The sold figure is the profit report's own (less what came back), so the two reports must agree for
the same window. The shelf figure is what the shop can sell now.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.profit_report import ProfitReportService
from app.core.sell_through_report import SellThroughReportService, share_of
from app.applications.apparel.modules.catalog.models import Product
from app.applications.apparel.modules.inventory.service import InventoryService
from tests.test_profit_report import DAY, NOW, _return, _sale, _variant, _wh

pytestmark = pytest.mark.asyncio


async def _stock(db, tid, wh, variant, qty):
    if not qty:
        return
    await InventoryService.move(
        db, tid, variant.id, wh.id, direction="in", quantity=qty, reason="purchase"
    )


async def _report(db, tid, **kw):
    return await SellThroughReportService.by_variant(
        db, tid, start=DAY - timedelta(days=1), end=DAY + timedelta(days=1), **kw
    )


def _row(rep, model, size):
    found = [r for r in rep["rows"] if r["model"] == model and r["size"] == size]
    assert len(found) == 1, (model, size, rep["rows"])
    return found[0]


async def _shop(db, tenant_ctx):
    """A shirt in S, M, L and a belt: S sells out, M half sells, L sits, the belt never sold."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    shirt, s = await _variant(db, tid, title="قميص", size="S")
    _, m = await _variant(db, tid, title="قميص", size="M")
    _, big = await _variant(db, tid, title="قميص", size="L")
    _, belt = await _variant(db, tid, title="حزام", size="M")
    await _stock(db, tid, wh, s, 0)
    await _stock(db, tid, wh, m, 5)
    await _stock(db, tid, wh, big, 10)
    await _stock(db, tid, wh, belt, 4)
    await _sale(db, tenant_ctx, wh, s, qty=4, net="400", cost="40")
    await _sale(db, tenant_ctx, wh, m, qty=5, net="500", cost="50")
    return {"wh": wh, "s": s, "m": m, "l": big, "belt": belt, "shirt": shirt}


# ── the share ─────────────────────────────────────────────────────────────────────────────────


def test_share_is_none_when_nothing_sold_and_nothing_left() -> None:
    assert share_of(0, 0) is None


def test_share_rounds_half_up_to_one_decimal() -> None:
    assert share_of(1, 2) == "33.3"
    assert share_of(2, 1) == "66.7"
    assert share_of(1, 7) == "12.5"
    assert share_of(1, 15) == "6.3"  # 6.25 rounds up, not to even


def test_share_is_zero_when_only_stock_and_a_hundred_when_only_sales() -> None:
    assert share_of(0, 9) == "0.0"
    assert share_of(9, 0) == "100.0"


# ── the report ────────────────────────────────────────────────────────────────────────────────


async def test_each_size_shows_what_sold_what_is_left_and_the_share(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id)
    s = _row(rep, "قميص", "S")
    assert (s["units_sold"], s["units_on_hand"], s["sold_share"]) == (4, 0, "100.0")
    m = _row(rep, "قميص", "M")
    assert (m["units_sold"], m["units_on_hand"], m["sold_share"]) == (5, 5, "50.0")


async def test_a_size_with_stock_and_no_sales_is_listed_as_the_one_that_sits(
    db, tenant_ctx
) -> None:
    await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id)
    sits = _row(rep, "قميص", "L")
    assert (sits["units_sold"], sits["units_on_hand"], sits["sold_share"]) == (0, 10, "0.0")
    belt = _row(rep, "حزام", "M")
    assert (belt["units_sold"], belt["units_on_hand"], belt["sold_share"]) == (0, 4, "0.0")


async def test_what_is_selling_out_comes_first(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id)
    order = [(r["model"], r["size"]) for r in rep["rows"]]
    assert order[0] == ("قميص", "S")
    assert order[1] == ("قميص", "M")
    assert set(order[2:]) == {("قميص", "L"), ("حزام", "M")}


async def test_totals_add_up_the_rows(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    t = (await _report(db, tenant_ctx.tenant_id))["totals"]
    assert t["units_sold"] == 9
    assert t["units_on_hand"] == 19
    assert t["sold_share"] == "32.1"  # 9 / 28


async def test_a_return_takes_its_units_off_what_sold(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    order = await _sale(db, tenant_ctx, shop["wh"], shop["l"], qty=3, net="300", cost="30")
    await _return(db, tenant_ctx, shop["wh"], order, shop["l"], qty=2, refund="200")
    rep = await _report(db, tenant_ctx.tenant_id)
    assert _row(rep, "قميص", "L")["units_sold"] == 1


async def test_it_agrees_with_the_profit_report_on_units_sold(db, tenant_ctx) -> None:
    """One source of truth: the same window gives the same units in both reports."""
    shop = await _shop(db, tenant_ctx)
    order = await _sale(db, tenant_ctx, shop["wh"], shop["m"], qty=2, net="200", cost="20")
    await _return(db, tenant_ctx, shop["wh"], order, shop["m"], qty=1, refund="100")
    tid = tenant_ctx.tenant_id
    window = {"start": DAY - timedelta(days=1), "end": DAY + timedelta(days=1)}
    profit = await ProfitReportService.by_variant(db, tid, **window)
    net = {r["variant_id"]: r["units_sold"] - r["units_returned"] for r in profit["rows"]}
    rep = await _report(db, tid)
    for r in rep["rows"]:
        if r["variant_id"] in net:
            assert r["units_sold"] == net[r["variant_id"]], r


async def test_a_sale_outside_the_window_does_not_count_but_its_stock_still_shows(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, title="جاكت", size="M")
    await _stock(db, tid, wh, v, 6)
    await _sale(db, tenant_ctx, wh, v, qty=2, net="200", cost="20", when=NOW - timedelta(days=30))
    row = _row(await _report(db, tid), "جاكت", "M")
    assert (row["units_sold"], row["units_on_hand"], row["sold_share"]) == (0, 6, "0.0")


async def test_the_end_of_the_window_is_not_included(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, title="جاكت", size="M")
    await _stock(db, tid, wh, v, 6)
    await _sale(db, tenant_ctx, wh, v, qty=2, net="200", cost="20", when=NOW)
    inside = await SellThroughReportService.by_variant(
        db, tid, start=NOW - timedelta(hours=1), end=NOW + timedelta(seconds=1)
    )
    assert _row(inside, "جاكت", "M")["units_sold"] == 2
    ends_at_the_sale = await SellThroughReportService.by_variant(
        db, tid, start=NOW - timedelta(hours=1), end=NOW
    )
    assert _row(ends_at_the_sale, "جاكت", "M")["units_sold"] == 0


async def test_stock_held_for_inspection_is_not_counted_as_left_to_sell(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, title="جاكت", size="M")
    await _stock(db, tid, wh, v, 10)
    await db.execute(
        text("update inventory_balances set quarantined = 3 where variant_id = :v"),
        {"v": v.id},
    )
    row = _row(await _report(db, tid), "جاكت", "M")
    assert row["units_on_hand"] == 7


async def test_stock_in_two_warehouses_is_added_up(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    one, two = await _wh(db, tid), await _wh(db, tid)
    _, v = await _variant(db, tid, title="جاكت", size="M")
    await _stock(db, tid, one, v, 4)
    await _stock(db, tid, two, v, 3)
    assert _row(await _report(db, tid), "جاكت", "M")["units_on_hand"] == 7


async def test_a_variant_with_no_stock_and_no_sales_is_not_a_row(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    await _variant(db, tid, title="جاكت", size="M")
    assert (await _report(db, tid))["rows"] == []


async def test_a_sold_variant_that_was_deactivated_still_shows_its_sales(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, title="جاكت", size="M")
    await _sale(db, tenant_ctx, wh, v, qty=3, net="300", cost="30")
    v.is_active = False
    await db.flush()
    row = _row(await _report(db, tid), "جاكت", "M")
    assert (row["units_sold"], row["units_on_hand"], row["sold_share"]) == (3, 0, "100.0")


async def test_an_empty_shop_is_an_empty_report(db, tenant_ctx) -> None:
    rep = await _report(db, tenant_ctx.tenant_id)
    assert rep["rows"] == []
    assert rep["totals"] == {"units_sold": 0, "units_on_hand": 0, "sold_share": None}


async def test_one_unit_sold_and_none_left_is_a_hundred_percent_not_nothing(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, title="جاكت", size="M")
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="10")
    row = _row(await _report(db, tid), "جاكت", "M")
    assert (row["units_sold"], row["units_on_hand"], row["sold_share"]) == (1, 0, "100.0")


async def test_everything_sold_and_returned_is_zero_sold_not_negative(db, tenant_ctx) -> None:
    """Two sold, both came back: nothing net sold, and the share is 0.0 rather than odd."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, title="جاكت", size="M")
    await _stock(db, tid, wh, v, 5)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="10")
    order = await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="10")
    await _return(db, tenant_ctx, wh, order, v, qty=1, refund="100")
    await _return(db, tenant_ctx, wh, order, v, qty=1, refund="100")
    row = _row(await _report(db, tid), "جاكت", "M")
    assert row["units_sold"] == 0  # 2 sold, 2 came back
    assert row["sold_share"] == "0.0"


async def test_more_held_than_on_the_shelf_never_shows_negative_stock(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, title="جاكت", size="M")
    await _stock(db, tid, wh, v, 2)
    await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="10")
    await db.execute(
        text("update inventory_balances set quarantined = 5 where variant_id = :v"),
        {"v": v.id},
    )
    row = _row(await _report(db, tid), "جاكت", "M")
    assert row["units_on_hand"] == 0
    assert row["sold_share"] == "100.0"


async def test_equal_shares_put_the_one_that_sold_more_first(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, small = await _variant(db, tid, title="قميص", size="S")
    _, big = await _variant(db, tid, title="قميص", size="XL")
    await _stock(db, tid, wh, small, 1)
    await _stock(db, tid, wh, big, 3)
    await _sale(db, tenant_ctx, wh, small, qty=1, net="100", cost="10")
    await _sale(db, tenant_ctx, wh, big, qty=3, net="300", cost="30")
    rep = await _report(db, tid)
    assert [r["size"] for r in rep["rows"]] == ["XL", "S"]
    assert rep["rows"][0]["sold_share"] == rep["rows"][1]["sold_share"] == "50.0"


async def test_the_fabric_filter_is_case_blind_on_the_shelf_too(db, tenant_ctx) -> None:
    """A fabric typed in another case still finds its stock, not just its sales."""
    await _tagged(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, material="cOtToN")
    assert [r["units_on_hand"] for r in rep["rows"]] == [5]


# ── filters ───────────────────────────────────────────────────────────────────────────────────


async def _tagged(db, tenant_ctx):
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    a, va = await _variant(db, tid, title="قميص قطن", size="M")
    b, vb = await _variant(db, tid, title="قميص كتان", size="M")
    c, vc = await _variant(db, tid, title="جاكت", size="M")
    for p, season, material in ((a, "SS26", "Cotton"), (b, "SS26", "Linen"), (c, "AW26", "Wool")):
        p.season, p.material = season, material
    await db.flush()
    for v in (va, vb, vc):
        await _stock(db, tid, wh, v, 5)
        await _sale(db, tenant_ctx, wh, v, qty=1, net="100", cost="10")


def _models(rep):
    return sorted(r["model"] for r in rep["rows"])


async def test_a_season_keeps_only_that_season(db, tenant_ctx) -> None:
    await _tagged(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, season="  ss26 ")
    assert _models(rep) == ["قميص قطن", "قميص كتان"]
    assert rep["totals"]["units_on_hand"] == 10


async def test_a_material_keeps_only_that_fabric(db, tenant_ctx) -> None:
    await _tagged(db, tenant_ctx)
    assert _models(await _report(db, tenant_ctx.tenant_id, material="COTTON")) == ["قميص قطن"]


async def test_a_brand_keeps_only_that_brand(db, tenant_ctx) -> None:
    from app.applications.apparel.modules.catalog.models import Brand

    tid = tenant_ctx.tenant_id
    await _tagged(db, tenant_ctx)
    nile = Brand(tenant_id=tid, name="نيل")
    db.add(nile)
    await db.flush()
    cotton = (
        await db.execute(Product.__table__.select().where(Product.title == "قميص قطن"))
    ).first()
    await db.execute(
        Product.__table__.update().where(Product.id == cotton.id).values(brand_id=nile.id)
    )
    assert _models(await _report(db, tid, brand_id=nile.id)) == ["قميص قطن"]


async def test_blank_filters_are_no_filter(db, tenant_ctx) -> None:
    await _tagged(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, season="", material="  ")
    assert len(rep["rows"]) == 3


async def test_filters_combine(db, tenant_ctx) -> None:
    await _tagged(db, tenant_ctx)
    rep = await _report(db, tenant_ctx.tenant_id, season="SS26", material="Linen")
    assert _models(rep) == ["قميص كتان"]


async def test_the_filtered_totals_follow_the_rows(db, tenant_ctx) -> None:
    await _tagged(db, tenant_ctx)
    t = (await _report(db, tenant_ctx.tenant_id, season="AW26"))["totals"]
    assert (t["units_sold"], t["units_on_hand"], t["sold_share"]) == (1, 5, "16.7")


async def test_another_shop_never_sees_this_shops_sales_or_stock(db, tenant_ctx) -> None:
    await _shop(db, tenant_ctx)
    rep = await _report(db, uuid.uuid4())
    assert rep["rows"] == []


# ── the route ─────────────────────────────────────────────────────────────────────────────────


def _qs(**kw) -> str:
    start = (DAY - timedelta(days=1)).isoformat()
    end = (DAY + timedelta(days=1)).isoformat()
    return f"start={start}&end={end}" + "".join(f"&{k}={v}" for k, v in kw.items())


async def test_the_route_is_manager_only(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import CASHIER, MANAGER, _call

    denied = await _call(
        db, tenant_ctx, "GET", f"/api/v1/reports/sell-through?{_qs()}", perms=CASHIER
    )
    assert denied.status_code == 403
    ok = await _call(db, tenant_ctx, "GET", f"/api/v1/reports/sell-through?{_qs()}", perms=MANAGER)
    assert ok.status_code == 200, ok.text


async def test_the_route_hands_every_filter_on_and_answers_with_the_rows(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import MANAGER, _call

    await _tagged(db, tenant_ctx)
    url = "/api/v1/reports/sell-through"
    every = await _call(db, tenant_ctx, "GET", f"{url}?{_qs()}", perms=MANAGER)
    assert len(every.json()["rows"]) == 3
    one = await _call(
        db, tenant_ctx, "GET", f"{url}?{_qs(season='ss26', material='linen')}", perms=MANAGER
    )
    body = one.json()
    assert [r["model"] for r in body["rows"]] == ["قميص كتان"]
    assert body["rows"][0]["material"] == "Linen"
    assert body["totals"]["units_sold"] == 1
    pos = await _call(db, tenant_ctx, "GET", f"{url}?{_qs(channel='nowhere')}", perms=MANAGER)
    assert [r["units_sold"] for r in pos.json()["rows"]] == [0, 0, 0]
