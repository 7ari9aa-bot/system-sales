"""Every analysis tool says WHEN to use it, and look-alike ones say which to use instead.

The model picks a tool from its description alone. Six of the eleven said only what they return, so
"how many orders today" could land on the cashier summary or the order lookup as easily as on the
metric tool. These checks need no model: they pin what the descriptions must contain.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence import tools as T
from app.modules.ai.tools import get_tool

T.register_si_tools()

# one tool for ONE named record, one for a TOTAL: the pair a vague question confuses
LOOKUPS = ("si_find_order", "si_find_customer")


def _d(name: str) -> str:
    spec = get_tool(name)
    assert spec is not None, name
    return spec.description


@pytest.mark.parametrize("name", T.SI_TOOLS)
def test_every_tool_says_when_to_use_it(name: str) -> None:
    text = _d(name).lower()
    assert any(k in text for k in ("use for", "use to", "use only", "call it when")), (
        f"{name} only says what it returns, so the model cannot tell when to pick it"
    )


@pytest.mark.parametrize("name", T.SI_TOOLS)
def test_a_description_only_points_at_tools_that_exist(name: str) -> None:
    import re

    for ref in set(re.findall(r"\bsi_[a-z_]+\b", _d(name))):
        assert ref in T.SI_TOOLS, f"{name} sends the model to {ref}, which is not a tool"


@pytest.mark.parametrize("name", LOOKUPS)
def test_a_lookup_is_for_one_named_record_and_points_totals_elsewhere(name: str) -> None:
    text = _d(name)
    assert "ONE" in text, f"{name} must say it is for a single named record"
    assert "si_metric" in text or "si_why" in text, f"{name} must say where totals live"


def test_the_cashier_tool_is_for_in_shop_sales_and_sends_online_totals_to_the_metric_tool() -> None:
    text = _d("si_cashier_summary")
    assert "point-of-sale" in text
    assert "si_metric" in text


def test_top_products_sends_a_plain_total_to_the_metric_tool() -> None:
    assert "si_metric" in _d("si_top_products")


def test_the_hints_stay_short_because_every_tool_is_paid_for_on_every_message() -> None:
    import json

    chars = sum(
        len(_d(n))
        + len(json.dumps(get_tool(n).args_schema.model_json_schema(), ensure_ascii=False))
        for n in T.SI_TOOLS
    )
    # measured 7962 when written; growing past this is a decision, not drift
    assert chars < 8600, f"the tool descriptions and schemas grew to {chars} characters"
