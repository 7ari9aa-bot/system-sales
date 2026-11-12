"""``si_purchasing_summary``: what the shop bought and what it still owes its suppliers.

The balance owed MUST equal the supplier statement the purchasing screen shows, so it uses the
same formula: received orders, minus payments (a reversal cancels one), minus accepted returns
settled as credit. A negative balance means the supplier owes the shop. A draft order is not a
purchase until it is received, and a cancelled one never is.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.ai.agents.sales_intelligence.tools import _si_purchasing_summary
from app.modules.ai.tools import TOOLS
from app.modules.catalog.models import Product, ProductVariant
from app.modules.inventory.models import Warehouse
from app.modules.pos import models as _pos_models  # noqa: F401  (FK targets)
from app.modules.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierPayment,
    SupplierReturn,
)

pytestmark = pytest.mark.usefixtures("db")

NOW = datetime.now(UTC)


def _d(x) -> Decimal:
    return Decimal(str(x))


async def _supplier(db, tenant_id, name="Acme", *, status="active") -> Supplier:
    s = Supplier(tenant_id=tenant_id, name=f"{name}-{uuid.uuid4().hex[:4]}", status=status)
    db.add(s)
    await db.flush()
    return s


async def _warehouse(db, tenant_id) -> Warehouse:
    wh = Warehouse(tenant_id=tenant_id, name="Main", code=f"W{uuid.uuid4().hex[:4]}")
    db.add(wh)
    await db.flush()
    return wh


async def _order(db, tenant_id, supplier, total, *, status="received", days_ago=3, wh=None):
    wh = wh or await _warehouse(db, tenant_id)
    po = PurchaseOrder(
        tenant_id=tenant_id,
        number=f"PO-{uuid.uuid4().hex[:8]}",
        supplier_id=supplier.id,
        warehouse_id=wh.id,
        order_date=(NOW - timedelta(days=days_ago)).date(),
        status=status,
        total=_d(total),
        received_at=(NOW - timedelta(days=days_ago)) if status == "received" else None,
        cancelled_at=(NOW - timedelta(days=days_ago)) if status == "cancelled" else None,
    )
    db.add(po)
    await db.flush()
    return po


async def _payment(db, tenant_id, supplier, amount, *, reverses=None, days_ago=1):
    p = SupplierPayment(
        tenant_id=tenant_id,
        supplier_id=supplier.id,
        amount=_d(amount),
        method="cash",
        paid_on=(NOW - timedelta(days=days_ago)).date(),
        reverses_payment_id=reverses.id if reverses else None,
    )
    db.add(p)
    await db.flush()
    return p


async def _return(db, tenant_id, supplier, total, *, status="accepted", settlement="credit"):
    wh = await _warehouse(db, tenant_id)
    r = SupplierReturn(
        tenant_id=tenant_id,
        number=f"SR-{uuid.uuid4().hex[:8]}",
        supplier_id=supplier.id,
        warehouse_id=wh.id,
        settlement=settlement,
        status=status,
        total=_d(total),
        return_date=NOW.date(),
        decided_at=None if status == "review" else NOW,
    )
    db.add(r)
    await db.flush()
    return r


def _owed(result, supplier) -> Decimal:
    for row in result["summary"]["owed_by_supplier"]:
        if row["supplier"] == supplier.name:
            return _d(row["owed"])
    raise AssertionError(f"{supplier.name} not listed: {result['summary']['owed_by_supplier']}")


# ------------------------------ what was bought ---------------------------------------------


async def test_received_orders_in_the_window_are_the_purchases(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 1000)
    await _order(db, t, s, 400)
    r = await _si_purchasing_summary(db, t, days=30)
    assert _d(r["summary"]["purchased"]) == Decimal("1400")
    assert r["summary"]["orders_received"] == 2


async def test_a_draft_is_not_a_purchase_but_is_reported_as_waiting(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 500)
    await _order(db, t, s, 9000, status="draft")
    r = await _si_purchasing_summary(db, t, days=30)
    assert _d(r["summary"]["purchased"]) == Decimal("500")
    assert r["summary"]["pending_orders"] == 1
    assert _d(r["summary"]["pending_value"]) == Decimal("9000")


async def test_a_cancelled_order_counts_nowhere(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 700, status="cancelled")
    r = await _si_purchasing_summary(db, t, days=30)
    assert _d(r["summary"]["purchased"]) == 0
    assert r["summary"]["pending_orders"] == 0


async def test_an_order_received_before_the_window_is_not_in_it(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 300, days_ago=2)
    await _order(db, t, s, 8000, days_ago=90)
    r = await _si_purchasing_summary(db, t, days=30)
    assert _d(r["summary"]["purchased"]) == Decimal("300")


async def test_top_suppliers_by_what_they_supplied_in_the_window(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    big, small = await _supplier(db, t, "Big"), await _supplier(db, t, "Small")
    await _order(db, t, big, 900)
    await _order(db, t, small, 100)
    r = await _si_purchasing_summary(db, t, days=30)
    top = r["summary"]["top_suppliers"]
    assert [x["supplier"] for x in top] == [big.name, small.name]
    assert _d(top[0]["purchased"]) == Decimal("900")


# ------------------------------ what is owed ------------------------------------------------


async def test_owed_is_received_minus_paid(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 1000)
    await _payment(db, t, s, 300)
    r = await _si_purchasing_summary(db, t, days=30)
    assert _owed(r, s) == Decimal("700")
    assert _d(r["summary"]["total_owed"]) == Decimal("700")


async def test_a_reversed_payment_is_owed_again(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 1000)
    paid = await _payment(db, t, s, 400)
    await _payment(db, t, s, 400, reverses=paid)
    r = await _si_purchasing_summary(db, t, days=30)
    assert _owed(r, s) == Decimal("1000")


async def test_a_credit_return_reduces_what_is_owed(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 1000)
    await _return(db, t, s, 150, settlement="credit")
    r = await _si_purchasing_summary(db, t, days=30)
    assert _owed(r, s) == Decimal("850")


async def test_only_accepted_credit_returns_count(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 1000)
    await _return(db, t, s, 100, status="review", settlement="credit")  # not accepted yet
    await _return(db, t, s, 200, status="rejected", settlement="credit")
    await _return(db, t, s, 300, status="accepted", settlement="cash")  # settled in cash
    await _return(db, t, s, 400, status="accepted", settlement="replace")
    r = await _si_purchasing_summary(db, t, days=30)
    assert _owed(r, s) == Decimal("1000")


async def test_an_overpaid_supplier_shows_a_negative_balance(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 100)
    await _payment(db, t, s, 250)
    r = await _si_purchasing_summary(db, t, days=30)
    assert _owed(r, s) == Decimal("-150")
    assert any("owes the shop" in n for n in r["limitations"])


async def test_a_draft_does_not_make_the_shop_owe_anything(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 5000, status="draft")
    r = await _si_purchasing_summary(db, t, days=30)
    assert _d(r["summary"]["total_owed"]) == 0


async def test_debt_does_not_depend_on_the_window(db, tenant_ctx):
    """What is owed is a standing balance: an old unpaid order is still owed."""
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 2000, days_ago=200)
    r = await _si_purchasing_summary(db, t, days=7)
    assert _d(r["summary"]["purchased"]) == 0
    assert _owed(r, s) == Decimal("2000")


async def test_a_settled_supplier_is_not_listed_as_owed(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 500)
    await _payment(db, t, s, 500)
    r = await _si_purchasing_summary(db, t, days=30)
    assert r["summary"]["owed_by_supplier"] == []
    assert _d(r["summary"]["total_owed"]) == 0


async def test_biggest_debt_is_listed_first(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    a, b = await _supplier(db, t, "A"), await _supplier(db, t, "B")
    await _order(db, t, a, 100)
    await _order(db, t, b, 900)
    r = await _si_purchasing_summary(db, t, days=30)
    assert [x["supplier"] for x in r["summary"]["owed_by_supplier"]] == [b.name, a.name]


async def test_total_owed_nets_a_supplier_that_owes_the_shop(db, tenant_ctx):
    """The total is the shop's net position, so an overpaid supplier offsets a debt."""
    t = tenant_ctx.tenant_id
    a, b = await _supplier(db, t, "A"), await _supplier(db, t, "B")
    await _order(db, t, a, 1000)
    await _order(db, t, b, 100)
    await _payment(db, t, b, 300)  # b: -200
    r = await _si_purchasing_summary(db, t, days=30)
    assert _d(r["summary"]["total_owed"]) == Decimal("800")


# ------------------------------ honesty and isolation ---------------------------------------


async def test_no_suppliers_at_all_says_nothing_is_recorded(db, tenant_ctx):
    r = await _si_purchasing_summary(db, tenant_ctx.tenant_id, days=30)
    assert r["status"] == "no_data"
    assert any("no suppliers" in n.lower() for n in r["limitations"])
    assert r["facts"] == []


async def test_suppliers_but_no_purchases_in_the_window_is_ok_with_zero(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _supplier(db, t)
    r = await _si_purchasing_summary(db, t, days=30)
    assert r["status"] == "ok"
    assert _d(r["summary"]["purchased"]) == 0


async def test_facts_carry_the_money_numbers(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    s = await _supplier(db, t)
    await _order(db, t, s, 1000)
    await _payment(db, t, s, 300)
    metrics = {f["metric"] for f in (await _si_purchasing_summary(db, t, days=30))["facts"]}
    assert {"purchased_total", "total_owed"} <= metrics


async def test_one_shop_never_sees_another_shops_suppliers(db, tenant_ctx):
    from app.core.db import bind_tenant
    from app.modules.identity.models import Tenant

    mine = tenant_ctx.tenant_id
    s = await _supplier(db, mine)
    await _order(db, mine, s, 1000)
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    r = await _si_purchasing_summary(db, other.id, days=30)
    assert r["status"] == "no_data"
    assert _d(r["summary"]["total_owed"]) == 0


# ------------------------------ wiring ------------------------------------------------------


async def test_top_suppliers_are_ordered_whatever_order_they_were_created_in(db, tenant_ctx):
    """Created small-first, so an unsorted result would list them the wrong way round."""
    t = tenant_ctx.tenant_id
    small = await _supplier(db, t, "Small")
    mid = await _supplier(db, t, "Mid")
    big = await _supplier(db, t, "Big")
    await _order(db, t, small, 10)
    await _order(db, t, mid, 500)
    await _order(db, t, big, 9000)
    r = await _si_purchasing_summary(db, t, days=30)
    assert [x["supplier"] for x in r["summary"]["top_suppliers"]] == [
        big.name,
        mid.name,
        small.name,
    ]


async def test_a_name_clash_with_another_shops_supplier_cannot_leak_money(db, tenant_ctx):
    """A purchase order points at its own shop's supplier; the join must stay inside the tenant."""
    from app.core.db import bind_tenant
    from app.modules.identity.models import Tenant

    mine = tenant_ctx.tenant_id
    s = await _supplier(db, mine, "Shared")
    await _order(db, mine, s, 1234)
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    their = await _supplier(db, other.id, "Theirs")
    await _order(db, other.id, their, 55)
    r = await _si_purchasing_summary(db, other.id, days=30)
    assert _d(r["summary"]["purchased"]) == Decimal("55")
    assert _d(r["summary"]["total_owed"]) == Decimal("55")


def test_registered_gated_by_purchasing_read_low_risk_and_allowed():
    import app.modules.ai.agents.sales_intelligence.tools as si
    from app.core.risk import known_actions
    from app.modules.ai.core.registry import AgentRegistry

    si.register_si_tools()
    spec = TOOLS["si_purchasing_summary"]
    assert spec.requires == "purchasing:read"
    assert spec.risk_level == "LOW"
    assert "si_purchasing_summary" in known_actions()
    assert AgentRegistry.is_tool_authorized("sales_intelligence", "si_purchasing_summary")


def test_every_purchasing_query_is_tenant_scoped():
    from app.modules.ai.agents.sales_intelligence import tools as si

    for name in ("_PURCHASES_SQL", "_OWED_SQL"):
        sql = getattr(si, name)
        assert "tenant_id = :tenant_id" in sql, name
    assert "po.tenant_id = :tenant_id" in si._PURCHASES_SQL
    # row-level security is the real wall; the join on tenant_id is the second layer
    assert "s.tenant_id = po.tenant_id" in si._PURCHASES_SQL
    assert "sp.tenant_id = s.tenant_id" in si._OWED_SQL
    assert "sr.tenant_id = s.tenant_id" in si._OWED_SQL
    assert "po.tenant_id = s.tenant_id" in si._OWED_SQL


_ = PurchaseOrderLine, Product, ProductVariant  # imported so every FK target is mapped
