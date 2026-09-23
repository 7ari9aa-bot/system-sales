"""Canonical contact handles — the vocabulary identity resolution matches on.

Identity resolution used to be exact-string, so one human typing
``+20 100 123 4567``, ``00201001234567`` and ``01001234567`` created three
customers. Every write and every contact lookup goes through here first.

Stdlib-only on purpose: this is imported from inside DB transactions, so it
must never drag a session, SQLAlchemy or FastAPI in. The single app import is
``app.core.errors``, which is itself dependency-free, so the refusal the
caller sees is the project's own ``ValidationError`` (HTTP 400).

The honest limit: Egypt is the only market whose *national* formats are
understood without a country hint. International numbers must already carry
``+``. There is no worldwide prefix solver, and a number that cannot be
canonicalized is refused rather than stored as a guessed ``+…`` string — a
poisoned identity key is worse than a rejected row.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple

from app.core.errors import ValidationError

# 20 = Egypt, this system's default market (GAP M12 names it explicitly).
DEFAULT_COUNTRY_CODE = "20"
_TRUNK_PREFIX = "0"
_INTL_DIAL_PREFIX = "00"
# ITU-T E.164: max 15 digits. The floor of 8 keeps short junk ("12345") out of
# a field that is a uniqueness key.
_MAX_E164_DIGITS = 15
_MIN_E164_DIGITS = 8
# Egyptian national numbers: 10 digits for mobile (01x…), 9 for a landline.
# Anything else is a guess, so it is refused.
_EG_NATIONAL_LENGTHS = (9, 10)

_SEPARATORS = re.compile(r"[\s().\-\u2013\u2014]")
_WHITESPACE = re.compile(r"\s")

# The deleted ``normalize_phone_e164`` defaulted to IRAQ, so it wrapped Egyptian
# digits in ``+964``. That prefix is what the corruption detector looks for.
LEGACY_DEFAULT_COUNTRY_CODE = "964"


class ContactNormalizationError(ValidationError):
    """A handle that cannot be canonicalized; refuses the write, not the human."""


def _digits(body: str, raw: str) -> str:
    if not body or not body.isdigit():
        raise ContactNormalizationError(f"phone '{raw}' is not a dialable number")
    return body


def _e164(digits: str, raw: str) -> str:
    if not _MIN_E164_DIGITS <= len(digits) <= _MAX_E164_DIGITS:
        raise ContactNormalizationError(
            f"phone '{raw}' is not a complete international number "
            f"({_MIN_E164_DIGITS}-{_MAX_E164_DIGITS} digits required)"
        )
    return f"+{digits}"


def normalize_phone(
    raw: str | None, *, default_country_code: str = DEFAULT_COUNTRY_CODE
) -> str | None:
    """E.164 (``+`` + country code + national number) or nothing.

    ``None``/blank normalizes to ``None`` (no contact given); an unparseable
    value raises instead of returning a string that only looks canonical.
    """
    if raw is None:
        return None
    value = _SEPARATORS.sub("", raw)
    if not value:
        return None

    if value.startswith("+"):
        return _e164(_digits(value[1:], raw), raw)

    if value.startswith(_INTL_DIAL_PREFIX):
        body = _digits(value[len(_INTL_DIAL_PREFIX) :], raw)
        if body.startswith(_TRUNK_PREFIX):
            raise ContactNormalizationError(
                f"phone '{raw}' has no usable country code after its '00' prefix"
            )
        return _e164(body, raw)

    if not value.isdigit():
        raise ContactNormalizationError(f"phone '{raw}' is not a dialable number")

    if value.startswith(_TRUNK_PREFIX):
        national = _digits(value[1:], raw)
        return _eg_national(national, raw, default_country_code)

    # No trunk prefix: either '<CC><national>' or the bare national number of
    # the default market. Both are decided against that one country code only.
    if value.startswith(default_country_code):
        national = value[len(default_country_code) :]
        if national:
            return _eg_national(national, raw, default_country_code)
    return _eg_national(value, raw, default_country_code)


def _eg_national(national: str, raw: str, default_country_code: str) -> str:
    if not national.startswith(_TRUNK_PREFIX) and len(national) in _EG_NATIONAL_LENGTHS:
        return _e164(f"{default_country_code}{national}", raw)
    raise ContactNormalizationError(
        f"phone '{raw}' cannot be canonicalized without a country hint; "
        "send it in international (+…) form"
    )


def normalize_email(raw: str | None) -> str | None:
    """Trimmed, lowercased ``local@domain`` — the only form worth matching on."""
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.count("@") != 1:
        raise ContactNormalizationError(f"email '{raw}' must contain exactly one @")
    if _WHITESPACE.search(value):
        raise ContactNormalizationError(f"email '{raw}' contains whitespace")
    local, domain = value.split("@")
    if not local or not domain:
        raise ContactNormalizationError(f"email '{raw}' is missing a local or domain part")
    return f"{local.lower()}@{domain.lower()}"


def phone_candidates(
    raw: str | None, *, default_country_code: str = DEFAULT_COUNTRY_CODE
) -> list[str]:
    """Values a stored customer may answer to, canonical first.

    The raw spelling stays in the list because rows written before this layer
    hold it verbatim — a backfill is a separate decision. When the value is
    unparseable there is no canonical form to try, so it matches as itself
    (exact-string, the pre-M12 behavior) instead of raising.
    """
    if raw is None or not raw.strip():
        return []
    fallback = _SEPARATORS.sub("", raw)
    try:
        canonical = normalize_phone(raw, default_country_code=default_country_code)
    except ContactNormalizationError:
        return [fallback] if fallback else []
    return [canonical] if canonical == fallback else [canonical, fallback]


def email_candidates(raw: str | None) -> list[str]:
    """Canonical email first, raw spelling second — see ``phone_candidates``."""
    if raw is None or not raw.strip():
        return []
    fallback = raw.strip()
    try:
        canonical = normalize_email(raw)
    except ContactNormalizationError:
        return [fallback]
    return [canonical] if canonical == fallback else [canonical, fallback]


# ---------------------------------------------------------------------------
# Reading BACK what is already stored — the data half of M12.
#
# ``normalize_phone`` answers "what should I write?". These answer "what is
# already in the column, and may I touch it?", which is a different question:
# a stored value can be already-correct, fixable, or damaged beyond recovery.
# The migration and the staff report share this vocabulary so they can never
# disagree about which row is which.
# ---------------------------------------------------------------------------

STATE_BLANK = "blank"
STATE_CANONICAL = "canonical"
STATE_REVERSIBLE = "reversible"
STATE_CORRUPTED = "corrupted"
STATE_UNPARSEABLE = "unparseable"

# '+964' immediately followed by the Egyptian trunk prefix '0' — the exact
# silhouette of digits handed to the Iraq-default normalizer.
_LEGACY_WRAP = f"+{LEGACY_DEFAULT_COUNTRY_CODE}0"


class LegacyFabrication(NamedTuple):
    """What the old default wrapped, and what it therefore probably was."""

    legacy_raw: str
    suspected_phone: str | None


def legacy_fabrication(raw: str | None) -> LegacyFabrication | None:
    """Name a ``+964``-wrapped Egyptian number, or ``None`` for anything else.

    The tell is the leading ``0``: an E.164 subscriber number never carries its
    country's trunk prefix, so ``+9640…`` is not a dialable Iraqi number, while
    every genuine Iraqi row (``+9647…``, ``+9641…``) stays out of the queue.
    ``legacy_raw`` is the digit string the old code wrapped — a FACT about the
    corruption, not a guess about the customer — which is why it is safe to hand
    a human. The recovered form is labelled *suspected* and is never written
    over the real column: only a person can say whether ``+96401001234567`` was
    a mangled Egyptian number or an Iraqi one.
    """
    if raw is None:
        return None
    value = _SEPARATORS.sub("", raw)
    if not value.startswith(_LEGACY_WRAP):
        return None
    wrapped = value[len(LEGACY_DEFAULT_COUNTRY_CODE) + 1 :]
    body = wrapped[1:]
    if not body.isdigit():
        return None
    try:
        suspected = normalize_phone(body)
    except ContactNormalizationError:
        suspected = None
    return LegacyFabrication(legacy_raw=wrapped, suspected_phone=suspected)


def classify_stored_phone(raw: str | None) -> str:
    """One of ``STATE_*`` for a value ALREADY in ``customers.phone``.

    The corruption test runs FIRST on purpose: ``+96401001234567`` is a legal
    13-digit E.164 string, so "is it already canonical?" answers yes and the
    fabrication walks free.
    """
    if raw is None or not raw.strip():
        return STATE_BLANK
    if legacy_fabrication(raw) is not None:
        return STATE_CORRUPTED
    try:
        canonical = normalize_phone(raw)
    except ContactNormalizationError:
        return STATE_UNPARSEABLE
    return STATE_CANONICAL if canonical == raw else STATE_REVERSIBLE


def classify_stored_email(raw: str | None) -> str:
    """``STATE_*`` for a stored email — no corruption is possible here."""
    if raw is None or not raw.strip():
        return STATE_BLANK
    try:
        canonical = normalize_email(raw)
    except ContactNormalizationError:
        return STATE_UNPARSEABLE
    return STATE_CANONICAL if canonical == raw else STATE_REVERSIBLE


def find_canonical_collisions(
    rows: Iterable[tuple[object, object, str | None]],
) -> list[dict]:
    """Rows in ONE tenant that would land on the same canonical phone.

    Input is ``(tenant_id, row_id, stored_phone)``; output is one dict per
    clashing group — ``{"tenant_id", "canonical", "row_ids"}`` — sorted by
    (tenant, value) with ids sorted too, because a migration that picks its
    order at runtime is not reproducible.

    Only values that would actually be REWRITTEN or already occupy a canonical
    slot are considered; corrupted and unparseable ones stay where they are and
    so can never clash. A group of two means the second UPDATE would raise
    23505 against ``uq_customers_tenant_phone`` — the caller must not write it.
    """
    buckets: dict[tuple[str, str], tuple[object, list[object]]] = {}
    for tenant_id, row_id, phone in rows:
        state = classify_stored_phone(phone)
        if state not in (STATE_CANONICAL, STATE_REVERSIBLE):
            continue
        canonical = phone if state == STATE_CANONICAL else normalize_phone(phone)
        buckets.setdefault((str(tenant_id), canonical), (tenant_id, []))[1].append(row_id)
    return [
        {
            "tenant_id": original_tenant,
            "canonical": canonical,
            "row_ids": sorted(ids, key=str),
        }
        for (tenant_key, canonical), (original_tenant, ids) in sorted(buckets.items())
        if len(ids) > 1
    ]
