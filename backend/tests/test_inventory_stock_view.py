"""The stock screen reads ONE joined view: name, options, barcode, cost, on-hand, the reorder rule.

The raw /inventory/balances row is only (variant, warehouse, on_hand, reserved): a screen built on
it shows a table of numbers with no names. Everything the screen needs is joined here, and the
status (in / low / out) is decided in ONE place, the backend, so the grid, the CSV export and the
dashboard alert count cannot drift apart.

Rules these tests pin down:
  * out  : on_hand <= 0
  * low  : 0 < on_hand <= reorder_level          (reorder_level 0 means "no alert", never "low")
  * in   : otherwise
  * on_hand is summed over warehouses (one shop first), reserved is reported separately
  * cost is the moving average; an UNKNOWN cost is null, never 0 (a 0 would value the shelf at
    nothing and make every margin look 100%)
  * an inactive variant never shows as a stock line
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.modules.catalog.service import CatalogService
from app.modules.inventory.service import InventoryService
from app.modules.inventory.stock_view import StockLevelService
from app.modules.pos.stock_view import StockViewService
from tests.test_pos_returns import _warehouse

pytestmark = pytest.mark.asyncio


async def _variant(db, tenant_ctx, *, stock, title="تيشيرت", options=None, price="100.00"):
    warehouse = await _warehouse(db, tenant_ctx)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title=title, slug=f"p-{uuid.uuid4().hex[:10]}"
    )
    variant = await CatalogService.add_variant(
        db,
        tenant_ctx.tenant_id,
        product.id,
        sku=f"SKU-{uuid.uuid4().hex[:8]}",
        option_values=options or {"color": "أسود", "size": "L"},
        price=price,
    )
    if stock:
        await InventoryService.move(
            db, tenant_ctx.tenant_id, variant.id, warehouse.id,
            direction="in", quantity=stock, reason="purchase",
        )  # fmt: skip
    return product, variant, warehouse


async def _row(db, tenant_ctx, variant):
    rows = await StockViewService.list_stock(db, tenant_ctx.tenant_id)
    mine = [r for r in rows if r["variant_id"] == str(variant.id)]
    assert len(mine) == 1
    return mine[0]


async def test_a_row_carries_everything_the_screen_prints(db, tenant_ctx):
    product, variant, _w = await _variant(db, tenant_ctx, stock=7)
    await CatalogService.add_identifier(
        db, tenant_ctx.tenant_id, variant.id, "barcode", "6221234567890"
    )
    row = await _row(db, tenant_ctx, variant)
    assert row["product_title"] == "تيشيرت"
    assert row["product_id"] == str(product.id)
    assert row["sku"] == variant.sku
    assert row["options"] == {"color": "أسود", "size": "L"}
    assert row["barcode"] == "6221234567890"
    assert row["price"] == "100.00"
    assert row["on_hand"] == 7
    assert row["reserved"] == 0


@pytest.mark.parametrize(
    ("stock", "level", "status"),
    [
        (0, 5, "out"),
        (1, 5, "low"),
        (5, 5, "low"),  # at the level is already low
        (6, 5, "in"),
        (3, 0, "in"),  # level 0 = no alert configured, never "low"
        (0, 0, "out"),
    ],
)
async def test_status_follows_the_reorder_level(db, tenant_ctx, stock, level, status):
    _p, variant, _w = await _variant(db, tenant_ctx, stock=stock)
    await StockLevelService.set_reorder_level(db, tenant_ctx.tenant_id, variant.id, level)
    row = await _row(db, tenant_ctx, variant)
    assert row["reorder_level"] == level
    assert row["status"] == status


async def test_on_hand_is_summed_across_warehouses(db, tenant_ctx):
    _p, variant, w1 = await _variant(db, tenant_ctx, stock=4)
    from app.modules.inventory.models import Warehouse

    w2 = Warehouse(tenant_id=tenant_ctx.tenant_id, name="مخزن ٢", code=f"W{uuid.uuid4().hex[:5]}")
    db.add(w2)
    await db.flush()
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, w2.id,
        direction="in", quantity=6, reason="purchase",
    )  # fmt: skip
    assert (await _row(db, tenant_ctx, variant))["on_hand"] == 10
    assert w1.id != w2.id


async def test_unknown_cost_is_null_not_zero(db, tenant_ctx):
    _p, variant, _w = await _variant(db, tenant_ctx, stock=3)
    row = await _row(db, tenant_ctx, variant)
    assert row["avg_cost"] is None
    assert row["stock_cost_value"] is None  # cannot value stock whose cost is unknown


async def test_a_known_cost_values_the_stock(db, tenant_ctx):
    from app.modules.purchasing.models import VariantCost

    _p, variant, _w = await _variant(db, tenant_ctx, stock=4)
    db.add(VariantCost(tenant_id=tenant_ctx.tenant_id, variant_id=variant.id, avg_cost="12.5000"))
    await db.flush()
    row = await _row(db, tenant_ctx, variant)
    assert Decimal(row["avg_cost"]) == Decimal("12.5000")
    assert Decimal(row["stock_cost_value"]) == Decimal("50.00")
    assert Decimal(row["stock_retail_value"]) == Decimal("400.00")


async def test_a_variant_with_no_movements_still_appears_with_zero(db, tenant_ctx):
    _p, variant, _w = await _variant(db, tenant_ctx, stock=0)
    row = await _row(db, tenant_ctx, variant)
    assert row["on_hand"] == 0
    assert row["status"] == "out"


async def test_an_inactive_variant_is_not_a_stock_line(db, tenant_ctx):
    _p, variant, _w = await _variant(db, tenant_ctx, stock=5)
    variant.is_active = False
    await db.flush()
    rows = await StockViewService.list_stock(db, tenant_ctx.tenant_id)
    assert all(r["variant_id"] != str(variant.id) for r in rows)


async def test_reorder_level_must_be_a_non_negative_whole_number(db, tenant_ctx):
    _p, variant, _w = await _variant(db, tenant_ctx, stock=1)
    for bad in (-1, 1.5, "3", True, None, 10**9):
        with pytest.raises(ValidationError):
            await StockLevelService.set_reorder_level(db, tenant_ctx.tenant_id, variant.id, bad)


async def test_setting_the_level_twice_keeps_one_row(db, tenant_ctx):
    _p, variant, _w = await _variant(db, tenant_ctx, stock=1)
    await StockLevelService.set_reorder_level(db, tenant_ctx.tenant_id, variant.id, 3)
    await StockLevelService.set_reorder_level(db, tenant_ctx.tenant_id, variant.id, 8)
    assert (await _row(db, tenant_ctx, variant))["reorder_level"] == 8


async def test_the_summary_counts_alerts_and_values_only_known_cost(db, tenant_ctx):
    from app.modules.purchasing.models import VariantCost

    _p, low, _w = await _variant(db, tenant_ctx, stock=2)
    _p, out, _w = await _variant(db, tenant_ctx, stock=0)
    _p, fine, _w = await _variant(db, tenant_ctx, stock=50)
    await StockLevelService.set_reorder_level(db, tenant_ctx.tenant_id, low.id, 5)
    db.add(VariantCost(tenant_id=tenant_ctx.tenant_id, variant_id=low.id, avg_cost="10.0000"))
    await db.flush()
    summary = await StockViewService.summary(db, tenant_ctx.tenant_id)
    assert summary["low"] == 1
    assert summary["out"] == 1
    assert summary["alerts"] == 2
    assert summary["pieces"] == 52
    assert Decimal(summary["cost_value"]) == Decimal("20.00")  # only the variant with a known cost
    assert summary["unknown_cost_variants"] == 2  # `out` and `fine`; `out` holds 0 pieces but
    # is still a variant whose cost nobody recorded: the screen shows "n unpriced", not a silent 0
    assert fine.id != out.id


async def test_a_variant_nobody_configured_is_never_reported_low(db, tenant_ctx):
    """No settings row at all reads as level 0 = no alert, even with only one piece left."""
    _p, variant, _w = await _variant(db, tenant_ctx, stock=1)
    row = await _row(db, tenant_ctx, variant)
    assert row["reorder_level"] == 0
    assert row["status"] == "in"


# ------------------- the routes, with the permissions the roles really hold -----


async def _ctx(db, tenant_ctx, role_code):
    from tests._pos_helpers import ctx_for as _ctx_for

    return await _ctx_for(db, tenant_ctx, role_code)


async def test_any_staff_member_can_read_the_stock_but_not_change_a_level(db, tenant_ctx):
    """The gate lives in Depends(), so calling the route function skips it. Run it explicitly."""
    from app.core.errors import PermissionDeniedError
    from app.modules.identity.deps import require_permission
    from app.modules.pos.router import list_stock, stock_summary

    _p, variant, _w = await _variant(db, tenant_ctx, stock=2)
    staff = await _ctx(db, tenant_ctx, "staff")
    manager = await _ctx(db, tenant_ctx, "manager")

    rows = await list_stock(staff)
    assert any(r["variant_id"] == str(variant.id) for r in rows)
    assert (await stock_summary(staff))["variants"] >= 1

    gate = require_permission("inventory:write")
    with pytest.raises(PermissionDeniedError):
        await gate(staff)
    assert await gate(manager) is manager


async def test_the_put_route_sets_the_level_and_rejects_a_bad_body(db, tenant_ctx):
    from pydantic import ValidationError as BodyError

    from app.modules.pos.router import ReorderLevelRequest, set_reorder_level

    _p, variant, _w = await _variant(db, tenant_ctx, stock=2)
    manager = await _ctx(db, tenant_ctx, "manager")
    out = await set_reorder_level(variant.id, ReorderLevelRequest(reorder_level=4), manager)
    assert out.reorder_level == 4
    assert (await _row(db, tenant_ctx, variant))["status"] == "low"

    for bad in (-1, 2.5, "3", True, 1_000_001):
        with pytest.raises(BodyError):
            ReorderLevelRequest(reorder_level=bad)


async def test_setting_a_level_for_a_variant_of_another_tenant_is_not_found(db, tenant_ctx):
    from app.modules.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await StockLevelService.set_reorder_level(db, tenant_ctx.tenant_id, uuid.uuid4(), 3)


async def test_filtering_by_status_and_search_term(db, tenant_ctx):
    _p, low, _w = await _variant(db, tenant_ctx, stock=1, title="قميص نادر")
    _p, fine, _w = await _variant(db, tenant_ctx, stock=40, title="بنطلون عادي")
    await StockLevelService.set_reorder_level(db, tenant_ctx.tenant_id, low.id, 3)
    await CatalogService.add_identifier(db, tenant_ctx.tenant_id, fine.id, "ean", "5012345678900")

    lows = await StockViewService.list_stock(db, tenant_ctx.tenant_id, status="low")
    assert [r["variant_id"] for r in lows] == [str(low.id)]
    by_name = await StockViewService.list_stock(db, tenant_ctx.tenant_id, term="نادر")
    assert [r["variant_id"] for r in by_name] == [str(low.id)]
    by_code = await StockViewService.list_stock(db, tenant_ctx.tenant_id, term="5012345678")
    assert [r["variant_id"] for r in by_code] == [str(fine.id)]
    with pytest.raises(ValidationError):
        await StockViewService.list_stock(db, tenant_ctx.tenant_id, status="broken")


def _gate_codes(path: str, method: str) -> set[str]:
    """The permission codes a LIVE route is wired to (the gate sits in Depends, not in the body)."""
    from app.modules.identity.deps import require_permission
    from app.modules.pos.router import router

    found: set[str] = set()
    for route in router.routes:
        if getattr(route, "path", None) != path or method not in route.methods:
            continue
        stack = list(route.dependant.dependencies)
        while stack:
            dep = stack.pop()
            if isinstance(dep.call, require_permission):
                found.add(dep.call.code)
            stack.extend(dep.dependencies)
        return found
    raise AssertionError(f"no {method} {path} on the pos router")


async def test_changing_a_level_is_wired_to_inventory_write_on_the_live_route():
    """Without this, deleting the Depends(...) on the PUT leaves every other test green."""
    assert _gate_codes("/pos/stock/{variant_id}/reorder-level", "PUT") == {"inventory:write"}


async def test_the_read_routes_do_not_demand_the_write_permission():
    assert "inventory:write" not in _gate_codes("/pos/stock", "GET")
    assert "inventory:write" not in _gate_codes("/pos/stock/summary", "GET")


async def test_the_stored_level_reads_back_and_unset_reads_zero(db, tenant_ctx):
    _p, variant, _w = await _variant(db, tenant_ctx, stock=1)
    assert await StockLevelService.get_reorder_level(db, tenant_ctx.tenant_id, variant.id) == 0
    await StockLevelService.set_reorder_level(db, tenant_ctx.tenant_id, variant.id, 9)
    assert await StockLevelService.get_reorder_level(db, tenant_ctx.tenant_id, variant.id) == 9


def test_the_cost_table_shape_matches_purchasing():
    """pos reads variant_costs via a light table (no purchasing import); keep the two in step."""
    from app.modules.pos.stock_view import VariantCost as light
    from app.modules.purchasing.models import VariantCost as real

    assert light.name == real.__tablename__
    real_columns = {c.name for c in real.__table__.columns}
    assert {c.name for c in light.c} <= real_columns


async def test_the_inventory_tables_pos_reads_match_inventory():
    """pos reads inventory_balances / variant_stock_settings as light tables; keep them in step."""
    from app.modules.inventory.models import InventoryBalance as balance
    from app.modules.inventory.models import VariantStockSetting as setting
    from app.modules.pos.stock_view import InventoryBalance as light_balance
    from app.modules.pos.stock_view import VariantStockSetting as light_setting

    for light, real in ((light_balance, balance), (light_setting, setting)):
        assert light.name == real.__tablename__
        assert {c.name for c in light.c} <= {c.name for c in real.__table__.columns}
