"""The metric tool tells the model which breakdown each metric allows, read from the registry.

Seen live: 9 of the 15 tool errors in three days were one mistake, asking for a breakdown the metric
does not have (collected_revenue by channel, orders_placed by carrier or customer, anything by
month). The error text is good, but every one cost a whole model round (6 to 10 s) to learn what the
description could have said. The table is read from the metric registry, never typed, so a metric
added or changed there cannot leave the description stale.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence import tools as T
from app.modules.ai.tools import get_tool


def _description() -> str:
    T.register_si_tools()
    return get_tool("si_metric").description


def _allowed() -> dict[str, list[str]]:
    registry, names, _ = T._metric_registry()
    reg = registry() if callable(registry) else registry
    return {n: list(reg[n].dimensions_allowed) for n in sorted(names())}


def test_every_metric_is_listed_with_exactly_the_breakdowns_the_registry_allows():
    text = _description()
    for name, dims in _allowed().items():
        expected = f"{name}({'/'.join(dims)})"
        assert expected in text, f"{name} is not described as {expected}"


def test_a_breakdown_the_registry_does_not_allow_is_never_attached_to_a_metric():
    text = _description()
    assert "collected_revenue(channel" not in text
    assert "orders_placed(carrier" not in text
    assert "orders_placed(customer" not in text


@pytest.mark.parametrize("never", ["month", "customer", "week", "day"])
def test_a_breakdown_nobody_supports_is_named_as_unavailable_not_left_to_a_failed_call(never):
    # the model asked for these and failed; the description must say they do not exist
    assert never in _description().split("split =")[1].split("explain =")[0]


def test_the_listing_follows_the_registry_not_a_typed_copy(monkeypatch):
    registry, names, _ = T._metric_registry()
    reg = registry() if callable(registry) else registry
    first = sorted(names())[0]
    monkeypatch.setattr(reg[first], "dimensions_allowed", ["zzz_new_dimension"], raising=False)
    # a spec built after the registry changed carries the change
    assert f"{first}(zzz_new_dimension)" in T._split_table()


def test_the_listing_stays_inside_the_size_bound():
    import json

    T.register_si_tools()
    chars = sum(
        len(get_tool(n).description)
        + len(json.dumps(get_tool(n).args_schema.model_json_schema(), ensure_ascii=False))
        for n in T.SI_TOOLS
    )
    assert chars < 5600


def test_the_metrics_are_separated_so_one_cannot_run_into_the_next():
    table = T._split_table()
    assert len(table.split(", ")) == len(_allowed())
