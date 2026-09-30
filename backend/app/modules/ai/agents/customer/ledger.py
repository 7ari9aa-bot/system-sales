"""Fact ledger v1 — the numbers a reply may honestly use (grounding §12).

Facts come ONLY from tool results the run actually executed, plus — for the
order tool — the quantities the model itself requested: the customer must
hear their own quantity echoed, and that number lives in the tool ARGUMENTS,
not the result. Anything else the model writes is unsourced and the
grounding controller will bounce it.
"""

from __future__ import annotations


def _walk_scalars(value, out: list[str]) -> None:
    """Collect every non-bool scalar leaf as its string form."""
    if isinstance(value, dict):
        for child in value.values():
            _walk_scalars(child, out)
    elif isinstance(value, list):
        for child in value:
            _walk_scalars(child, out)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float, str)):
        out.append(str(value))


def _walk_quantities(value, out: list[str]) -> None:
    """Collect only values under a 'quantity' key (create_order's args shape)."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "quantity" and isinstance(child, int) and not isinstance(child, bool):
                out.append(str(child))
            else:
                _walk_quantities(child, out)
    elif isinstance(value, list):
        for child in value:
            _walk_quantities(child, out)


def facts_from_tool_calls(tool_calls_made: list[dict]) -> list[str]:
    """String facts from every OK tool result of this run.

    Failed or denied tool calls contribute nothing — their error text must
    never become quotable "data". Money stays the exact Decimal string the
    tools serialized (§47), which is what makes substring matching reliable
    for prices.
    """
    facts: list[str] = []
    for call in tool_calls_made:
        if call.get("status") != "ok":
            continue
        result = call.get("result")
        if isinstance(result, dict):
            _walk_scalars(result, facts)
        if "order" in str(call.get("name", "")):
            _walk_quantities(call.get("args"), facts)
    return facts
