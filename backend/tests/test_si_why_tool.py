"""`si_why`: ONE tool for "why did it change / who buys / when / how are deliveries".

`si_analyze_drivers`, `si_analyze_seasonality`, `si_analyze_customers` and `si_analyze_fulfillment`
were four more choices for the model on every question. They are one thin router now: `focus`
picks which tested analysis runs, the analyses themselves are untouched. These tests pin that each
focus reaches the right one with the right arguments, that none of the four old names is offered
next to it, and that no permission was added or dropped by the merge.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.modules.ai.agents.sales_intelligence import tools as T
from app.modules.ai.tools import get_tool
from app.modules.customers.models import Customer
from app.modules.orders.models import Order, Shipment

NOW = datetime.now(UTC)
OLD = (
    "si_analyze_drivers",
    "si_analyze_seasonality",
    "si_analyze_customers",
    "si_analyze_fulfillment",
)
FOCUSES = ("drivers", "seasonality", "customers", "fulfillment")
_CLOCK = {"data_as_of", "computed_at"}


def _same(new, old) -> bool:
    """Equal in everything but the compute-time stamps (the originals differ on them too)."""
    if isinstance(new, dict) and isinstance(old, dict):
        return new.keys() == old.keys() and all(
            _same(new[k], old[k]) for k in new if k not in _CLOCK
        )
    if isinstance(new, list) and isinstance(old, list):
        return len(new) == len(old) and all(_same(a, b) for a, b in zip(new, old, strict=True))
    return new == old


def test_the_four_old_tools_are_replaced_by_the_metric_tool():
    assert "si_metric" in T.SI_TOOLS
    assert "si_why" not in T.SI_TOOLS, "the why reads are a mode of the metric tool now"
    for name in OLD:
        assert name not in T.SI_TOOLS, f"{name} must not be offered"


def test_the_why_reads_need_no_permission_and_are_low_risk():
    T.register_si_tools()
    spec = get_tool("si_metric")
    assert spec is not None
    # the four it replaces had no requirement; the merge must not add or drop one
    assert spec.requires is None
    assert spec.risk_level == "LOW"


def test_the_description_says_what_each_focus_is_for():
    T.register_si_tools()
    text = get_tool("si_metric").description
    for focus in FOCUSES:
        assert f"{focus} (" in text, f"the model is never told what focus={focus} is for"
    assert "days" in text and "minimum_volume" in text
    # each focus says what it MEANS and when to pick it, not just its name
    for meaning in (
        "why revenue moved",
        "more orders or a bigger basket",
        "which weekdays are strong",
        "new versus returning",
        "delivery and rejection per carrier",
    ):
        assert meaning in text, f"the description lost: {meaning!r}"


def test_args_schema_rejects_an_unknown_focus_and_keeps_the_old_defaults():
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        T.SIWhyArgs(focus="forecast")
    a = T.SIWhyArgs(focus="fulfillment")
    assert a.days == 30 and a.minimum_volume == 10


def test_args_schema_keeps_the_old_bounds():
    with pytest.raises(Exception):  # noqa: B017
        T.SIWhyArgs(focus="drivers", days=0)
    with pytest.raises(Exception):  # noqa: B017
        T.SIWhyArgs(focus="drivers", days=91)
    with pytest.raises(Exception):  # noqa: B017
        T.SIWhyArgs(focus="fulfillment", minimum_volume=0)
    with pytest.raises(Exception):  # noqa: B017
        T.SIWhyArgs(focus="fulfillment", minimum_volume=101)


async def _orders(db, tenant_id, *, n, days_ago, total, tag):
    c = Customer(tenant_id=tenant_id, name=f"c-{tag}")
    db.add(c)
    await db.flush()
    for i in range(n):
        db.add(
            Order(
                tenant_id=tenant_id,
                number=f"{tag}-{i}",
                customer_id=c.id,
                status="delivered",
                grand_total=Decimal(total),
                channel="web",
                placed_at=NOW - timedelta(days=days_ago, hours=i),
            )
        )
    await db.flush()


async def _shipments(db, tenant_id, *, n, days_ago, carrier, tag):
    c = Customer(tenant_id=tenant_id, name=f"c-{tag}")
    db.add(c)
    await db.flush()
    for i in range(n):
        order = Order(
            tenant_id=tenant_id,
            number=f"{tag}-{i}",
            customer_id=c.id,
            status="delivered",
            grand_total=Decimal("10.00"),
            channel="web",
            placed_at=NOW - timedelta(days=days_ago + 1),
        )
        db.add(order)
        await db.flush()
        db.add(
            Shipment(
                tenant_id=tenant_id,
                order_id=order.id,
                carrier=carrier,
                status="delivered",
                shipped_at=NOW - timedelta(days=days_ago),
                delivered_at=NOW - timedelta(days=days_ago - 1),
            )
        )
    await db.flush()


async def _two_periods(db, tenant_id):
    await _orders(db, tenant_id, n=6, days_ago=5, total="200.00", tag="cur")
    await _orders(db, tenant_id, n=3, days_ago=40, total="100.00", tag="prev")
    # 12 recent shipments by one carrier, 12 old ones by another: a 7 day window sees the first
    # carrier only, a 60 day window sees both
    await _shipments(db, tenant_id, n=12, days_ago=5, carrier="Bosta", tag="shr")
    await _shipments(db, tenant_id, n=12, days_ago=40, carrier="Aramex", tag="sho")


async def test_drivers_matches_the_old_analyze_drivers(db, tenant_ctx):
    await _two_periods(db, tenant_ctx.tenant_id)
    new = await T._si_why(db, tenant_ctx.tenant_id, focus="drivers", days=30)
    old = await T._si_analyze_drivers(db, tenant_ctx.tenant_id, days=30)
    assert _same(new, old)
    assert new["drivers"], "two populated periods must produce a driver breakdown"


async def test_seasonality_matches_the_old_analyze_seasonality(db, tenant_ctx):
    await _two_periods(db, tenant_ctx.tenant_id)
    new = await T._si_why(db, tenant_ctx.tenant_id, focus="seasonality", days=30)
    old = await T._si_analyze_seasonality(db, tenant_ctx.tenant_id, days=30)
    assert _same(new, old)


async def test_customers_matches_the_old_analyze_customers(db, tenant_ctx):
    await _two_periods(db, tenant_ctx.tenant_id)
    new = await T._si_why(db, tenant_ctx.tenant_id, focus="customers", days=30)
    old = await T._si_analyze_customers(db, tenant_ctx.tenant_id, days=30)
    assert _same(new, old)


async def test_fulfillment_matches_the_old_analyze_fulfillment(db, tenant_ctx):
    await _two_periods(db, tenant_ctx.tenant_id)
    new = await T._si_why(db, tenant_ctx.tenant_id, focus="fulfillment", days=30, minimum_volume=10)
    old = await T._si_analyze_fulfillment(db, tenant_ctx.tenant_id, days=30, minimum_volume=10)
    assert _same(new, old)


async def test_the_window_is_passed_through_not_fixed_at_30(db, tenant_ctx):
    """Orders 5 and 40 days old: a 7-day window sees 6 orders, a 60-day one sees all 9."""
    await _two_periods(db, tenant_ctx.tenant_id)
    for focus, old in (
        ("drivers", T._si_analyze_drivers),
        ("seasonality", T._si_analyze_seasonality),
        ("customers", T._si_analyze_customers),
        ("fulfillment", T._si_analyze_fulfillment),
    ):
        results = {}
        for days in (7, 60):
            new = await T._si_why(db, tenant_ctx.tenant_id, focus=focus, days=days)
            ref = await old(db, tenant_ctx.tenant_id, days=days)
            assert _same(new, ref), f"{focus} ignored days={days}"
            results[days] = new
        # the data really differs between the two windows, so "ignored days" cannot hide
        assert not _same(results[7], results[60]), (
            f"{focus}: a 7 and a 60 day window gave the same answer, the test proves nothing"
        )


async def test_minimum_volume_is_passed_through_to_fulfillment(db, tenant_ctx):
    await _two_periods(db, tenant_ctx.tenant_id)
    for mv in (1, 100):
        new = await T._si_why(
            db, tenant_ctx.tenant_id, focus="fulfillment", days=30, minimum_volume=mv
        )
        ref = await T._si_analyze_fulfillment(db, tenant_ctx.tenant_id, days=30, minimum_volume=mv)
        assert _same(new, ref), f"fulfillment ignored minimum_volume={mv}"


async def test_an_unknown_focus_is_refused_with_the_valid_ones(db, tenant_ctx):
    with pytest.raises((ValidationError, ValueError)) as exc:
        await T._si_why(db, tenant_ctx.tenant_id, focus="forecast")
    for focus in FOCUSES:
        assert focus in str(exc.value)


def test_the_comparison_helper_still_catches_a_real_difference():
    base = {"facts": [{"value": "4", "computed_at": "t1"}]}
    assert _same(base, {"facts": [{"value": "4", "computed_at": "t2"}]})
    assert not _same(base, {"facts": [{"value": "5", "computed_at": "t1"}]})
    assert not _same(base, {"facts": []})
