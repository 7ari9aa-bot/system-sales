"""``si_stock_status``: what is left in the shop, as the owner assistant sees it.

The assistant had no inventory tool at all, so "what is running out?" could not be answered. The
numbers here are computed in SQL; the model only explains them. The rules that matter:

* available = max(on_hand - reserved, 0) PER WAREHOUSE, then summed. A warehouse that is oversold
  must not eat the stock another warehouse really has (same rule the website catalog uses, so the
  two screens never disagree).
* a variant with NO balance row is "not tracked", never "0": zero means sold out, and telling the
  owner an untracked item is sold out would be a false alarm about their own shop.
* "running low" is the shop's own ``reorder_level``. 0 means the owner set none, so such a variant
  is never called low (it can still be out).
* inactive variants and non-active products are not part of the shop's stock.
* read-only, tenant-scoped, and shown only to someone holding ``inventory:read``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.modules.ai.agents.sales_intelligence.tools import _si_stock_status
from app.modules.ai.tools import get_tool
from app.modules.catalog.models import Product, ProductVariant
from app.modules.customers.models import Customer
from app.modules.inventory.models import InventoryBalance, VariantStockSetting, Warehouse

pytestmark = pytest.mark.usefixtures("db")


async def _warehouse(db, tenant_id, code="W1") -> Warehouse:
    wh = Warehouse(tenant_id=tenant_id, name=f"Warehouse {code}", code=code)
    db.add(wh)
    await db.flush()
    return wh


async def _variant(db, tenant_id, title, *, sku=None, active=True, status="active", options=None):
    product = Product(
        tenant_id=tenant_id,
        title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        status=status,
    )
    db.add(product)
    await db.flush()
    variant = ProductVariant(
        tenant_id=tenant_id,
        product_id=product.id,
        sku=sku or f"SKU-{uuid.uuid4().hex[:6]}",
        title=title,
        option_values=options or {},
        price=100,
        is_active=active,
    )
    db.add(variant)
    await db.flush()
    return variant


async def _stock(db, tenant_id, wh, variant, on_hand, reserved=0):
    db.add(
        InventoryBalance(
            tenant_id=tenant_id,
            warehouse_id=wh.id,
            variant_id=variant.id,
            on_hand=on_hand,
            reserved=reserved,
        )
    )
    await db.flush()


async def _reorder(db, tenant_id, variant, level):
    db.add(VariantStockSetting(tenant_id=tenant_id, variant_id=variant.id, reorder_level=level))
    await db.flush()


async def _run(db, tenant_id, **kw) -> dict:
    return await _si_stock_status(db, tenant_id, **kw)


def _by_title(result: dict, bucket: str) -> dict[str, dict]:
    return {row["title"]: row for row in result["summary"][bucket]}


async def test_available_is_on_hand_minus_reserved(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    v = await _variant(db, t, "Blue Shirt", options={"size": "M", "color": "blue"})
    await _stock(db, t, wh, v, on_hand=10, reserved=3)
    result = await _run(db, t)
    row = _by_title(result, "items")["Blue Shirt"]
    assert (row["available"], row["on_hand"], row["reserved"]) == (7, 10, 3)
    assert (row["size"], row["color"]) == ("M", "blue")


async def test_an_oversold_warehouse_does_not_eat_another_warehouses_stock(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    w1, w2 = await _warehouse(db, t, "W1"), await _warehouse(db, t, "W2")
    v = await _variant(db, t, "Hat")
    await _stock(db, t, w1, v, on_hand=2, reserved=5)  # oversold here: contributes 0, not -3
    await _stock(db, t, w2, v, on_hand=4, reserved=0)
    row = _by_title(await _run(db, t), "items")["Hat"]
    assert row["available"] == 4


async def test_a_variant_with_no_balance_row_is_not_tracked_rather_than_sold_out(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _warehouse(db, t)
    await _variant(db, t, "Untracked Scarf")
    result = await _run(db, t)
    assert "Untracked Scarf" not in _by_title(result, "out_of_stock")
    assert "Untracked Scarf" in _by_title(result, "not_tracked")
    assert result["summary"]["counts"]["not_tracked"] == 1


async def test_zero_available_is_out_of_stock(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    v = await _variant(db, t, "Gone Belt")
    await _stock(db, t, wh, v, on_hand=3, reserved=3)
    assert "Gone Belt" in _by_title(await _run(db, t), "out_of_stock")


async def test_low_stock_uses_the_shops_own_reorder_level(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    low = await _variant(db, t, "Low Socks")
    fine = await _variant(db, t, "Fine Socks")
    await _stock(db, t, wh, low, on_hand=4)
    await _stock(db, t, wh, fine, on_hand=40)
    await _reorder(db, t, low, 5)
    await _reorder(db, t, fine, 5)
    result = await _run(db, t)
    assert "Low Socks" in _by_title(result, "low_stock")
    assert "Fine Socks" not in _by_title(result, "low_stock")
    assert _by_title(result, "low_stock")["Low Socks"]["reorder_level"] == 5


async def test_the_reorder_level_itself_counts_as_low(db, tenant_ctx):
    """ "Reorder when you reach 5" means at 5, not only below it."""
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    v = await _variant(db, t, "Edge Cap")
    await _stock(db, t, wh, v, on_hand=5)
    await _reorder(db, t, v, 5)
    assert "Edge Cap" in _by_title(await _run(db, t), "low_stock")


async def test_no_reorder_level_means_never_low_but_can_still_be_out(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    few = await _variant(db, t, "Few Gloves")
    none = await _variant(db, t, "None Gloves")
    await _stock(db, t, wh, few, on_hand=1)  # no setting row at all
    await _stock(db, t, wh, none, on_hand=0)
    await _reorder(db, t, none, 0)  # explicit 0 = the owner set no level
    result = await _run(db, t)
    assert "Few Gloves" not in _by_title(result, "low_stock")
    assert "None Gloves" not in _by_title(result, "low_stock")
    assert "None Gloves" in _by_title(result, "out_of_stock")


async def test_an_out_of_stock_variant_is_not_also_listed_as_low(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    v = await _variant(db, t, "Zero Tie")
    await _stock(db, t, wh, v, on_hand=0)
    await _reorder(db, t, v, 5)
    result = await _run(db, t)
    assert "Zero Tie" in _by_title(result, "out_of_stock")
    assert "Zero Tie" not in _by_title(result, "low_stock")


async def test_inactive_variants_and_non_active_products_are_not_the_shops_stock(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    off = await _variant(db, t, "Retired Coat", active=False)
    draft = await _variant(db, t, "Draft Coat", status="draft")
    live = await _variant(db, t, "Live Coat")
    for v in (off, draft, live):
        await _stock(db, t, wh, v, on_hand=0)
    titles = {r["title"] for r in _by_title(await _run(db, t), "out_of_stock").values()}
    assert titles == {"Live Coat"}


async def test_stagnant_means_stock_on_hand_that_has_not_sold_in_the_window(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    sleeping = await _variant(db, t, "Sleeping Bag")
    selling = await _variant(db, t, "Selling Bag")
    for v in (sleeping, selling):
        await _stock(db, t, wh, v, on_hand=9)
    await _sell(db, t, selling, days_ago=3)
    result = await _run(db, t, stagnant_days=30)
    assert "Sleeping Bag" in _by_title(result, "stagnant")
    assert "Selling Bag" not in _by_title(result, "stagnant")


async def test_a_sale_older_than_the_window_does_not_save_it_from_stagnant(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    v = await _variant(db, t, "Old Seller")
    await _stock(db, t, wh, v, on_hand=9)
    await _sell(db, t, v, days_ago=90)
    assert "Old Seller" in _by_title(await _run(db, t, stagnant_days=30), "stagnant")


async def test_out_of_stock_is_never_called_stagnant(db, tenant_ctx):
    """Nothing on the shelf cannot be sitting there unsold."""
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    v = await _variant(db, t, "Empty Shelf")
    await _stock(db, t, wh, v, on_hand=0)
    assert "Empty Shelf" not in _by_title(await _run(db, t), "stagnant")


async def test_a_cancelled_or_deleted_order_does_not_count_as_a_sale(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    v = await _variant(db, t, "Phantom Seller")
    await _stock(db, t, wh, v, on_hand=9)
    await _sell(db, t, v, days_ago=2, status="cancelled")
    await _sell(db, t, v, days_ago=2, deleted=True)
    assert "Phantom Seller" in _by_title(await _run(db, t, stagnant_days=30), "stagnant")


async def test_the_most_urgent_come_first_and_the_list_is_capped_honestly(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    for i, qty in enumerate([4, 1, 3, 0, 2]):
        v = await _variant(db, t, f"Item {i}")
        await _stock(db, t, wh, v, on_hand=qty)
        await _reorder(db, t, v, 10)
    result = await _run(db, t, limit=2)
    lows = result["summary"]["low_stock"]
    assert [r["available"] for r in lows] == [1, 2]  # lowest first
    assert result["summary"]["counts"]["low_stock"] == 4  # 4,1,3,2 are low; the 0 is "out"
    assert any("2" in note for note in result["limitations"])


async def test_every_number_the_model_may_quote_is_registered_evidence(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    wh = await _warehouse(db, t)
    v = await _variant(db, t, "Evidence Mug", sku="MUG-1")
    await _stock(db, t, wh, v, on_hand=6, reserved=1)
    result = await _run(db, t)
    facts = {(f["metric"], f["value"]) for f in result["facts"]}
    assert ("stock_available", "5") in facts or ("stock_available", 5) in facts


async def test_one_shop_never_sees_another_shops_stock(db, tenant_ctx):
    from app.core.db import bind_tenant
    from app.modules.identity.models import Tenant

    mine = tenant_ctx.tenant_id
    wh = await _warehouse(db, mine)
    v = await _variant(db, mine, "Private Jacket")
    await _stock(db, mine, wh, v, on_hand=0)
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    result = await _run(db, other.id)
    assert result["summary"]["items"] == []
    assert result["summary"]["counts"] == {
        "tracked": 0,
        "low_stock": 0,
        "out_of_stock": 0,
        "stagnant": 0,
        "not_tracked": 0,
    }


def test_it_is_registered_and_gated_by_the_inventory_permission():
    import app.modules.ai.agents.sales_intelligence.tools as tools

    tools.register_si_tools()
    spec = get_tool("si_stock_status")
    assert spec is not None
    assert spec.requires == "inventory:read"


def test_the_agent_kind_allows_the_tool():
    from app.modules.ai.core.registry import AgentRegistry

    assert AgentRegistry.is_tool_authorized("sales_intelligence", "si_stock_status")


async def _sell(db, tenant_id, variant, *, days_ago, status="fulfilled", deleted=False):
    from app.modules.orders.models import Order, OrderItem

    placed = datetime.now(UTC) - timedelta(days=days_ago)
    customer = Customer(tenant_id=tenant_id, name="Buyer")
    db.add(customer)
    await db.flush()
    order = Order(
        customer_id=customer.id,
        tenant_id=tenant_id,
        number=f"S-{uuid.uuid4().hex[:8]}",
        status=status,
        grand_total=100,
        placed_at=placed,
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            tenant_id=tenant_id,
            order_id=order.id,
            variant_id=variant.id,
            title=variant.title,
            sku=variant.sku,
            quantity=1,
            unit_price=100,
            total=100,
        )
    )
    if deleted:
        await db.execute(
            text("UPDATE orders SET deleted_at = now() WHERE id = :i"), {"i": str(order.id)}
        )
    await db.flush()


async def test_the_stock_query_filters_by_tenant_on_every_table_it_reads(db, tenant_ctx):
    """RLS is the second lock, not the first: the query itself must be scoped, so that a pooled
    connection whose tenant binding is lost can never read another shop's stock."""
    from app.modules.ai.agents.sales_intelligence.tools import _STOCK_SQL

    for table in (
        "product_variants v",
        "products p",
        "inventory_balances b",
        "variant_stock_settings s",
        "order_items oi",
        "orders o",
    ):
        alias = table.split()[1]
        assert f"{alias}.tenant_id" in _STOCK_SQL, f"{table} is read without a tenant condition"
    # The two tables read in the WHERE (not just joined) must be bound to the caller's tenant
    # explicitly. A variant id is unique so the unsold lookup could not leak today, but the
    # explicit bind is the belt that stays if that join ever changes.
    assert "v.tenant_id = :tenant_id" in _STOCK_SQL
    assert "oi.tenant_id = :tenant_id" in _STOCK_SQL
