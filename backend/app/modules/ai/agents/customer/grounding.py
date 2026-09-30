"""Grounding controller v1 — every numeral must trace to a fact.

The assistant replies in Arabic, so numerals are folded from Arabic-Indic
digits (٠-٩) before matching, and the Arabic decimal separator (٫) folds to
a dot. The match is substring-level by design — strictness beyond that
belongs to the offline eval suite, not the hot path; one ungrounded numeral
fails the whole reply.

Skip contract: the runner calls this ONLY when the run has tool results —
the unsourced-claim guardrail gate owns the no-tool-results case.
"""

from __future__ import annotations

import re

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


def check_grounding(reply: str, facts: list[str]) -> str | None:
    """A failure reason when some numeral matches no fact, else None.

    Substring matching both directions of precision: the fact "25.50"
    grounds a reply saying 25.5 or 25.50, and the fact "3" grounds "3
    قطع".
    """
    for numeral in extract_numerals(reply):
        if not any(numeral in fact for fact in facts):
            return f"ungrounded numeral: {numeral}"
    return None
