"""`si_data_status` tells the model what the SHOP has recorded, not what the platform could do.

It used to return the same text for every shop (a fixed list of metrics and "maturity curves not
built yet"): proven by calling it for a shop with orders and shipments and for a shop with nothing,
and getting identical answers. So when the owner asked something and the answer was empty, nothing
could tell the model whether the shop had no sales, had never recorded costs, or had no stock data.
That is exactly the "no data" the owner complained about.

It now reports, per source, whether anything is recorded and the first and last date, so the model
can say WHICH of those is true. It carries counts and dates only, never an amount: the tool has no
permission requirement, so it must not leak money to someone without ``finance:read``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.db import bind_tenant
from app.modules.ai.agents.sales_intelligence import tools as T
from app.modules.ai.tools import get_tool
from app.modules.identity.models import Tenant
from tests.test_si_finance_tools import _category, _expense, _variant
from tests.test_si_why_tool import _two_periods

pytestmark = pytest.mark.usefixtures("db")

SOURCES = (
    "orders",
    "shipments",
    "expenses",
    "inventory",
    "purchases",
    "customers",
    "conversations",
)


def _by_source(result) -> dict:
    return {row["source"]: row for row in result["summary"]["sources"]}


async def test_an_empty_shop_is_told_apart_from_a_shop_with_data(db, tenant_ctx):
    empty = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Empty")
    db.add(empty)
    await db.flush()
    await _two_periods(db, tenant_ctx.tenant_id)

    await bind_tenant(db, tenant_ctx.tenant_id)
    full = await T._si_data_status(db, tenant_ctx.tenant_id)
    await bind_tenant(db, empty.id)
    nothing = await T._si_data_status(db, empty.id)

    assert full != nothing, "a shop with data and a shop with none got the same answer"
    assert _by_source(full)["orders"]["recorded"] is True
    assert _by_source(nothing)["orders"]["recorded"] is False


async def test_every_source_is_listed_even_when_empty(db, tenant_ctx):
    out = await T._si_data_status(db, tenant_ctx.tenant_id)
    assert set(_by_source(out)) == set(SOURCES)
    for row in _by_source(out).values():
        assert row["recorded"] is False and row["count"] == 0
        assert row["first"] is None and row["last"] is None


async def test_orders_report_a_count_and_the_first_and_last_day(db, tenant_ctx):
    await _two_periods(db, tenant_ctx.tenant_id)  # 6 orders 5 days ago, 3 orders 40 days ago
    row = _by_source(await T._si_data_status(db, tenant_ctx.tenant_id))["orders"]

    assert row["count"] == 9 + 24  # the helper also creates 24 orders for its shipments
    today = datetime.now(UTC).date()
    assert row["last"] <= today.isoformat()
    assert row["first"] < row["last"]
    first = datetime.fromisoformat(row["first"]).date()
    assert (today - first).days >= 40


async def test_a_shop_with_orders_but_no_shipments_is_not_called_empty(db, tenant_ctx):
    from tests.test_si_why_tool import _orders

    await _orders(db, tenant_ctx.tenant_id, n=3, days_ago=2, total="10.00", tag="solo")
    rows = _by_source(await T._si_data_status(db, tenant_ctx.tenant_id))

    assert rows["orders"]["recorded"] is True
    assert rows["shipments"]["recorded"] is False, "no shipments is a different gap from no orders"


async def test_expenses_and_stock_are_reported_as_their_own_sources(db, tenant_ctx):
    cat = await _category(db, tenant_ctx.tenant_id)
    await _expense(db, tenant_ctx.tenant_id, cat, 50, days_ago=3)
    await _variant(db, tenant_ctx.tenant_id, "Shirt", cost=10)
    rows = _by_source(await T._si_data_status(db, tenant_ctx.tenant_id))

    assert rows["expenses"]["recorded"] is True and rows["expenses"]["count"] == 1
    assert rows["orders"]["recorded"] is False


async def test_it_never_carries_an_amount(db, tenant_ctx):
    """No permission is required, so nothing monetary may leave this tool."""
    await _two_periods(db, tenant_ctx.tenant_id)
    cat = await _category(db, tenant_ctx.tenant_id)
    await _expense(db, tenant_ctx.tenant_id, cat, 98765, days_ago=3)
    out = await T._si_data_status(db, tenant_ctx.tenant_id)

    text = str(out)
    assert "98765" not in text, "an expense amount leaked through a tool with no permission"
    for row in _by_source(out).values():
        assert set(row) == {"source", "recorded", "count", "first", "last"}, set(row)


async def test_one_shop_never_sees_another_shops_counts(db, tenant_ctx):
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()
    await _two_periods(db, tenant_ctx.tenant_id)

    await bind_tenant(db, other.id)
    theirs = _by_source(await T._si_data_status(db, other.id))
    assert all(row["count"] == 0 for row in theirs.values()), "another shop's rows were counted"


async def test_a_deleted_order_is_not_counted(db, tenant_ctx):
    from sqlalchemy import update

    from app.modules.orders.models import Order
    from tests.test_si_why_tool import _orders

    await _orders(db, tenant_ctx.tenant_id, n=3, days_ago=2, total="10.00", tag="del")
    await db.execute(
        update(Order)
        .where(Order.tenant_id == tenant_ctx.tenant_id)
        .values(deleted_at=datetime.now(UTC))
    )
    await db.flush()
    row = _by_source(await T._si_data_status(db, tenant_ctx.tenant_id))["orders"]
    assert row["count"] == 0 and row["recorded"] is False


async def test_the_old_static_text_is_gone(db, tenant_ctx):
    out = await T._si_data_status(db, tenant_ctx.tenant_id)
    assert "maturity_curves" not in str(out)
    assert "not built yet" not in str(out)


async def test_it_still_works_through_the_registered_tool(db, tenant_ctx):
    await _two_periods(db, tenant_ctx.tenant_id)
    T.register_si_tools()
    out = await get_tool("si_metric").handler(db, tenant_ctx.tenant_id, mode="status")
    assert _by_source(out)["orders"]["recorded"] is True
    assert get_tool("si_metric").requires is None  # it needs no permission, as before


def test_the_description_tells_the_model_when_to_use_it_and_what_it_does_not_hold():
    T.register_si_tools()
    text = get_tool("si_metric").description.lower()
    for meaning in (
        "what the shop has recorded",
        "whether",
        "first and last",
        "no amounts",
    ):
        assert meaning in text, f"the description lost: {meaning!r}"
    # the empty-answer rule is what stops "no data" from meaning three different things
    assert "empty" in text and "nothing was recorded" in text
    assert "data freshness/maturity" not in text, "the old claim is still there"


async def test_every_query_is_filtered_to_the_shop_in_the_code_itself(db, tenant_ctx, monkeypatch):
    """Row level security already hides other shops, but it must not be the ONLY wall: the SQL this
    tool sends has to name the shop on every table it reads. Read from the statements run."""
    sent: list[str] = []
    original = db.execute

    async def spy(statement, *args, **kwargs):
        sent.append(str(statement))
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", spy)
    await T._si_data_status(db, tenant_ctx.tenant_id)

    reads = [q for q in sent if "FROM" in q.upper()]
    assert len(reads) == len(SOURCES), f"expected one read per source, got {len(reads)}"
    for query in reads:
        assert "tenant_id = :tenant_id" in query, f"a read does not name the shop: {query}"


async def test_a_voided_expense_does_not_count_as_recorded(db, tenant_ctx):
    cat = await _category(db, tenant_ctx.tenant_id)
    await _expense(db, tenant_ctx.tenant_id, cat, 40, days_ago=2, status="voided")
    row = _by_source(await T._si_data_status(db, tenant_ctx.tenant_id))["expenses"]
    assert row["count"] == 0 and row["recorded"] is False

    await _expense(db, tenant_ctx.tenant_id, cat, 40, days_ago=2, status="posted")
    row = _by_source(await T._si_data_status(db, tenant_ctx.tenant_id))["expenses"]
    assert row["count"] == 1 and row["recorded"] is True


def test_the_description_says_when_to_call_it_and_how_to_read_an_empty_source():
    T.register_si_tools()
    text = get_tool("si_metric").description
    for sentence in (
        "Call it when an answer comes back empty or surprising",
        "or when the owner asks what data you have",
        "An empty source means nothing was recorded in the system, not that the number is zero.",
    ):
        assert sentence in text, f"the description lost: {sentence!r}"
