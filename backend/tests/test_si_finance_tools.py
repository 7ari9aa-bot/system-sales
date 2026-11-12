"""``si_expenses_summary`` and ``si_profit_summary``: the owner's money, told honestly.

Profit is the number most likely to mislead, so the rules are strict:

* revenue is the shop's own definition (delivered orders in the window), so this tool can never
  disagree with the sales numbers the same assistant quotes;
* profit is shown ONLY when the cost of every sold line is known. A variant with no recorded cost
  is unknown, not free: treating it as 0 would invent profit. When any cost is missing the tool
  says how many lines and how much revenue are uncosted and shows NO profit figure;
* only POSTED expenses count; a voided one never reduces profit or inflates spending;
* both are read-only, tenant-scoped, and gated by ``finance:read``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.ai.agents.sales_intelligence.tools import (
    _si_expenses_summary,
    _si_profit_summary,
)
from app.modules.ai.tools import TOOLS
from app.modules.catalog.models import Product, ProductVariant
from app.modules.customers.models import Customer
from app.modules.expenses.models import Expense, ExpenseCategory
from app.modules.orders.models import Order, OrderItem, Shipment
from app.modules.pos import models as _pos_models  # noqa: F401  (expenses.session_id FK)
from app.modules.purchasing.models import VariantCost

pytestmark = pytest.mark.usefixtures("db")

TODAY = datetime.now(UTC)


async def _category(db, tenant_id, name="Rent") -> ExpenseCategory:
    cat = ExpenseCategory(tenant_id=tenant_id, name=f"{name}-{uuid.uuid4().hex[:5]}")
    db.add(cat)
    await db.flush()
    return cat


async def _expense(db, tenant_id, cat, amount, *, days_ago=1, status="posted", method="cash"):
    db.add(
        Expense(
            tenant_id=tenant_id,
            number=f"EXP-{uuid.uuid4().hex[:8]}",
            category_id=cat.id,
            description="x",
            amount=Decimal(str(amount)),
            payment_method=method,
            expense_date=(TODAY - timedelta(days=days_ago)).date(),
            status=status,
        )
    )
    await db.flush()


async def _variant(db, tenant_id, title, *, cost=None) -> ProductVariant:
    product = Product(
        tenant_id=tenant_id,
        title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(product)
    await db.flush()
    v = ProductVariant(
        tenant_id=tenant_id,
        product_id=product.id,
        sku=f"S-{uuid.uuid4().hex[:6]}",
        title=title,
        price=100,
    )
    db.add(v)
    await db.flush()
    if cost is not None:
        db.add(VariantCost(tenant_id=tenant_id, variant_id=v.id, avg_cost=Decimal(str(cost))))
        await db.flush()
    return v


async def _delivered_sale(db, tenant_id, lines, *, days_ago=2, deleted=False):
    """lines = [(variant, qty, line_total)]. Delivered inside the window unless told otherwise."""
    customer = Customer(tenant_id=tenant_id, name="Buyer")
    db.add(customer)
    await db.flush()
    when = TODAY - timedelta(days=days_ago)
    order = Order(
        tenant_id=tenant_id,
        number=f"O-{uuid.uuid4().hex[:8]}",
        customer_id=customer.id,
        status="delivered",
        grand_total=sum(Decimal(str(t)) for _, _, t in lines),
        placed_at=when - timedelta(days=1),
    )
    db.add(order)
    await db.flush()
    for variant, qty, total in lines:
        db.add(
            OrderItem(
                tenant_id=tenant_id,
                order_id=order.id,
                variant_id=variant.id,
                title=variant.title,
                sku=variant.sku,
                quantity=qty,
                unit_price=Decimal(str(total)) / qty,
                total=Decimal(str(total)),
            )
        )
    db.add(
        Shipment(
            tenant_id=tenant_id,
            order_id=order.id,
            carrier="Bosta",
            status="delivered",
            shipped_at=when - timedelta(hours=5),
            delivered_at=when,
        )
    )
    if deleted:
        from sqlalchemy import text

        await db.execute(
            text("UPDATE orders SET deleted_at = now() WHERE id = :i"), {"i": str(order.id)}
        )
    await db.flush()
    return order


def _money(x) -> Decimal:
    return Decimal(str(x))


# ----------------------------- expenses -----------------------------------------------------


async def test_expenses_total_and_split_by_category(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    rent, ads = await _category(db, t, "Rent"), await _category(db, t, "Ads")
    await _expense(db, t, rent, 1000)
    await _expense(db, t, ads, 250)
    await _expense(db, t, ads, 150)
    result = await _si_expenses_summary(db, t, days=30)
    assert _money(result["summary"]["total"]) == Decimal("1400")
    assert result["summary"]["count"] == 3
    by_cat = {
        c["category"].split("-")[0]: _money(c["total"]) for c in result["summary"]["by_category"]
    }
    assert by_cat == {"Rent": Decimal("1000"), "Ads": Decimal("400")}


async def test_a_voided_expense_is_not_spending(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    cat = await _category(db, t)
    await _expense(db, t, cat, 500)
    await _expense(db, t, cat, 9999, status="voided")
    result = await _si_expenses_summary(db, t, days=30)
    assert _money(result["summary"]["total"]) == Decimal("500")
    assert result["summary"]["count"] == 1


async def test_an_expense_outside_the_window_is_left_out(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    cat = await _category(db, t)
    await _expense(db, t, cat, 300, days_ago=2)
    await _expense(db, t, cat, 700, days_ago=60)
    result = await _si_expenses_summary(db, t, days=30)
    assert _money(result["summary"]["total"]) == Decimal("300")


async def test_no_expenses_is_zero_not_an_error(db, tenant_ctx):
    result = await _si_expenses_summary(db, tenant_ctx.tenant_id, days=30)
    assert _money(result["summary"]["total"]) == Decimal("0")
    assert result["summary"]["by_category"] == []
    assert result["status"] == "ok"


async def test_expenses_split_by_payment_method_too(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    cat = await _category(db, t)
    await _expense(db, t, cat, 100, method="cash")
    await _expense(db, t, cat, 40, method="card")
    result = await _si_expenses_summary(db, t, days=30)
    by_method = {m["method"]: _money(m["total"]) for m in result["summary"]["by_method"]}
    assert by_method == {"cash": Decimal("100"), "card": Decimal("40")}


async def test_expenses_registers_its_totals_as_evidence(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    cat = await _category(db, t)
    await _expense(db, t, cat, 250)
    result = await _si_expenses_summary(db, t, days=30)
    assert any(f["metric"] == "expenses_total" for f in result["facts"])


# ----------------------------- profit -------------------------------------------------------


async def test_profit_is_revenue_minus_cost_minus_expenses_when_every_cost_is_known(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    shirt = await _variant(db, t, "Shirt", cost=40)
    hat = await _variant(db, t, "Hat", cost=10)
    await _delivered_sale(db, t, [(shirt, 2, 200), (hat, 3, 90)])  # revenue 290, cost 80+30=110
    cat = await _category(db, t)
    await _expense(db, t, cat, 50)
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert s["profit_known"] is True
    assert _money(s["revenue"]) == Decimal("290")
    assert _money(s["cost_of_goods"]) == Decimal("110")
    assert _money(s["gross_profit"]) == Decimal("180")
    assert _money(s["expenses"]) == Decimal("50")
    assert _money(s["net_profit"]) == Decimal("130")


async def test_a_missing_cost_hides_profit_instead_of_inventing_it(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    known = await _variant(db, t, "Known", cost=40)
    unknown = await _variant(db, t, "Unknown")  # no VariantCost row at all
    await _delivered_sale(db, t, [(known, 1, 100), (unknown, 1, 300)])
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert s["profit_known"] is False
    assert s.get("gross_profit") is None
    assert s.get("net_profit") is None
    assert s["uncosted_lines"] == 1
    assert _money(s["uncosted_revenue"]) == Decimal("300")
    assert _money(s["revenue"]) == Decimal("400")  # revenue is still true and still shown


async def test_a_null_cost_is_unknown_not_free(db, tenant_ctx):
    """A VariantCost row whose avg_cost is NULL means 'stock older than any purchase'."""
    t = tenant_ctx.tenant_id
    v = await _variant(db, t, "Legacy")
    db.add(VariantCost(tenant_id=t, variant_id=v.id, avg_cost=None))
    await db.flush()
    await _delivered_sale(db, t, [(v, 1, 100)])
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert s["profit_known"] is False
    assert s["uncosted_lines"] == 1


async def test_a_zero_cost_is_a_real_cost(db, tenant_ctx):
    """A free sample really costs 0. That is known, and must not be flagged as missing."""
    t = tenant_ctx.tenant_id
    v = await _variant(db, t, "Giveaway", cost=0)
    await _delivered_sale(db, t, [(v, 1, 100)])
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert s["profit_known"] is True
    assert _money(s["gross_profit"]) == Decimal("100")


async def test_expenses_are_still_reported_when_profit_is_unknown(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    v = await _variant(db, t, "Nocost")
    await _delivered_sale(db, t, [(v, 1, 100)])
    cat = await _category(db, t)
    await _expense(db, t, cat, 30)
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert s["profit_known"] is False
    assert _money(s["expenses"]) == Decimal("30")


async def test_only_delivered_orders_in_the_window_count_as_revenue(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    v = await _variant(db, t, "Item", cost=10)
    await _delivered_sale(db, t, [(v, 1, 100)], days_ago=3)
    await _delivered_sale(db, t, [(v, 1, 5000)], days_ago=80)  # delivered long before the window
    await _delivered_sale(db, t, [(v, 1, 7000)], days_ago=3, deleted=True)  # deleted order
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert _money(s["revenue"]) == Decimal("100")


async def test_an_old_uncosted_sale_does_not_poison_a_recent_window(db, tenant_ctx):
    """Revenue and cost must be measured over the SAME deliveries. If the cost query ignored the
    window, an old sale with no recorded cost would hide the profit of a fully costed month."""
    t = tenant_ctx.tenant_id
    costed = await _variant(db, t, "Costed", cost=10)
    unknown = await _variant(db, t, "OldUnknown")
    await _delivered_sale(db, t, [(costed, 1, 100)], days_ago=3)
    await _delivered_sale(db, t, [(unknown, 1, 900)], days_ago=120)
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert s["profit_known"] is True
    assert s["uncosted_lines"] == 0
    assert _money(s["gross_profit"]) == Decimal("90")


async def test_an_old_order_with_no_lines_does_not_poison_a_recent_window(db, tenant_ctx):
    from sqlalchemy import text

    t = tenant_ctx.tenant_id
    costed = await _variant(db, t, "Costed2", cost=10)
    await _delivered_sale(db, t, [(costed, 1, 100)], days_ago=3)
    old = await _delivered_sale(db, t, [(costed, 1, 800)], days_ago=120)
    await db.execute(text("DELETE FROM order_items WHERE order_id = :i"), {"i": str(old.id)})
    await db.flush()
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert s["profit_known"] is True
    assert _money(s["revenue"]) == Decimal("100")


async def test_cost_is_charged_per_unit_sold(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    v = await _variant(db, t, "Bulk", cost=7)
    await _delivered_sale(db, t, [(v, 5, 100)])
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert _money(s["cost_of_goods"]) == Decimal("35")


async def test_a_sale_without_lines_has_revenue_but_no_cost_claim(db, tenant_ctx):
    """An order with no item rows: revenue is real, its cost cannot be known, so no profit."""
    t = tenant_ctx.tenant_id
    v = await _variant(db, t, "Ghost", cost=1)
    order = await _delivered_sale(db, t, [(v, 1, 100)])
    from sqlalchemy import text

    await db.execute(text("DELETE FROM order_items WHERE order_id = :i"), {"i": str(order.id)})
    await db.flush()
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert _money(s["revenue"]) == Decimal("100")
    assert s["profit_known"] is False


async def test_no_sales_means_nothing_to_profit_from(db, tenant_ctx):
    s = (await _si_profit_summary(db, tenant_ctx.tenant_id, days=30))["summary"]
    assert _money(s["revenue"]) == Decimal("0")
    assert s["profit_known"] is True
    assert _money(s["net_profit"]) == Decimal("0")


async def test_a_loss_is_shown_as_negative_not_hidden(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    v = await _variant(db, t, "Loser", cost=90)
    await _delivered_sale(db, t, [(v, 1, 100)])
    cat = await _category(db, t)
    await _expense(db, t, cat, 50)
    s = (await _si_profit_summary(db, t, days=30))["summary"]
    assert _money(s["net_profit"]) == Decimal("-40")


async def test_profit_numbers_are_registered_evidence_but_a_loss_is_not_dropped(db, tenant_ctx):
    """register_numbers refuses negatives. A real loss must still reach the model."""
    t = tenant_ctx.tenant_id
    v = await _variant(db, t, "Loser2", cost=90)
    await _delivered_sale(db, t, [(v, 1, 100)])
    cat = await _category(db, t)
    await _expense(db, t, cat, 50)
    result = await _si_profit_summary(db, t, days=30)
    assert _money(result["summary"]["net_profit"]) == Decimal("-40")
    assert any("loss" in note.lower() for note in result["limitations"])


async def test_unknown_profit_registers_no_profit_fact(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    v = await _variant(db, t, "Nocost2")
    await _delivered_sale(db, t, [(v, 1, 100)])
    facts = {f["metric"] for f in (await _si_profit_summary(db, t, days=30))["facts"]}
    assert "gross_profit" not in facts and "net_profit" not in facts
    assert "revenue" in facts


async def test_one_shop_never_sees_another_shops_money(db, tenant_ctx):
    from app.core.db import bind_tenant
    from app.modules.identity.models import Tenant

    mine = tenant_ctx.tenant_id
    v = await _variant(db, mine, "Mine", cost=10)
    await _delivered_sale(db, mine, [(v, 1, 100)])
    cat = await _category(db, mine)
    await _expense(db, mine, cat, 60)
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    p = (await _si_profit_summary(db, other.id, days=30))["summary"]
    e = (await _si_expenses_summary(db, other.id, days=30))["summary"]
    assert _money(p["revenue"]) == 0 and _money(e["total"]) == 0


# ----------------------------- wiring -------------------------------------------------------


def test_both_tools_are_registered_gated_low_risk_and_allowed():
    import app.modules.ai.agents.sales_intelligence.tools as si
    from app.core.risk import known_actions
    from app.modules.ai.core.registry import AgentRegistry

    si.register_si_tools()
    for name in ("si_expenses_summary", "si_profit_summary"):
        spec = TOOLS[name]
        assert spec.requires == "finance:read", f"{name} must need finance:read"
        assert spec.risk_level == "LOW"
        assert name in known_actions()
        assert AgentRegistry.is_tool_authorized("sales_intelligence", name)


def test_the_sql_is_scoped_to_the_tenant_on_every_table():
    from app.modules.ai.agents.sales_intelligence import tools as si

    for sql in (si._EXPENSES_SQL, si._PROFIT_REVENUE_SQL, si._PROFIT_LINES_SQL):
        assert ":tenant_id" in sql
    assert "o.tenant_id = :tenant_id" in si._PROFIT_EMPTY_ORDERS_SQL
    assert "e.tenant_id = :tenant_id" in si._EXPENSES_SQL
    assert "o.tenant_id = :tenant_id" in si._PROFIT_REVENUE_SQL
    assert "oi.tenant_id = :tenant_id" in si._PROFIT_LINES_SQL
    assert "c.tenant_id = oi.tenant_id" in si._PROFIT_LINES_SQL


_ = date  # keep the import used if the suite changes
