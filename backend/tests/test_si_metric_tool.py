"""`si_metric`: ONE tool the model picks for "a number", "vs before", "split by", "what is it".

Four tools (`si_get_metric`, `si_compare_periods`, `si_breakdown`, `si_explain_metric`) were four
choices the model had to weigh on every question. They are one thin adapter now: `mode` picks
which tested computation runs, and the computation itself is untouched. These tests pin that the
adapter routes each mode to the right one and passes the right arguments, and that the four old
names are gone so an agent is never offered both.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.modules.ai.agents.sales_intelligence import tools as T
from app.modules.ai.tools import get_tool
from app.modules.customers.models import Customer
from app.modules.orders.models import Order

NOW = datetime.now(UTC)
# Stamped when the figure is computed, so two calls a millisecond apart never match on these two.
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


OLD = ("si_get_metric", "si_compare_periods", "si_breakdown", "si_explain_metric")


def test_the_four_old_tools_are_replaced_by_one():
    assert "si_metric" in T.SI_TOOLS
    for name in OLD:
        assert name not in T.SI_TOOLS, f"{name} must not be offered next to si_metric"


def test_si_metric_is_registered_with_no_permission_requirement():
    T.register_si_tools()
    spec = get_tool("si_metric")
    assert spec is not None
    # The four it replaces had no requirement; the merge must not add or drop one.
    assert spec.requires is None
    assert spec.risk_level == "LOW"


def test_the_description_names_every_mode_and_when_to_use_it():
    """The model picks a mode from this text alone, so each mode needs its own use-when sentence."""
    T.register_si_tools()
    text = get_tool("si_metric").description
    for mode in ("value", "compare", "split", "explain"):
        assert f"{mode} = " in text, f"the model is never told what mode={mode} is for"
    # explain must be fenced off from "fetch a number", the confusion it would otherwise invite
    assert "never to fetch a number" in text
    # each mode says what it MEANS and when to pick it, not just its name
    for meaning in (
        "the number for the last N days",
        "this window against the one before it",
        "divided by a dimension",
        "what the metric means and how it is counted",
    ):
        assert meaning in text, f"the description lost: {meaning!r}"
    assert "days" in text and "dimension" in text


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


async def test_value_mode_matches_the_old_get_metric(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=4, days_ago=3, total="50.00", tag="a")
    new = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="value", metric_name="orders_placed", days=30
    )
    old = await T._si_get_metric(db, tenant_ctx.tenant_id, metric_name="orders_placed", days=30)
    assert _same(new, old)
    assert new["facts"], "a populated window must report at least one fact"


async def test_compare_mode_matches_the_old_compare_periods(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=6, days_ago=5, total="200.00", tag="cur")
    await _orders(db, tenant_ctx.tenant_id, n=3, days_ago=40, total="100.00", tag="prev")
    new = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="compare", metric_name="orders_placed", days=30
    )
    old = await T._si_compare_periods(
        db, tenant_ctx.tenant_id, metric_name="orders_placed", days=30
    )
    assert _same(new, old)
    assert Decimal(new["comparisons"][0]["delta"]) == Decimal("3")


async def test_split_mode_matches_the_old_breakdown_and_passes_the_dimension(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=4, days_ago=3, total="50.00", tag="a")
    new = await T._si_metric(
        db,
        tenant_ctx.tenant_id,
        mode="split",
        metric_name="orders_placed",
        dimension="channel",
        days=30,
    )
    old = await T._si_breakdown(
        db, tenant_ctx.tenant_id, metric_name="orders_placed", dimension="channel", days=30
    )
    assert _same(new, old)
    assert new["dimensions"][0]["dimension"] == "channel"


async def test_split_mode_uses_the_dimension_it_was_given_not_always_channel(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=3, days_ago=3, total="50.00", tag="g")
    for dim in ("governorate", "product"):
        new = await T._si_metric(
            db, tenant_ctx.tenant_id, mode="split", metric_name="orders_placed", dimension=dim
        )
        assert new["dimensions"][0]["dimension"] == dim, f"asked for {dim}, answered another"


async def test_value_mode_passes_the_channel_filter_through(db, tenant_ctx):
    """Two channels, different counts: a dropped filter returns the all-channel total."""
    c = Customer(tenant_id=tenant_ctx.tenant_id, name="c-ch")
    db.add(c)
    await db.flush()
    for i, ch in enumerate(["web"] * 5 + ["whatsapp"] * 2):
        db.add(
            Order(
                tenant_id=tenant_ctx.tenant_id,
                number=f"ch-{i}",
                customer_id=c.id,
                status="delivered",
                grand_total=Decimal("10.00"),
                channel=ch,
                placed_at=NOW - timedelta(days=2, hours=i),
            )
        )
    await db.flush()

    everything = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="value", metric_name="orders_placed", days=30
    )
    only_wa = await T._si_metric(
        db,
        tenant_ctx.tenant_id,
        mode="value",
        metric_name="orders_placed",
        days=30,
        channel="whatsapp",
    )
    assert Decimal(everything["facts"][0]["value"]) == Decimal("7")
    assert Decimal(only_wa["facts"][0]["value"]) == Decimal("2"), "the channel filter was dropped"


async def test_explain_mode_matches_the_old_explain_metric(db, tenant_ctx):
    new = await T._si_metric(db, tenant_ctx.tenant_id, mode="explain", metric_name="orders_placed")
    old = await T._si_explain_metric(db, tenant_ctx.tenant_id, metric_name="orders_placed")
    assert _same(new, old)


async def test_an_unknown_mode_is_refused_with_the_valid_ones(db, tenant_ctx):
    with pytest.raises((ValidationError, ValueError)) as exc:
        await T._si_metric(db, tenant_ctx.tenant_id, mode="forecast", metric_name="orders_placed")
    for mode in ("value", "compare", "split", "explain"):
        assert mode in str(exc.value)


def test_args_schema_rejects_an_unknown_mode():
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        T.SIMetricArgs(mode="forecast", metric_name="orders_placed")


def test_args_schema_defaults_are_the_old_defaults():
    a = T.SIMetricArgs(mode="value", metric_name="orders_placed")
    assert a.days == 30
    assert a.dimension == "channel"
    assert a.channel is None


def test_the_comparison_helper_still_catches_a_real_difference():
    """Without this the helper could be hiding everything (it would pass any two dicts)."""
    base = {"facts": [{"value": "4", "computed_at": "t1"}]}
    assert _same(base, {"facts": [{"value": "4", "computed_at": "t2"}]})
    assert not _same(base, {"facts": [{"value": "5", "computed_at": "t1"}]})
    assert not _same(base, {"facts": []})
    assert not _same(base, {"facts": [{"value": "4", "computed_at": "t1", "extra": 1}]})
