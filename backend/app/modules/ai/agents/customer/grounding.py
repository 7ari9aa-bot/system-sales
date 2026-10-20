"""Grounding controller v1 — every numeral must trace to a fact.

The assistant replies in Arabic, so numerals are folded from Arabic-Indic
digits (٠-٩) before matching, and the Arabic decimal separator (٫) folds to
a dot. The match is substring-level by design — strictness beyond that
belongs to the offline eval suite, not the hot path; one ungrounded numeral
fails the whole reply.

Skip contract: the runner calls ``check_grounding`` ONLY when the run has tool
results. The no-tool-results case is owned by ``check_unsourced_numerals``
below: the system prompt makes tools the ONLY source of a number a reply may
state, so a numeral with no successful tool behind it (and not echoed from the
customer's own message) is an unsourced claim, whatever it is about. The
financial-claim guardrail alone cannot see "الاسترجاع خلال 14 يوم" or
"بنقفل الساعة 10", because it only recognises price / stock / money wording.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_ARABIC_INDIC = str.maketrans(
    {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "٫": ".",
    }
)
_NUMERAL_RE = re.compile(r"\d+(?:\.\d+)?")

CORRECTION_INSTRUCTION = (
    "Your previous draft contained numbers that no tool result supports. "
    "Rewrite the reply using ONLY numbers the tools returned — exact prices, "
    "quantities and counts, never invented or rounded. Keep the same tone, "
    "language, and helpfulness."
)


def extract_numerals(text: str) -> list[str]:
    """Arabic-Indic digits folded to Western, then every numeral as text."""
    return _NUMERAL_RE.findall(text.translate(_ARABIC_INDIC))


def _numeral_matches_fact(numeral: str, fact: str) -> bool:
    """True if numeral numerically equals fact or matches as a discrete number.

    The FACT side folds too: merchant-authored content (store info, knowledge
    items) is full of Arabic-Indic digits, while the model almost always
    writes Western digits. Matching the fact verbatim blocked every grounded
    reply that quoted such content — the reply side folds, so the fact side
    must fold with the same table.
    """
    fact_str = fact.strip().translate(_ARABIC_INDIC)
    # 1. Exact numeric equality (handles precision: 25.5 == 25.50, 100 == 100.00)
    try:
        if Decimal(numeral) == Decimal(fact_str):
            return True
    except (InvalidOperation, ValueError):
        pass

    # 2. Discrete number match in fact text (P1-10: (?<![\w.])N(?![\w.]))
    # Prevents "3" from matching inside UUIDs, hex strings, or longer numerals like "135".
    pattern = re.compile(rf"(?<![\w.]){re.escape(numeral)}(?![\w.])")
    if pattern.search(fact_str):
        return True

    return False


def check_grounding(reply: str, facts: list[str]) -> str | None:
    """A failure reason when some numeral matches no fact, else None.

    P1-10: Strict whole-number and Decimal equivalence: the fact "25.50"
    grounds "25.5" or "25.50", and fact "3" grounds "3 قطع", but numeral "3"
    will never match inside a UUID or inside "135".
    """
    for numeral in extract_numerals(reply):
        if not any(_numeral_matches_fact(numeral, fact) for fact in facts):
            return f"ungrounded numeral: {numeral}"
    return None


def check_unsourced_numerals(reply: str, customer_message: str | None) -> str | None:
    """A failure reason when a run with NO tool facts still states a number.

    Called only when the run produced no usable facts (no tool ran, none
    succeeded, or the ones that did returned nothing). Then a numeral has two
    legitimate sources: ``0`` ("none"), and the customer's own message.
    "عايز 2 تيشرت" -> "تمام، 2 تيشرت" is an echo, not a claim, and blocking it
    would silence an innocent confirmation. Anything else is a figure the model
    produced from nowhere (a return window, closing hour, delivery time,
    warranty length, size guidance) and the customer must not receive it.

    Same normalisation as ``check_grounding`` (Arabic-Indic digits and the
    Arabic decimal separator fold first), compared numerically, so "١٤" in the
    customer's message covers a reply that says "14".
    """
    echoed: list[Decimal] = []
    for numeral in extract_numerals(customer_message or ""):
        try:
            echoed.append(Decimal(numeral))
        except InvalidOperation:
            continue
    for numeral in extract_numerals(reply):
        try:
            value = Decimal(numeral)
        except InvalidOperation:
            return f"unsourced numeral: {numeral}"
        if value != 0 and value not in echoed:
            return f"unsourced numeral: {numeral}"
    return None
