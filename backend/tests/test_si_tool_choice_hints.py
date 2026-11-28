"""Every analysis tool says WHEN to use it, and look-alike ones say which to use instead.

The model picks a tool from its description alone. Six of the eleven tools it once had said only
what they return, so "how many orders today" could land on the cashier summary or the order lookup
as easily as on the metric tool. These checks need no model: they pin what the descriptions must
contain.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence import tools as T
from app.modules.ai.tools import get_tool

T.register_si_tools()


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


def test_the_shop_tool_says_a_lookup_is_for_ONE_record_and_sends_totals_to_the_metric_tool():
    text = _d("si_shop")
    assert "ONE order" in text and "ONE customer" in text
    assert "si_metric" in text, "it must say where online order totals live"


def test_the_cashier_read_is_for_in_shop_sales():
    text = _d("si_shop")
    assert "point-of-sale" in text and "in-shop" in text


def test_each_read_a_tool_can_run_is_named_in_its_description() -> None:
    """A read the description never mentions cannot be chosen by the model."""
    from typing import get_args

    for tool, parameter in (("si_metric", "mode"), ("si_shop", "view"), ("si_finance", "report")):
        spec = get_tool(tool)
        field = spec.args_schema.model_fields[parameter]
        for value in get_args(field.annotation):
            assert f"{value} =" in spec.description, f"{tool} never explains {parameter}={value}"


def test_the_hints_stay_short_because_every_tool_is_paid_for_on_every_message() -> None:
    import json

    chars = sum(
        len(_d(n))
        + len(json.dumps(get_tool(n).args_schema.model_json_schema(), ensure_ascii=False))
        for n in T.SI_TOOLS
    )
    # 7962 with eleven tools, 4988 with three; growing past this is a decision, not drift.
    # 5600 -> 7400 for si_cashier (7 drawer/cash views in one tool). Measured: main was ALREADY
    # over the old ceiling at 5822 before this tool existed, and this change takes it to 7356, so
    # the raise is the new tool's ~1534 characters, not a re-baselining of the existing ones. The
    # description is kept to one line per view; if a fifth tool is added, split or shorten first.
    assert chars < 7400, f"the tool descriptions and schemas grew to {chars} characters"


def test_the_shop_tool_never_invites_a_guessed_lookup():
    """Seen live: after a customer list the model searched orders for "أ" and "01" (a 70 s answer).
    The order and customer reads need a query the owner gave or a result showed; ranking customers
    is another tool's job, and the description says so."""
    T.register_si_tools()
    text = get_tool("si_shop").description
    assert "never guess one" in text
    assert "never try letters or digits to see what comes back" in text
    assert "an earlier result showed" in text
    # "best customer" goes to the read that ranks by spend, and the description says the activity
    # view answers a different question (who messaged), so the two are never mixed up
    assert "'Best customer' is top_customers" in text
    assert "who MESSAGED the shop, not who bought" in text
