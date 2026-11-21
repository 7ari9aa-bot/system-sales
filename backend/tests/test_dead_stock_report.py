"""Dead stock: stock on the shelf that has not sold for the shop's own number of days.

The stock ledger is append-only (the app role cannot UPDATE inventory_movements), so a stock-in
cannot be back-dated. Time is moved the other way: every test measures from the real moment its
stock arrived (``t0``) and asks the report what it thinks at ``t0 + age``. A sale is placed with an
explicit ``placed_at`` relative to that same clock, so the boundary day is exact.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.dead_stock_report import DeadStockReportService
from app.modules.inventory.service import InventoryService
from app.modules.settings.registry import ENFORCED_KEYS, REGISTRY
from app.modules.settings.service import SettingsService
from tests.test_profit_report import _return, _sale, _variant, _wh

pytestmark = pytest.mark.asyncio


class Shop:
    """One shop's clock: ``now`` is the report's 'today', moved to suit each test."""

    def __init__(self) -> None:
        self.t0: datetime | None = None
        self.now: datetime | None = None

    def at(self, days_after_arrival: float) -> None:
        assert self.t0 is not None
        self.now = self.t0 + timedelta(days=days_after_arrival)

    def ago(self, days: float) -> datetime:
        assert self.now is not None
        return self.now - timedelta(days=days)


async def _stock(db, tid, wh, variant, qty, shop: Shop) -> None:
    await InventoryService.move(
        db, tid, variant.id, wh.id, direction="in", quantity=qty, reason="purchase"
    )
    got = (
        await db.execute(
            text(
                "select min(created_at) from inventory_movements"
                " where variant_id = :v and direction = 'in'"
            ),
            {"v": variant.id},
        )
    ).scalar()
    if shop.t0 is None or got < shop.t0:
        shop.t0 = got


async def _cost(db, tid, variant, avg):
    from decimal import Decimal

    from app.modules.purchasing.models import VariantCost

    db.add(VariantCost(tenant_id=tid, variant_id=variant.id, avg_cost=Decimal(str(avg))))
    await db.flush()


async def _dead(db, tid, shop: Shop, **kw):
    return await DeadStockReportService.report(db, tid, now=shop.now, **kw)


def _sizes(rep):
    return sorted(r["size"] for r in rep["rows"])


async def _one(db, tenant_ctx, shop, *, size="M", qty=5, cost=None):
    """A size with stock that has just arrived (t0). Sales are added by the test."""
    tid = tenant_ctx.tenant_id
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, size=size)
    await _stock(db, tid, wh, v, qty, shop)
    if cost is not None:
        await _cost(db, tid, v, cost)
    return wh, v


async def _sell(db, tenant_ctx, shop, wh, v, days_ago, **kw):
    """A sale placed ``days_ago`` before the report's 'today'."""
    return await _sale(
        db, tenant_ctx, wh, v, qty=1, net="100", cost="10", when=shop.ago(days_ago), **kw
    )


# ── the setting ───────────────────────────────────────────────────────────────────────────────


def test_the_setting_is_registered_with_the_agreed_bounds() -> None:
    d = REGISTRY["inventory.dead_stock_days"]
    assert (d.default, d.min_value, d.max_value) == (60, 7, 730)
    assert "inventory.dead_stock_days" in ENFORCED_KEYS


async def test_the_shops_own_setting_decides_how_long_is_too_long(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop)
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, v, 40)
    assert (await _dead(db, tid, shop))["rows"] == []  # default 60 days: 40 is fine
    await SettingsService(db, tid).set("inventory.dead_stock_days", 30)
    rep = await _dead(db, tid, shop)
    assert rep["days"] == 30 and len(rep["rows"]) == 1


async def test_the_days_override_beats_the_setting_for_one_look(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop)
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, v, 40)
    assert len((await _dead(db, tid, shop, days=30))["rows"]) == 1
    assert (await _dead(db, tid, shop, days=45))["rows"] == []


# ── the boundary day ──────────────────────────────────────────────────────────────────────────


async def test_a_last_sale_exactly_n_days_ago_is_not_dead_and_one_more_second_is(
    db, tenant_ctx
) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, small = await _one(db, tenant_ctx, shop, size="S")
    _, large = await _one(db, tenant_ctx, shop, size="L")
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, small, 60)
    assert _sizes(await _dead(db, tid, shop)) == ["L"]  # S is on the line, L never sold
    await _sale(
        db, tenant_ctx, wh, large, qty=1, net="100", cost="10",
        when=shop.ago(60) - timedelta(seconds=1),
    )  # fmt: skip
    assert _sizes(await _dead(db, tid, shop)) == ["L"]
    shop.now += timedelta(seconds=1)  # one more second and S crosses the line too
    assert _sizes(await _dead(db, tid, shop)) == ["L", "S"]


async def test_a_sale_the_day_before_the_boundary_is_not_dead(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop)
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, v, 59)
    assert (await _dead(db, tid, shop))["rows"] == []


async def test_sold_yesterday_is_never_dead(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop)
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, v, 1)
    assert (await _dead(db, tid, shop))["rows"] == []


# ── never sold ────────────────────────────────────────────────────────────────────────────────


async def test_never_sold_old_stock_is_dead_and_shows_no_last_sale(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    await _one(db, tenant_ctx, shop)
    shop.at(100)
    row = (await _dead(db, tid, shop))["rows"][0]
    assert row["last_sold_at"] is None and row["days_since_last_sale"] is None


async def test_never_sold_new_stock_is_not_dead_yet(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    await _one(db, tenant_ctx, shop)
    shop.at(10)
    assert (await _dead(db, tid, shop))["rows"] == []


async def test_never_sold_stock_that_arrived_exactly_n_days_ago_is_not_dead(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    await _one(db, tenant_ctx, shop)
    shop.at(60)
    assert (await _dead(db, tid, shop))["rows"] == []
    shop.now += timedelta(seconds=1)
    assert len((await _dead(db, tid, shop))["rows"]) == 1


async def test_never_sold_age_counts_from_the_first_stock_in_not_the_latest(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop, qty=3)
    shop.at(200)
    await InventoryService.move(
        db, tid, v.id, wh.id, direction="in", quantity=2, reason="purchase"
    )  # a top-up made "today" does not make the old stock new
    assert len((await _dead(db, tid, shop))["rows"]) == 1


# ── what does not count ───────────────────────────────────────────────────────────────────────


async def test_a_size_with_no_stock_is_not_listed(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, size="M")
    shop.t0 = datetime.now(UTC)
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, v, 200)
    assert (await _dead(db, tid, shop))["rows"] == []


async def test_stock_held_for_inspection_is_not_sellable_so_not_listed(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    _, v = await _one(db, tenant_ctx, shop, qty=4)
    await db.execute(
        text("update inventory_balances set quarantined = 4 where variant_id = :v"), {"v": v.id}
    )
    shop.at(300)
    assert (await _dead(db, tid, shop))["rows"] == []


async def test_only_the_sellable_units_are_counted(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    _, v = await _one(db, tenant_ctx, shop, qty=10)
    await db.execute(
        text("update inventory_balances set quarantined = 3 where variant_id = :v"), {"v": v.id}
    )
    shop.at(300)
    assert (await _dead(db, tid, shop))["rows"][0]["units_on_hand"] == 7


async def test_a_return_is_not_a_sale_and_does_not_restart_the_clock(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop)
    shop.at(300)
    order = await _sell(db, tenant_ctx, shop, wh, v, 100)
    await _return(db, tenant_ctx, wh, order, v, qty=1, refund="100")
    # the till helper also stocks an unrelated product, so find this variant by id
    mine = [r for r in (await _dead(db, tid, shop))["rows"] if r["variant_id"] == str(v.id)]
    assert [r["days_since_last_sale"] for r in mine] == [100]


async def test_a_cancelled_or_draft_order_is_not_a_sale(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop)
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, v, 100)
    await _sell(db, tenant_ctx, shop, wh, v, 2, status="cancelled")
    await _sell(db, tenant_ctx, shop, wh, v, 1, status="draft")
    assert (await _dead(db, tid, shop))["rows"][0]["days_since_last_sale"] == 100


async def test_the_latest_of_several_sales_is_the_one_that_counts(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop)
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, v, 200)
    await _sell(db, tenant_ctx, shop, wh, v, 20)
    assert (await _dead(db, tid, shop))["rows"] == []


async def test_a_deactivated_variant_is_not_listed(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    _, v = await _one(db, tenant_ctx, shop)
    v.is_active = False
    await db.flush()
    shop.at(300)
    assert (await _dead(db, tid, shop))["rows"] == []


# ── when stock arrived: the first "in" movement, else the variant's own birth ─────────────────


async def _seed_balance(db, tid, wh, v, on_hand):
    """Stock that came in without any ledger movement (as an opening import can leave it)."""
    await db.execute(
        text(
            "insert into inventory_balances (id, tenant_id, warehouse_id, variant_id, on_hand,"
            " reserved, quarantined) values (:id, :t, :w, :v, :n, 0, 0)"
        ),
        {"id": uuid.uuid4(), "t": tid, "w": wh.id, "v": v.id, "n": on_hand},
    )


async def test_stock_with_no_stock_in_movement_ages_from_the_variants_own_birth(
    db, tenant_ctx
) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, size="M")
    await _seed_balance(db, tid, wh, v, 5)
    born = (
        await db.execute(text("select created_at from product_variants where id = :v"), {"v": v.id})
    ).scalar()
    shop.t0 = born
    shop.at(59)
    assert (await _dead(db, tid, shop))["rows"] == []  # born 59 days ago: not dead yet
    shop.at(61)
    assert len((await _dead(db, tid, shop))["rows"]) == 1


async def _movement(db, tid, wh, v, *, direction, at):
    """A ledger row with an explicit time (an INSERT may carry one; an UPDATE is not allowed)."""
    from app.modules.inventory.models import InventoryMovement

    db.add(
        InventoryMovement(
            tenant_id=tid,
            variant_id=v.id,
            warehouse_id=wh.id,
            direction=direction,
            quantity=1,
            reason="purchase" if direction == "in" else "adjustment",
            balance_after=0,
            created_at=at,
        )
    )
    await db.flush()


async def test_age_counts_from_the_oldest_of_several_stock_ins(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, size="M")
    await _seed_balance(db, tid, wh, v, 5)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await _movement(db, tid, wh, v, direction="in", at=base)  # the first arrival
    await _movement(db, tid, wh, v, direction="in", at=base + timedelta(days=80))  # a top-up
    shop.now = base + timedelta(days=90)  # 90 days since the first, only 10 since the top-up
    assert len((await _dead(db, tid, shop))["rows"]) == 1


async def test_a_very_old_out_movement_does_not_date_the_stock(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, size="M")
    await _seed_balance(db, tid, wh, v, 5)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await _movement(db, tid, wh, v, direction="out", at=base - timedelta(days=400))
    await _movement(db, tid, wh, v, direction="in", at=base + timedelta(days=80))
    shop.now = base + timedelta(days=90)  # the only arrival is 10 days old
    assert (await _dead(db, tid, shop))["rows"] == []


async def test_an_out_movement_is_not_an_arrival(db, tenant_ctx) -> None:
    """Only an 'in' movement dates the stock; a later 'out' must not make old stock look new."""
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop, qty=10)
    await InventoryService.move(
        db, tid, v.id, wh.id, direction="out", quantity=1, reason="adjustment"
    )
    shop.at(100)
    mine = [r for r in (await _dead(db, tid, shop))["rows"] if r["variant_id"] == str(v.id)]
    assert len(mine) == 1 and mine[0]["units_on_hand"] == 9


async def test_a_shelf_count_below_zero_is_never_listed_or_counted(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh = await _wh(db, tid)
    _, v = await _variant(db, tid, size="M")
    await _seed_balance(db, tid, wh, v, 0)
    await db.execute(
        text("update inventory_balances set on_hand = 1, quarantined = 4 where variant_id = :v"),
        {"v": v.id},
    )
    shop.t0 = datetime.now(UTC)
    shop.at(300)
    rep = await _dead(db, tid, shop)
    assert rep["rows"] == [] and rep["totals"]["units_on_hand"] == 0


# ── money ─────────────────────────────────────────────────────────────────────────────────────


async def test_value_at_cost_is_units_times_cost(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    await _one(db, tenant_ctx, shop, qty=4, cost="12.50")
    shop.at(300)
    rep = await _dead(db, tid, shop)
    row = rep["rows"][0]
    assert (row["cost_known"], row["unit_cost"], row["stock_value_at_cost"]) == (
        True,
        "12.50",
        "50.00",
    )
    assert rep["totals"]["stock_value_at_cost"] == "50.00"
    assert rep["totals"]["cost_is_complete"] is True


async def test_an_unknown_cost_is_flagged_and_never_priced_at_zero(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    await _one(db, tenant_ctx, shop, size="S", qty=2)
    await _one(db, tenant_ctx, shop, size="L", qty=4, cost="10")
    shop.at(300)
    rep = await _dead(db, tid, shop)
    unknown = [r for r in rep["rows"] if r["size"] == "S"][0]
    assert unknown["cost_known"] is False
    assert unknown["unit_cost"] is None and unknown["stock_value_at_cost"] is None
    t = rep["totals"]
    assert t["variants_without_cost"] == 1 and t["cost_is_complete"] is False
    assert t["stock_value_at_cost"] == "40.00"  # the known part only


async def test_cost_is_rounded_half_up_to_the_cent(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    await _one(db, tenant_ctx, shop, qty=1, cost="10.005")
    shop.at(300)
    assert (await _dead(db, tid, shop))["rows"][0]["stock_value_at_cost"] == "10.01"


# ── order and totals ──────────────────────────────────────────────────────────────────────────


async def test_the_most_money_tied_up_comes_first_unknown_cost_last(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    await _one(db, tenant_ctx, shop, size="S", qty=1, cost="10")
    await _one(db, tenant_ctx, shop, size="M", qty=9, cost="10")
    await _one(db, tenant_ctx, shop, size="L", qty=50)
    shop.at(300)
    assert [r["size"] for r in (await _dead(db, tid, shop))["rows"]] == ["M", "S", "L"]


async def test_equal_value_puts_the_longest_unsold_first_and_never_sold_oldest(
    db, tenant_ctx
) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, s = await _one(db, tenant_ctx, shop, size="S", qty=1, cost="10")
    _, m = await _one(db, tenant_ctx, shop, size="M", qty=1, cost="10")
    await _one(db, tenant_ctx, shop, size="L", qty=1, cost="10")
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, s, 70)
    await _sell(db, tenant_ctx, shop, wh, m, 200)
    assert [r["size"] for r in (await _dead(db, tid, shop))["rows"]] == ["L", "M", "S"]


async def test_days_since_last_sale_is_whole_days(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    wh, v = await _one(db, tenant_ctx, shop)
    shop.at(300)
    await _sell(db, tenant_ctx, shop, wh, v, 75.9)
    assert (await _dead(db, tid, shop))["rows"][0]["days_since_last_sale"] == 75


async def test_totals_add_the_rows_and_an_empty_shop_is_empty(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    shop.t0 = datetime.now(UTC)
    shop.at(300)
    empty = await _dead(db, tid, shop)
    assert empty["rows"] == []
    assert empty["totals"] == {
        "variants": 0,
        "units_on_hand": 0,
        "stock_value_at_cost": "0.00",
        "variants_without_cost": 0,
        "cost_is_complete": True,
    }
    shop2 = Shop()
    await _one(db, tenant_ctx, shop2, size="S", qty=2, cost="10")
    await _one(db, tenant_ctx, shop2, size="L", qty=3, cost="10")
    shop2.at(300)
    t = (await _dead(db, tid, shop2))["totals"]
    assert (t["variants"], t["units_on_hand"], t["stock_value_at_cost"]) == (2, 5, "50.00")


async def test_another_shop_sees_nothing_of_this_shop(db, tenant_ctx) -> None:
    shop = Shop()
    await _one(db, tenant_ctx, shop)
    shop.at(300)
    assert (await _dead(db, uuid.uuid4(), shop))["rows"] == []


async def test_the_days_asked_for_are_kept_inside_the_limits(db, tenant_ctx) -> None:
    tid, shop = tenant_ctx.tenant_id, Shop()
    shop.t0 = datetime.now(UTC)
    shop.at(1)
    assert (await _dead(db, tid, shop, days=1))["days"] == 7
    assert (await _dead(db, tid, shop, days=99999))["days"] == 730


# ── the route ─────────────────────────────────────────────────────────────────────────────────


async def test_the_route_is_manager_only_and_checks_the_days(db, tenant_ctx) -> None:
    from tests.test_pos_close_variance_discipline import CASHIER, MANAGER, _call

    url = "/api/v1/reports/dead-stock"
    assert (await _call(db, tenant_ctx, "GET", url, perms=CASHIER)).status_code == 403
    ok = await _call(db, tenant_ctx, "GET", url, perms=MANAGER)
    assert ok.status_code == 200, ok.text
    assert ok.json()["days"] == 60
    assert (await _call(db, tenant_ctx, "GET", f"{url}?days=3", perms=MANAGER)).status_code == 422
    assert (
        await _call(db, tenant_ctx, "GET", f"{url}?days=9999", perms=MANAGER)
    ).status_code == 422
    seven = await _call(db, tenant_ctx, "GET", f"{url}?days=7", perms=MANAGER)
    assert seven.json()["days"] == 7
