"""A tool description is the first thing a model reads: it must not name a missing metric.

``si_get_metric`` said "orders/revenue/refunds". There is no metric called ``revenue``: the
model took the description at its word, called with ``revenue`` and spent two of its ten tool
calls learning the real names from the refusal. Any ordinary model does the same, and the model
is a per-shop setting, so the descriptions have to be right rather than the model clever.

The names are read from the registry the tools validate against, so a metric added or removed
later cannot leave the description lying.
"""

from __future__ import annotations

from app.modules.ai.agents.sales_intelligence.tools import (
    _metric_registry,
    register_si_tools,
)
from app.modules.ai.tools import get_tool

METRIC_TOOLS = ("si_get_metric", "si_compare_periods", "si_breakdown")


def _descriptions() -> dict[str, str]:
    register_si_tools()
    return {name: get_tool(name).description for name in METRIC_TOOLS}


def test_the_descriptions_list_every_computable_metric():
    _, computable, _ = _metric_registry()
    for name, text in _descriptions().items():
        for metric in computable():
            assert metric in text, f"{name} does not offer {metric}"


def test_the_descriptions_do_not_invent_a_metric():
    _, computable, _ = _metric_registry()
    real = set(computable())
    for name, text in _descriptions().items():
        assert "orders/revenue/refunds" not in text, name
        listed = text.split("Metrics:")[-1].split(".")[0]
        for word in (w.strip() for w in listed.split(",")):
            assert word in real, f"{name} names '{word}', which is not a computable metric"


def test_a_derived_metric_is_not_offered_as_computable():
    _, computable, _ = _metric_registry()
    for text in _descriptions().values():
        for derived in {"aov", "net_revenue"} - set(computable()):
            assert derived not in text
