"""Grounding v1 unit tests — ledger facts + numeral tracing (pure logic).

Pins the Arabic-Indic folding (the assistant replies in Arabic), the
substring-match contract, the create_order quantity exception (facts live in
ARGS for the order tool), and that failed/denied tool calls never become
quotable facts.
"""

from __future__ import annotations

from app.modules.ai.agents.customer.grounding import (
    check_grounding,
    extract_numerals,
)
from app.modules.ai.agents.customer.ledger import facts_from_tool_calls


def test_arabic_indic_digits_fold_before_matching():
    assert extract_numerals("السعر ٢٥ جنيه") == ["25"]
    assert extract_numerals("٥٫٥ كيلو") == ["5.5"]
    assert check_grounding("السعر ٢٥ جنيه", ["25.50"]) is None
    assert check_grounding("السعر ٢٦ جنيه", ["25.50"]) is not None


def test_substring_matches_both_precisions():
    # The fact "25.50" grounds 25.5 and 25.50; the count "3" grounds "3 قطع".
    assert check_grounding("بـ 25.5 بس", ["25.50"]) is None
    assert check_grounding("3 قطع", ["3", "25.50"]) is None
    # Rounding UP to a number no tool returned is a violation.
    assert check_grounding("بـ 25.6 بس", ["25.50"]) is not None


def test_facts_come_from_ok_results_only():
    calls = [
        {"name": "search_products", "status": "ok", "args": {"query": "widget"},
         "result": {"results": [{"price": "25.50", "sku": "BW-1"}]}},
        {"name": "check_stock", "status": "error", "args": {}, "result": {"error": "boom"}},
        {"name": "create_order", "status": "denied", "args": {}, "result": {"error": "x"}},
    ]
    facts = facts_from_tool_calls(calls)
    assert "25.50" in facts and "BW-1" in facts
    # The failed call's error text must never become quotable "data".
    assert "boom" not in facts


def test_order_quantities_read_from_args_not_result():
    calls = [
        {
            "name": "create_order",
            "status": "ok",
            "args": {"items": [{"variant_id": "v1", "quantity": 3}]},
            "result": {"order_id": "o-9", "grand_total": "75.00"},
        }
    ]
    facts = facts_from_tool_calls(calls)
    assert "3" in facts  # the customer's own quantity
    assert "75.00" in facts and "o-9" in facts


def test_non_order_tool_args_do_not_leak_in():
    calls = [
        {
            "name": "search_products",
            "status": "ok",
            "args": {"query": "99", "limit": 5},
            "result": {"results": []},
        }
    ]
    facts = facts_from_tool_calls(calls)
    assert "99" not in facts  # args are facts ONLY for the order tool
    assert "5" not in facts


def test_bools_and_nones_are_not_facts():
    calls = [
        {"name": "get_customer", "status": "ok", "args": {},
         "result": {"is_blocked": False, "phone": None, "name": "سالم"}}
    ]
    facts = facts_from_tool_calls(calls)
    assert "False" not in facts and "None" not in facts
    assert "سالم" in facts
