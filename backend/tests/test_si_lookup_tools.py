"""``si_find_order`` and ``si_find_customer``: the owner asks "where is order 1042?" or "what did
Ahmed buy?" and gets the record, read-only.

Two shop-owner realities shape these: names are typed the way people spell, not the way they were
saved ("احمد" for "أحمد"), and the data is personal, so the tools return the least that answers
the question, never an address, never an unbounded list, and never a deleted or merged record
dressed up as a live one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.ai.agents.sales_intelligence.tools import (
    _si_find_customer,
    _si_find_order,
)
from app.modules.ai.tools import TOOLS
from app.modules.catalog.models import Product, ProductVariant
from app.modules.customers.models import Customer
from app.modules.orders.models import Order, OrderItem

pytestmark = pytest.mark.usefixtures("db")

NOW = datetime.now(UTC)


def _d(x) -> Decimal:
    return Decimal(str(x))


async def _customer(db, t, name="Ali", phone=None, email=None, **kw) -> Customer:
    c = Customer(
        tenant_id=t,
        name=name,
        phone=phone or f"+2010{uuid.uuid4().int % 10**8:08d}",
        email=email,
        **kw,
    )
    db.add(c)
    await db.flush()
    return c


async def _order(db, t, customer, *, number=None, total=100, status="confirmed", days_ago=1, **kw):
    o = Order(
        tenant_id=t,
        number=number or f"O-{uuid.uuid4().hex[:8]}",
        customer_id=customer.id,
        status=status,
        grand_total=_d(total),
        placed_at=NOW - timedelta(days=days_ago),
        **kw,
    )
    db.add(o)
    await db.flush()
    return o


async def _item(db, t, order, title="Shirt", qty=1, price=50):
    p = Product(tenant_id=t, title=title, slug=f"p-{uuid.uuid4().hex[:8]}", status="active")
    db.add(p)
    await db.flush()
    v = ProductVariant(
        tenant_id=t, product_id=p.id, sku=f"S{uuid.uuid4().hex[:6]}", price=_d(price)
    )
    db.add(v)
    await db.flush()
    it = OrderItem(
        tenant_id=t,
        order_id=order.id,
        variant_id=v.id,
        title=title,
        sku=v.sku,
        quantity=qty,
        unit_price=_d(price),
        total=_d(price) * qty,
    )
    db.add(it)
    await db.flush()
    return it


# ----------------------------------- find order ---------------------------------------------


async def test_an_order_is_found_by_its_exact_number(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t)
    await _order(db, t, c, number="ORD-1042", total=300)
    r = await _si_find_order(db, t, query="ORD-1042")
    assert r["status"] == "ok"
    assert [o["number"] for o in r["matches"]] == ["ORD-1042"]
    assert _d(r["matches"][0]["grand_total"]) == Decimal("300")


async def test_an_order_is_found_by_part_of_its_number_ignoring_case_and_dash(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t)
    await _order(db, t, c, number="ORD-1042")
    for q in ("1042", "ord1042", "ord-1042", "ORD 1042"):
        r = await _si_find_order(db, t, query=q)
        assert [o["number"] for o in r["matches"]] == ["ORD-1042"], q


async def test_arabic_indic_digits_find_the_same_order(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t)
    await _order(db, t, c, number="ORD-1042")
    r = await _si_find_order(db, t, query="١٠٤٢")
    assert [o["number"] for o in r["matches"]] == ["ORD-1042"]


async def test_an_order_is_found_by_the_customers_name_in_any_spelling(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="أحمد محمود")
    await _order(db, t, c, number="A-1")
    r = await _si_find_order(db, t, query="احمد")
    assert [o["number"] for o in r["matches"]] == ["A-1"]


async def test_an_order_is_found_by_the_customers_phone(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, phone="+201001234567")
    await _order(db, t, c, number="P-1")
    r = await _si_find_order(db, t, query="01001234567")
    assert [o["number"] for o in r["matches"]] == ["P-1"]


async def test_an_order_carries_status_items_channel_and_date(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Sara")
    o = await _order(db, t, c, number="X-9", status="shipped", channel="whatsapp", days_ago=3)
    await _item(db, t, o, title="Red dress", qty=2, price=150)
    m = (await _si_find_order(db, t, query="X-9"))["matches"][0]
    assert m["status"] == "shipped"
    assert m["channel"] == "whatsapp"
    assert m["customer_name"] == "Sara"
    assert m["items"] == [{"title": "Red dress", "quantity": 2, "total": "300.00"}]
    assert m["placed_at"].startswith((NOW - timedelta(days=3)).strftime("%Y-%m-%d"))


async def test_a_deleted_order_is_not_found(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t)
    o = await _order(db, t, c, number="GONE-1")
    o.deleted_at = NOW
    await db.flush()
    r = await _si_find_order(db, t, query="GONE-1")
    assert r["status"] == "no_match"
    assert r["matches"] == []


async def test_the_shipping_address_and_phone_are_never_returned(db, tenant_ctx):
    """Personal data the question did not ask for. The owner can open the order for it."""
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Mona", phone="+201009998877")
    await _order(
        db, t, c, number="PII-1", shipping_address={"line1": "12 Secret St", "city": "Cairo"}
    )
    r = await _si_find_order(db, t, query="PII-1")
    blob = str(r)
    assert "Secret St" not in blob
    assert "01009998877" not in blob


async def test_percent_and_underscore_in_a_query_are_literal(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t)
    await _order(db, t, c, number="AB-1")
    await _order(db, t, c, number="AB-2")
    for q in ("A%", "A_-1", "%%", "__"):
        r = await _si_find_order(db, t, query=q)
        assert r["status"] == "no_match", q
    # a lone "%" is one character: refused as too short, and either way it matches nothing
    assert (await _si_find_order(db, t, query="%"))["matches"] == []


async def test_regex_syntax_in_a_query_is_literal(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Ahmed")
    await _order(db, t, c, number="R-1")
    for q in (".*", "A.*", "(", "[a-z]+", "^A"):
        r = await _si_find_order(db, t, query=q)
        assert r["status"] in ("no_match", "query_too_short"), q
        assert r["matches"] == []


async def test_a_one_character_query_is_refused_not_run(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t)
    await _order(db, t, c, number="Z-1")
    for q in ("", " ", "a"):
        r = await _si_find_order(db, t, query=q)
        assert r["status"] == "query_too_short", repr(q)
        assert r["matches"] == []


async def test_results_are_capped_and_the_cap_is_reported(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Bulk Buyer")
    for i in range(15):
        await _order(db, t, c, number=f"B-{i:03d}", days_ago=i)
    r = await _si_find_order(db, t, query="Bulk", limit=5)
    assert len(r["matches"]) == 5
    assert r["total_matches"] == 15
    assert any("5 of 15" in n for n in r["limitations"])


async def test_newest_order_comes_first(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Sorted")
    await _order(db, t, c, number="S-OLD", days_ago=20)
    await _order(db, t, c, number="S-NEW", days_ago=1)
    await _order(db, t, c, number="S-MID", days_ago=10)
    r = await _si_find_order(db, t, query="Sorted")
    assert [o["number"] for o in r["matches"]] == ["S-NEW", "S-MID", "S-OLD"]


async def test_one_shop_never_finds_another_shops_order(db, tenant_ctx):
    from app.core.db import bind_tenant
    from app.modules.identity.models import Tenant

    mine = tenant_ctx.tenant_id
    c = await _customer(db, mine, name="Mine")
    await _order(db, mine, c, number="SECRET-1")
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    r = await _si_find_order(db, other.id, query="SECRET-1")
    assert r["status"] == "no_match"


# ----------------------------------- find customer ------------------------------------------


async def test_a_customer_is_found_by_name_in_any_arabic_spelling(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="أحمد علي")
    await _customer(db, t, name="Someone Else")
    r = await _si_find_customer(db, t, query="احمد")
    assert [c["name"] for c in r["matches"]] == ["أحمد علي"]


async def test_a_customer_is_found_by_phone_and_by_email(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="By Phone", phone="+201112223334")
    await _customer(db, t, name="By Mail", email="mail.me@example.com")
    assert (await _si_find_customer(db, t, query="01112223334"))["matches"][0]["name"] == "By Phone"
    assert (await _si_find_customer(db, t, query="mail.me@"))["matches"][0]["name"] == "By Mail"


async def test_a_customer_summary_has_order_count_spend_and_last_purchase(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Regular")
    await _order(db, t, c, total=100, days_ago=30)
    await _order(db, t, c, total=250, days_ago=2)
    m = (await _si_find_customer(db, t, query="Regular"))["matches"][0]
    assert m["order_count"] == 2
    assert _d(m["total_spent"]) == Decimal("350")
    assert m["last_order_at"].startswith((NOW - timedelta(days=2)).strftime("%Y-%m-%d"))


async def test_cancelled_and_deleted_orders_do_not_count_as_spend(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Careful")
    await _order(db, t, c, total=100)
    await _order(db, t, c, total=900, status="cancelled")
    gone = await _order(db, t, c, total=700)
    gone.deleted_at = NOW
    await db.flush()
    m = (await _si_find_customer(db, t, query="Careful"))["matches"][0]
    assert m["order_count"] == 1
    assert _d(m["total_spent"]) == Decimal("100")


async def test_a_customer_with_no_orders_says_zero_not_missing(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="Browser")
    m = (await _si_find_customer(db, t, query="Browser"))["matches"][0]
    assert m["order_count"] == 0
    assert _d(m["total_spent"]) == 0
    assert m["last_order_at"] is None


async def test_a_blocked_customer_is_shown_as_blocked(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="Troublemaker", is_blocked=True)
    assert (await _si_find_customer(db, t, query="Troublemaker"))["matches"][0][
        "is_blocked"
    ] is True


async def test_a_deleted_customer_is_not_found(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Erased")
    c.deleted_at = NOW
    await db.flush()
    assert (await _si_find_customer(db, t, query="Erased"))["status"] == "no_match"


async def test_a_merged_away_customer_is_not_listed_beside_the_one_it_became(db, tenant_ctx):
    """After a merge the old row stays (history) but points at the survivor. Listing both would
    show one person twice with the spend split between them."""
    t = tenant_ctx.tenant_id
    keep = await _customer(db, t, name="Dup Person")
    old = await _customer(db, t, name="Dup Person")
    old.merged_into_customer_id = keep.id
    old.merged_at = NOW
    await db.flush()
    r = await _si_find_customer(db, t, query="Dup Person")
    assert [m["customer_id"] for m in r["matches"]] == [str(keep.id)]


async def test_the_customers_phone_and_email_are_masked_in_the_answer(db, tenant_ctx):
    """Enough to tell two Ahmeds apart, not enough to copy out of the chat."""
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="Masked", phone="+201005551234", email="private.person@example.com")
    m = (await _si_find_customer(db, t, query="Masked"))["matches"][0]
    assert m["phone_hint"] == "***1234"
    assert m["email_hint"] == "p***@example.com"
    blob = str(m)
    assert "201005551234" not in blob
    assert "private.person" not in blob


async def test_customer_results_are_capped_and_reported(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    for i in range(12):
        await _customer(db, t, name=f"Many {i}")
    r = await _si_find_customer(db, t, query="Many", limit=4)
    assert len(r["matches"]) == 4
    assert r["total_matches"] == 12
    assert any("4 of 12" in n for n in r["limitations"])


async def test_customer_wildcards_and_regex_are_literal(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="Plain Name")
    for q in ("%", "_", ".*", "P.*", "(", "[a-z]+"):
        r = await _si_find_customer(db, t, query=q)
        assert r["matches"] == [], q


async def test_a_one_character_customer_query_is_refused(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="Aaa")
    assert (await _si_find_customer(db, t, query="a"))["status"] == "query_too_short"


async def test_one_shop_never_finds_another_shops_customer(db, tenant_ctx):
    from app.core.db import bind_tenant
    from app.modules.identity.models import Tenant

    await _customer(db, tenant_ctx.tenant_id, name="Private Client")
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    assert (await _si_find_customer(db, other.id, query="Private"))["status"] == "no_match"


# ----------------------------------- wiring and facts ---------------------------------------


async def test_an_order_match_is_backed_by_evidence_so_the_model_may_quote_it(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t)
    await _order(db, t, c, number="EV-1", total=321)
    r = await _si_find_order(db, t, query="EV-1")
    assert any(f["metric"] == "order_total" for f in r["facts"])


async def test_a_customer_match_is_backed_by_evidence(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Evidence Person")
    await _order(db, t, c, total=40)
    r = await _si_find_customer(db, t, query="Evidence")
    assert {f["metric"] for f in r["facts"]} >= {"customer_total_spent", "customer_order_count"}


def test_both_tools_are_registered_read_only_and_gated():
    import app.modules.ai.agents.sales_intelligence.tools as si
    from app.core.risk import known_actions
    from app.modules.ai.core.registry import AgentRegistry

    si.register_si_tools()
    for name, perm in (("si_find_order", "orders:read"), ("si_find_customer", "customers:read")):
        spec = TOOLS[name]
        assert spec.requires == perm, name
        assert spec.risk_level == "LOW", name
        assert name in known_actions()
        assert AgentRegistry.is_tool_authorized("sales_intelligence", name)


def test_every_lookup_query_is_tenant_scoped_and_skips_deleted_rows():
    from app.modules.ai.agents.sales_intelligence import tools as si

    for name in ("_FIND_ORDER_SQL", "_FIND_ORDER_ITEMS_SQL", "_FIND_CUSTOMER_SQL"):
        sql = getattr(si, name)
        assert "tenant_id = :tenant_id" in sql, name
    assert "o.deleted_at IS NULL" in si._FIND_ORDER_SQL
    assert "c.deleted_at IS NULL" in si._FIND_CUSTOMER_SQL
    assert "merged_into_customer_id IS NULL" in si._FIND_CUSTOMER_SQL


async def test_wildcards_cannot_widen_the_email_or_phone_match(db, tenant_ctx):
    """ "%@%" and "__________" would match every address and every number if bound raw."""
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="Some One", phone="+201001112223", email="some.one@example.com")
    await _customer(db, t, name="Another", phone="+201004445556", email="other@example.com")
    for q in ("%@%", "_@_", "s_me.one@", "%example%", "%.com", "_", "%%"):
        r = await _si_find_customer(db, t, query=q)
        assert r["matches"] == [], q
    # the same characters INSIDE a real term stay literal, not special
    r = await _si_find_customer(db, t, query="some.one@")
    assert [m["name"] for m in r["matches"]] == ["Some One"]


async def test_a_long_run_of_digits_cannot_wildcard_the_phone(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="Num One", phone="+201001112223")
    await _customer(db, t, name="Num Two", phone="+201004445556")
    # "0100%" is not "0100" followed by anything: the percent is literal text and is dropped
    r = await _si_find_customer(db, t, query="01001112223")
    assert [m["name"] for m in r["matches"]] == ["Num One"]
    r = await _si_find_customer(db, t, query="0100111____")
    assert [m["name"] for m in r["matches"]] == [] or all(
        m["name"] == "Num One" for m in r["matches"]
    )


async def test_arabic_indic_digits_find_a_customer_by_phone(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _customer(db, t, name="Phone Indic", phone="+201001234567")
    r = await _si_find_customer(db, t, query="٠١٠٠١٢٣٤٥٦٧")
    assert [m["name"] for m in r["matches"]] == ["Phone Indic"]


async def test_the_customer_phone_does_not_leak_through_the_order_match(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="No Leak", phone="+201007776655", email="leak.me@example.com")
    await _order(db, t, c, number="NL-1")
    m = (await _si_find_order(db, t, query="NL-1"))["matches"][0]
    assert set(m) == {
        "order_id",
        "number",
        "status",
        "grand_total",
        "channel",
        "customer_name",
        "placed_at",
        "items",
    }, "an order match carries exactly these fields and no contact details"


def test_every_table_in_a_lookup_query_is_tenant_matched():
    """RLS is the real wall, but the SQL says it too: a joined or sub-selected table that forgot its
    tenant would read across shops the day RLS is misconfigured. Each table reference needs its OWN
    tenant match, so the count of references must not exceed the count of matches (three subqueries
    sharing the alias ``o`` must not be covered by one match)."""
    import re

    from app.modules.ai.agents.sales_intelligence import tools as si

    for name in ("_FIND_ORDER_SQL", "_FIND_ORDER_ITEMS_SQL", "_FIND_CUSTOMER_SQL"):
        sql = getattr(si, name)
        refs = re.findall(r"\b(?:FROM|JOIN)\s+(?:orders|customers|order_items)\s+(\w+)", sql)
        assert refs, name
        for alias in set(refs):
            wanted = refs.count(alias)
            found = len(re.findall(rf"\b{alias}\.tenant_id\s*=", sql))
            assert found >= wanted, f"{name}: {wanted} uses of {alias} but {found} tenant matches"


async def test_an_old_order_still_gets_evidence_so_the_model_may_quote_it(db, tenant_ctx):
    """A looked-up order can be months old; its evidence must not be tied to the last 30 days."""
    t = tenant_ctx.tenant_id
    c = await _customer(db, t, name="Old Timer")
    await _order(db, t, c, number="OLD-1", total=555, days_ago=200)
    r = await _si_find_order(db, t, query="OLD-1")
    assert r["status"] == "ok"
    assert [f["metric"] for f in r["facts"]] == ["order_total"]
    r = await _si_find_customer(db, t, query="Old Timer")
    assert {f["metric"] for f in r["facts"]} >= {"customer_total_spent"}
