"""The metric tool tells the model which breakdown each metric allows, read from the registry.

Seen live: 9 of the 15 tool errors in three days were one mistake, asking for a breakdown the metric
does not have (collected_revenue by channel, orders_placed by carrier or customer, anything by
month). The error text is good, but every one cost a whole model round (6 to 10 s) to learn what the
description could have said. The table is read from the metric registry, never typed, so a metric
added or changed there cannot leave the description stale.
"""

from __future__ import annotations

import pytest

from app.applications.apparel.modules.ai.agents.sales_intelligence import tools as T
from app.applications.apparel.modules.ai.tools import get_tool


def _description() -> str:
    T.register_si_tools()
    return get_tool("si_metric").description


def _allowed() -> dict[str, list[str]]:
    """What a breakdown call can actually run: declared by the registry AND compiled."""
    from app.applications.apparel.modules.analytics import compiler as C

    registry, names, _ = T._metric_registry()
    reg = registry() if callable(registry) else registry
    out: dict[str, list[str]] = {}
    for n in sorted(names()):
        if n not in C._BREAKDOWN_STATEMENTS:
            continue
        compiled = C._BREAKDOWN_STATEMENTS[n][1]
        if compiled in reg[n].dimensions_allowed:
            out[n] = [compiled]
    return out


def test_every_metric_is_listed_with_exactly_the_breakdowns_the_registry_allows():
    text = _description()
    for name, dims in _allowed().items():
        expected = f"{name}({'/'.join(dims)})"
        assert expected in text, f"{name} is not described as {expected}"


def test_a_breakdown_that_is_declared_but_cannot_run_is_never_offered():
    """Seen live: shipped_orders by carrier is declared in the registry, but nothing compiles it, so
    the call failed with "has no carrier breakdown path" after the description had invited it."""
    text = _description()
    split = text.split("split =")[1].split("explain =")[0]
    for dead in ("collected_revenue", "shipped_orders", "refund_amount"):
        assert dead not in split, f"{dead} has no runnable breakdown but is listed"
    for dead in ("(carrier", "product", "governorate", "method", "reason"):
        assert dead not in split.split("never month")[0]


@pytest.mark.parametrize("never", ["month", "customer", "week", "day"])
def test_a_breakdown_nobody_supports_is_named_as_unavailable_not_left_to_a_failed_call(never):
    # the model asked for these and failed; the description must say they do not exist
    assert never in _description().split("split =")[1].split("explain =")[0]


def test_the_listing_follows_the_registry_not_a_typed_copy(monkeypatch):
    from app.applications.apparel.modules.analytics import compiler as C

    monkeypatch.setitem(C._BREAKDOWN_STATEMENTS, "orders_placed", ("select 1", "zzz_dim"))
    registry, _, _ = T._metric_registry()
    reg = registry() if callable(registry) else registry
    monkeypatch.setattr(reg["orders_placed"], "dimensions_allowed", ["zzz_dim"], raising=False)
    # a spec built after the change carries it: nothing is typed in the description
    assert "orders_placed(zzz_dim)" in T._split_table()


def test_the_listing_stays_inside_the_size_bound():
    """The SAME budget the tool-choice guard reads, from tools.py.

    This test used to hold its own ceiling of 5600 while the other guard held 7400, so the two
    disagreed and main was red in both directions. The table below is the one that grows when a
    metric is added, so the bound belongs here too — but the number is not typed twice.
    """
    import json

    T.register_si_tools()
    chars = sum(
        len(get_tool(n).description)
        + len(json.dumps(get_tool(n).args_schema.model_json_schema(), ensure_ascii=False))
        for n in T.SI_TOOLS
    )
    assert chars <= T.SI_TOOL_BUDGET_CHARS, (
        f"the listing grew to {chars} characters (budget {T.SI_TOOL_BUDGET_CHARS})"
    )


def test_the_metrics_are_separated_so_one_cannot_run_into_the_next():
    table = T._split_table()
    assert len(table.split(", ")) == len(_allowed())


def test_a_compiled_breakdown_the_registry_does_not_allow_is_not_offered(monkeypatch):
    """The compiler refuses a dimension the registry does not declare, so offering it would fail."""
    from app.applications.apparel.modules.analytics import compiler as C

    monkeypatch.setitem(C._BREAKDOWN_STATEMENTS, "orders_placed", ("select 1", "zzz_undeclared"))
    assert "zzz_undeclared" not in T._split_table()
