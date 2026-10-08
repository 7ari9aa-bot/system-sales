"""Fact ledger v1 — the numbers a reply may honestly use (grounding §12).

Facts come ONLY from tool results the run actually executed, plus — for the
order tool — the quantities the model itself requested: the customer must
hear their own quantity echoed, and that number lives in the tool ARGUMENTS,
not the result. Anything else the model writes is unsourced and the
grounding controller will bounce it.
"""

from __future__ import annotations

import re
from decimal import Decimal

_IGNORE_KEY_SUFFIXES = ("_id", "_at", "_url", "_token", "_hash")
_IGNORE_KEYS = frozenset(
    {
        "id",
        "uuid",
        # NOT "sku": `search_products` publishes the SKU to the model on
        # purpose (tools.py), so the model quoting "BW-1" must be grounded.
        # Excluding it made every SKU containing a digit read as an ungrounded
        # numeral and blocked an otherwise correct reply.
        "code",
        "barcode",
        "tracking_number",
        "phone",
        "email",
        "url",
        "image",
        "media_url",
        "image_url",
    }
)
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _should_ignore_key(key: str) -> bool:
    k = key.lower()
    if k in _IGNORE_KEYS:
        return True
    return any(k.endswith(suffix) for suffix in _IGNORE_KEY_SUFFIXES)


def _is_id_or_date_string(s: str) -> bool:
    s_clean = s.strip()
    if _UUID_RE.match(s_clean):
        return True
    if _ISO_DATE_RE.match(s_clean):
        return True
    return False


def _walk_scalars(value, out: list[str]) -> None:
    """Collect non-bool scalar leaves representing actual business facts.
    Excludes UUIDs, ISO dates, URLs, and entity ID columns (P1-10)."""
    if isinstance(value, dict):
        for key, child in value.items():
            if _should_ignore_key(str(key)):
                continue
            _walk_scalars(child, out)
    elif isinstance(value, list):
        for child in value:
            _walk_scalars(child, out)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float, Decimal)):
        out.append(str(value))
    elif isinstance(value, str):
        if not _is_id_or_date_string(value):
            out.append(value)


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


def facts_from_tool_calls(
    tool_calls_made: list[dict],
    *,
    policy_facts: list[str] | None = None,
) -> list[str]:
    """String facts from every OK tool result of this run.

    Failed or denied tool calls contribute nothing — their error text must
    never become quotable "data". Money stays the exact Decimal string the
    tools serialized (§47), which is what makes substring matching reliable
    for prices.

    P1-11: Policy numbers are NOT pre-approved. A hardcoded default let every
    tenant's agent promise a 14-day return window the merchant never published,
    and grounding passed because the number was pre-approved rather than
    retrieved. A policy number is a fact only when a tool actually returned it
    (knowledge search over the tenant's own policy) or a caller passes that
    tenant's verified policy numbers in explicitly.
    """
    facts: list[str] = []
    if policy_facts:
        facts.extend(policy_facts)

    for call in tool_calls_made:
        if call.get("status") != "ok":
            continue
        result = call.get("result")
        if isinstance(result, dict):
            _walk_scalars(result, facts)
        if "order" in str(call.get("name", "")):
            _walk_quantities(call.get("args"), facts)
    return facts
