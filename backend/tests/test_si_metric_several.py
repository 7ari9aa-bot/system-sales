"""``si_metric`` with several metrics in one call: one model round instead of one per metric.

Measured live on production: every slow answer (40 to 55 s) called ``si_metric`` five to eight
times for the same question, once per metric, because the tool took one name. Each extra call is a
whole model round of 6 to 10 s. The names now travel together and the SAME tested read runs once per
name, so the computation, the registry check and the evidence are exactly what they were.
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.applications.apparel.modules.ai.agents.sales_intelligence import tools as T
from tests.test_si_metric_tool import _orders, _same

pytestmark = pytest.mark.usefixtures("db")

TWO = "orders_placed,collected_revenue"
TWO_PLAIN = "refund_amount,shipped_orders"


def test_names_are_split_on_commas_in_order_each_once():
    assert T._metric_names("a, b،c;a") == ["a", "b", "c"]
    assert T._metric_names("  one  ") == ["one"]
    assert T._metric_names(None) == []
    assert T._metric_names(" , ") == []


def test_more_than_the_ceiling_is_refused_with_a_message_that_says_why():
    many = ",".join(f"m{i}" for i in range(T._MAX_METRICS_PER_CALL + 1))
    with pytest.raises(ValidationError, match="at most 6"):
        T._metric_names(many)
    assert len(T._metric_names(",".join(f"m{i}" for i in range(T._MAX_METRICS_PER_CALL)))) == 6


async def test_one_name_is_exactly_the_old_single_read(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=3, days_ago=3, total="50.00", tag="s")
    one = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="value", metric_name="refund_amount", days=30
    )
    old = await T._si_get_metric(db, tenant_ctx.tenant_id, metric_name="refund_amount", days=30)
    assert _same(one, old)
    # a stray separator around one name changes nothing
    padded = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="value", metric_name=" refund_amount ,", days=30
    )
    assert _same(padded, old)


async def test_two_names_run_the_same_read_for_each_and_keep_every_fact(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=4, days_ago=3, total="50.00", tag="m")
    both = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="value", metric_name=TWO_PLAIN, days=30
    )
    a = await T._si_get_metric(db, tenant_ctx.tenant_id, metric_name="refund_amount", days=30)
    b = await T._si_get_metric(db, tenant_ctx.tenant_id, metric_name="shipped_orders", days=30)
    metrics = {f["metric"] for f in both["facts"]}
    assert {f["metric"] for f in a["facts"]} | {f["metric"] for f in b["facts"]} == metrics
    assert len(both["facts"]) == len(a["facts"]) + len(b["facts"])
    assert [m["metric"] for m in both["summary"]["metrics"]] == ["refund_amount", "shipped_orders"]


async def test_compare_with_two_names_keeps_both_comparisons(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=6, days_ago=5, total="200.00", tag="cur")
    await _orders(db, tenant_ctx.tenant_id, n=3, days_ago=40, total="100.00", tag="prev")
    both = await T._si_metric(db, tenant_ctx.tenant_id, mode="compare", metric_name=TWO, days=30)
    assert len(both["comparisons"]) >= 2


async def test_one_unknown_name_fails_the_whole_call_with_the_reads_own_message(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=2, days_ago=3, total="50.00", tag="u")
    with pytest.raises(ValidationError):
        await T._si_metric(
            db,
            tenant_ctx.tenant_id,
            mode="value",
            metric_name="orders_placed,not_a_real_metric",
            days=30,
        )


async def test_the_merged_result_is_read_by_the_evidence_collector_like_any_other(db, tenant_ctx):
    """The runner rebuilds the evidence the number gate checks from each tool result's own lists.
    Both metrics' figures must be in it, or the model's second number would be refused."""
    from app.applications.apparel.modules.ai.agents.sales_intelligence.agent import _rebuild_evidence

    await _orders(db, tenant_ctx.tenant_id, n=4, days_ago=3, total="50.00", tag="e")
    result = await T._si_metric(db, tenant_ctx.tenant_id, mode="value", metric_name=TWO, days=30)
    evidence = _rebuild_evidence([{"name": "si_metric", "status": "ok", "result": result}])
    assert {f["metric"] for f in evidence["facts"]} == {f["metric"] for f in result["facts"]}
    assert len({f["metric"] for f in evidence["facts"]}) >= 2


async def test_the_modes_that_take_no_metric_ignore_a_comma_in_it(db, tenant_ctx):
    status = await T._si_metric(db, tenant_ctx.tenant_id, mode="status", metric_name="a,b")
    assert status["capability"] == "get_data_status"


async def test_the_merged_status_is_ok_only_when_every_metric_was_ok(db, tenant_ctx, monkeypatch):
    """One metric with no data must not let the call read as complete: the model would present a
    half-measured answer as whole."""
    answers = {
        "refund_amount": {"status": "ok", "summary": {}, "facts": []},
        "shipped_orders": {"status": "no_data", "summary": {}, "facts": []},
    }

    async def fake(session, tenant_id, *, metric_name, days, channel=None, context=None):
        return dict(answers[metric_name])

    monkeypatch.setattr(T, "_si_get_metric", fake)
    mixed = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="value", metric_name=TWO_PLAIN, days=30
    )
    assert mixed["status"] == "partial"
    answers["shipped_orders"] = {"status": "ok", "summary": {}, "facts": []}
    clean = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="value", metric_name=TWO_PLAIN, days=30
    )
    assert clean["status"] == "ok"


async def test_each_metrics_limitations_reach_the_model_once(db, tenant_ctx, monkeypatch):
    """A limitation ("the profit is hidden when a cost is missing") is a safety statement. Merging
    must carry every metric's, and a note both share is said once, not twice."""
    notes = {
        "refund_amount": ["partial data", "shared note"],
        "shipped_orders": ["shared note", "cost missing"],
    }

    async def fake(session, tenant_id, *, metric_name, days, channel=None, context=None):
        return {"status": "ok", "summary": {}, "facts": [], "limitations": notes[metric_name]}

    monkeypatch.setattr(T, "_si_get_metric", fake)
    both = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="value", metric_name=TWO_PLAIN, days=30
    )
    assert both["limitations"] == ["partial data", "shared note", "cost missing"]


# --- the core sales bundle: asking for one of the three figures returns all three -------------


async def test_asking_for_one_core_metric_returns_the_other_two_for_the_same_window(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=3, days_ago=3, total="50.00", tag="b")
    r = await T._si_metric(
        db, tenant_ctx.tenant_id, mode="value", metric_name="orders_placed", days=30
    )
    assert {f["metric"] for f in r["facts"]} >= set(T._CORE_SALES_METRICS)
    assert [m["metric"] for m in r["summary"]["metrics"]] == [
        "orders_placed",
        "delivered_revenue",
        "collected_revenue",
    ]


def test_the_bundle_is_the_asked_names_first_then_the_missing_core_ones_once():
    f = T._with_the_core_sales_metrics
    assert f(["collected_revenue"], "value") == [
        "collected_revenue",
        "orders_placed",
        "delivered_revenue",
    ]
    assert f(["delivered_revenue", "orders_placed"], "compare") == [
        "delivered_revenue",
        "orders_placed",
        "collected_revenue",
    ]


@pytest.mark.parametrize("mode", ["split", "explain", "why", "activity", "status"])
def test_other_modes_never_get_the_bundle(mode):
    """split and explain answer a different question and return a different shape."""
    assert T._with_the_core_sales_metrics(["orders_placed"], mode) == ["orders_placed"]


def test_a_metric_outside_the_core_three_is_left_alone():
    assert T._with_the_core_sales_metrics(["refund_amount"], "value") == ["refund_amount"]
    assert T._with_the_core_sales_metrics([], "value") == []


def test_a_channel_filter_turns_the_bundle_off():
    """Payments cannot be filtered by channel: adding collected_revenue to 'WhatsApp sales' would
    fail a question that works without the bundle."""
    assert T._with_the_core_sales_metrics(["orders_placed"], "value", channel="whatsapp") == [
        "orders_placed"
    ]


async def test_a_channel_question_still_works_and_stays_one_metric(db, tenant_ctx):
    await _orders(db, tenant_ctx.tenant_id, n=2, days_ago=3, total="50.00", tag="ch")
    r = await T._si_metric(
        db,
        tenant_ctx.tenant_id,
        mode="value",
        metric_name="orders_placed",
        days=30,
        channel="web",
    )
    assert {f["metric"] for f in r["facts"]} == {"orders_placed"}
