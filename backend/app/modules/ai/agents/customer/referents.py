"""Referent resolver (spec §8) — what "التاني" points at.

The customer says "ابعت لي صورة التاني". The SECOND one — according to
WHAT? According to `shown_items` in the conversation state, in the order the
system showed them. This module maps ordinal and positional markers in the
utterance onto that list, with Arabic normalization (hamza/alef variants,
diacritics, teh-marbuta) so spoken forms match.

Honest limits, on purpose: the v1 vocabulary covers first/second/third,
"the last one", "the previous one", and bare "ده/دي" (the current topic).
Beyond third the customer names the product or sends the photo — guessing
"التاسع" against a three-item list is how confident-wrong happens. No match
or an out-of-range position returns None: the caller ASKS, never guesses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Diacritics (harakat) stripped before matching.
_HARAKAT_RE = re.compile(r"[\u064b-\u0652\u0670]")

#: marker → 1-based position in shown_items (position -1 = the last shown).
_ORDINALS: dict[str, int] = {
    "الاول": 1,
    "الاولاني": 1,
    "التاني": 2,
    "الثاني": 2,
    "التالت": 3,
    "التالث": 3,
    "الثالث": 3,
}

#: markers that mean "the last one shown" (the current topic of the chat).
_LAST_MARKERS = ("الاخير", "اللي فات", "الفات", "ده", "دي", "دا")


def normalize_arabic(text: str) -> str:
    """Lowercase + strip diacritics + unify alef/yeh/teh-marbuta forms."""
    text = _HARAKAT_RE.sub("", text)
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ـ": "",  # tatweel
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.lower()


@dataclass(slots=True)
class Referent:
    """One resolved pointing: which shown item, at which 1-based position."""

    product_id: str
    position: int
    marker: str


def resolve_referent(utterance: str, shown_items: list[str]) -> Referent | None:
    """Map an ordinal/positional marker onto the shown_items list.

    Positions are 1-based over the order the items were SHOWN. None means
    "no referent" OR "the referent outruns what was shown" — both cases the
    caller must handle by asking, not by picking something plausible.
    """
    if not shown_items:
        return None
    text = normalize_arabic(utterance or "")

    for marker, position in _ORDINALS.items():
        if marker in text:
            return _at(shown_items, position, marker)

    for marker in _LAST_MARKERS:
        if marker in text:
            return _at(shown_items, len(shown_items), marker)
    return None


def _at(shown_items: list[str], position: int, marker: str) -> Referent | None:
    if position < 1 or position > len(shown_items):
        return None
    return Referent(product_id=shown_items[position - 1], position=position, marker=marker)
