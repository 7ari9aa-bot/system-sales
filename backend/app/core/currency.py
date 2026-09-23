"""ISO 4217 facts this system depends on: what a code means, and what it costs.

Standard library only, on purpose (§47). Three places need the same answer —
``orders.money`` converts to a provider's MINOR units, the tenant settings
service decides whether a currency can be traded in at all, and the catalog
labels a price tier — and a second copy of the table is how a price ends up
rounded differently on the way to the provider than on the way into the row.

The scope is deliberately small: these are the currencies this market quotes
in, plus the ones a payment provider hands back. An unlisted code has no
exponent, so it is refused rather than guessed at — a wrong guess here is a
wrong amount, not a wrong label.
"""

from __future__ import annotations

__all__ = [
    "CURRENCY_EXPONENTS",
    "PLATFORM_BILLING_CURRENCY",
    "STORED_DECIMALS",
    "SUPPORTED_CURRENCIES",
    "exponent_of",
    "minor_unit_of",
    "storage_refusal",
]

#: What the platform bills ITS tenants in, and the currency every AI cost figure
#: is estimated in (`config.ai_monthly_cost_cap_usd`, the per-minute Whisper
#: price). A tenant's own `tenants.currency` is what its CUSTOMERS pay it, which
#: is a different question — an invoice for dollars stamped SAR would carry a
#: currency no number on the row is in (§47's label rule, applied in the
#: platform's direction rather than the tenant's).
PLATFORM_BILLING_CURRENCY = "USD"

# The number of digits after the decimal point — i.e. how many minor units make
# one major. Most currencies: 2 (pennies, qurush, fils). A few Gulf dinars are
# quoted to 3 (a fil is a thousandth), and a handful have no minor unit at all.
CURRENCY_EXPONENTS: dict[str, int] = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "SAR": 2,
    "AED": 2,
    "EGP": 2,
    "MAD": 2,
    "TND": 2,
    "LBP": 2,
    "SYP": 2,
    "YER": 2,
    "SOS": 2,
    "DJF": 0,
    "GNF": 0,
    "JPY": 0,
    "KRW": 0,
    "VUV": 0,
    "XOF": 0,
    "XAF": 0,
    "CLP": 0,
    "ISK": 0,
    "IQD": 3,
    "BHD": 3,
    "JOD": 3,
    "KWD": 3,
    "OMR": 3,
}

SUPPORTED_CURRENCIES = tuple(sorted(CURRENCY_EXPONENTS))

#: Every MONEY column in this schema is ``NUMERIC(14, 2)`` (``model_kit.MONEY``).
STORED_DECIMALS = 2


def exponent_of(code: str) -> int | None:
    """Digits after the decimal point, or ``None`` for an unlisted code.

    ``None`` rather than the previous silent default of 2: a currency that is
    not in the table is one nobody has checked, and "unchecked" must not be
    allowed to mean "cents".
    """
    return CURRENCY_EXPONENTS.get((code or "").upper())


def minor_unit_of(code: str) -> str:
    """The human name of the currency's smallest quoted unit."""
    return {0: "unit", 3: "thousandth"}.get(exponent_of(code) or 2, "hundredth")


def storage_refusal(code: str) -> str | None:
    """Why this code cannot be a tenant's currency, or ``None``.

    A three-decimal currency cannot live in a two-decimal column: every price,
    order and refund would be rounded to a fifth of its real minor unit on the
    way in, and the ledger would disagree with the provider on every line. The
    alternative — widening every MONEY column — is a schema migration this
    system does not need until it actually sells in a third of a fil.
    """
    exponent = exponent_of(code)
    if exponent is None:
        return (
            f"'{code}' is not a currency this system trades in "
            f"(supported: {', '.join(SUPPORTED_CURRENCIES)})"
        )
    if exponent > STORED_DECIMALS:
        return (
            f"{code} is quoted to {exponent} decimal places and money here is "
            f"stored with {STORED_DECIMALS} — every amount would lose a "
            f"{minor_unit_of(code)} on write"
        )
    return None
