"""The closed list of dialects a shop owner can choose, and how an unset shop gets one.

This lives in ``identity`` because the choice is a shop SETTING (``tenants.dialect``): identity owns
which values are allowed and the default for a shop that never chose. The assistant (``ai``) only
reads it and supplies the wording, so the dependency runs ai -> identity and never the other way.

NULL in the column is an answer, not a gap: "the owner never chose". The default is then derived
from the shop's currency, the nearest thing the tenant has to a country. A stored value that is not
on the list fails closed to the neutral register instead of guessing a dialect nobody chose.
"""

from __future__ import annotations

#: The closed list, in the order the settings screen offers it. Mirrored by the database CHECK
#: ``tenants_dialect_listed`` (migration fe2026111209); a test keeps the two from drifting.
CHOICES: tuple[str, ...] = ("egyptian", "gulf", "levantine", "maghrebi", "msa")

#: The neutral register: what an unknown value or an unmapped currency resolves to.
NEUTRAL = "msa"

#: Currency -> dialect, the default for a shop that never chose. Only the currencies the shop
#: settings offer today; any other currency is neutral rather than a guess.
CURRENCY_DEFAULT: dict[str, str] = {
    "EGP": "egyptian",
    "SAR": "gulf",
    "AED": "gulf",
    "QAR": "gulf",
    "KWD": "gulf",
    "JOD": "levantine",
    "MAD": "maghrebi",
}

#: Where the dialect in use came from, so a screen can say "from your currency" honestly.
SOURCE_OWNER = "owner"
SOURCE_CURRENCY = "currency"
SOURCE_DEFAULT = "default"


def is_valid(value: str | None) -> bool:
    """True for a listed key, and for the empty value that clears the choice."""
    return not value or value in CHOICES


def resolve(stored: str | None, currency: str | None) -> tuple[str, str]:
    """``(dialect, source)``: the owner's choice, else the currency's, else neutral.

    A stored value that is not on the list is neither: it fails closed to neutral."""
    if stored:
        return (stored, SOURCE_OWNER) if stored in CHOICES else (NEUTRAL, SOURCE_DEFAULT)
    mapped = CURRENCY_DEFAULT.get((currency or "").upper())
    if mapped:
        return mapped, SOURCE_CURRENCY
    return NEUTRAL, SOURCE_DEFAULT


def dialect_refusal(value: str | None) -> str | None:
    """Why this is not a dialect the shop may choose, or ``None``."""
    if is_valid(value):
        return None
    shown = (value or "")[:24]
    return f"unknown dialect {shown!r}; choose one of: {', '.join(CHOICES)}"
