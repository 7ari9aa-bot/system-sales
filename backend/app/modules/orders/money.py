"""Money rules for the ORDERS domain — one ``Decimal`` discipline.

Money is a ``Decimal`` quantized to the currency's two places and never a
``float``. The rules that decide *how much* money an order holds live here, free
of any session, so they can be exercised without a database.

Each function below exists because the money path got it wrong in a way that
cost real money:

* ``to_money`` — amounts were compared unquantized and then stored into
  ``NUMERIC(14,2)``. The guard reasoned about a value the database never
  stored, so three refunds of ``3.3333`` summed to ``9.9999``, passed the
  ``<= 10.00`` cap, and the three stored rows summed to ``9.99``: the last
  cent was left permanently unrefundable.
* ``positive_money`` — the old ``> 0`` check ran BEFORE any rounding, so
  ``0.001`` was accepted and then stored as ``0.00``. A refund of nothing was
  recorded, and the payment was flipped to ``partially_refunded`` anyway.
* ``order_balance`` — the over-payment guard summed payment amounts GROSS, so
  after a partial refund the refunded part still counted as collected and the
  customer could never be charged it again.
* ``reconciliation_refusal`` — ``reconcile_payment`` let a stale provider
  report move a locally CAPTURED payment to ``failed``. The captured money
  dropped out of the order's settled balance and the same amount could then be
  captured a SECOND time: a double charge, with the provider holding the first
  capture the whole time.

The module imports NOTHING but the standard library on purpose: it stays a pure
rule set, and it adds no cross-module edge (``tests/test_module_boundaries.py``
ratchets those). The caller owns the transaction AND the error type — these
functions return a reason, they never raise a domain error.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

__all__ = [
    "MONEY_QUANTUM",
    "REFUNDED_PAYMENT_STATUSES",
    "SETTLED_PAYMENT_STATUSES",
    "amount_minor",
    "from_amount_minor",
    "net_collected",
    "order_balance",
    "positive_money",
    "reconciliation_refusal",
    "to_money",
]

# Matches ``model_kit.MONEY`` — ``NUMERIC(14, 2)``.
MONEY_QUANTUM = Decimal("0.01")

# Payment statuses whose ``amount`` is money the customer has committed: the
# gross side of the collected/refunded pair.
#
# ``refunded`` is included DELIBERATELY, and this is the subtle one. A fully
# refunded payment is still gross collected money; its ``refunds`` rows
# subtract it back to zero. Dropping it from the gross side while still
# subtracting its refunds counts the refund twice and reads the order as
# over-refunded by the full amount.
#
# ``authorized`` is included because an outstanding authorization is money the
# customer has already committed with the provider — capturing on top of it
# would over-collect. The refunds that can exist against it are none.
SETTLED_PAYMENT_STATUSES = (
    "captured",
    "partially_refunded",
    "refunded",
    "authorized",
)

# Statuses that assert money went back to the customer. They are written ONLY
# by ``OrderService.register_refund``, which writes the matching ``refunds``
# row in the same transaction. A payment in one of these states with no refund
# row is a ledger that disagrees with itself.
REFUNDED_PAYMENT_STATUSES = ("refunded", "partially_refunded")


def to_money(value: object, field: str = "amount") -> Decimal:
    """Coerce ``value`` to a 2-place ``Decimal``, rounding as Postgres will.

    Quantizing here (not at the column) is the point: every comparison the
    service makes must be about the value that is actually going to be stored.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid number") from exc
    # ``Decimal("NaN") > 0`` raises InvalidOperation instead of answering, and
    # ``Decimal("Infinity")`` cannot be stored at all — reject both here rather
    # than leaking a driver-level error out of the service.
    if not amount.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def positive_money(value: object, field: str = "amount") -> Decimal:
    """``to_money`` plus the "greater than zero" rule, applied AFTER rounding.

    Rounding first is what stops ``0.001`` from passing the guard and then
    being stored as ``0.00``.
    """
    amount = to_money(value, field)
    if amount <= 0:
        raise ValueError(f"{field} must be greater than zero")
    return amount


def net_collected(settled_gross: object, refunded: object) -> Decimal:
    """Money the merchant actually holds: settled gross minus refunds.

    ``refunded`` must be the non-rejected refund total; the same pair of rules
    is what ``platform.metrics.net_revenue`` computes.
    """
    return to_money(settled_gross, "settled") - to_money(refunded, "refunded")


def order_balance(
    grand_total: object, settled_gross: object, refunded: object
) -> Decimal:
    """What is still collectable on the order.

    ``grand_total - net_collected(...)``. May be negative when the order has
    been refunded past its total (data drift, manual correction): callers must
    treat that as "nothing more may be collected", which ``>`` comparisons do
    naturally.
    """
    return to_money(grand_total, "grand_total") - net_collected(
        settled_gross, refunded
    )


def reconciliation_refusal(current: str, observed: str) -> str | None:
    """Why a provider report of ``observed`` may not be applied, or ``None``.

    Money states are MONOTONE. Once a payment is ``captured`` locally, the only
    way back down is a ``refunds`` row via ``register_refund`` — a later, stale
    provider report must not erase the capture, because erasing it drops the
    money out of the order's settled balance and lets the same amount be
    captured a second time.

    Returns a human-readable reason instead of raising: the caller owns the
    transaction and decides which domain error to raise.
    """
    if observed == current:
        return None
    if current == "captured":
        return (
            f"refusing to move a captured payment to '{observed}' — captured "
            "money leaves the ledger only through register_refund"
        )
    if current in REFUNDED_PAYMENT_STATUSES:
        return f"cannot reconcile a {current} payment to '{observed}'"
    if current == "failed" and observed == "captured":
        # A capture after a definitive local failure is a provider state change
        # that needs human eyes — not a silent flip.
        return "cannot reconcile a failed payment to captured"
    if observed in REFUNDED_PAYMENT_STATUSES:
        return (
            f"provider reported '{observed}' — record the refund through "
            "register_refund so it reconciles against the capture"
        )
    return None


# ---------------------------------------------------------------------------
# §47 — Minor-unit (amount_minor) helpers
# ---------------------------------------------------------------------------
# Payment provider APIs (Stripe, tap, etc.) expect amounts in MINOR units
# (integer cents/fils), not Decimal dollars/dinars. Converting at the
# provider boundary is mandatory: a ``Decimal("19.99")`` must become
# ``1999`` (cents) for USD, or ``19990`` (fils) for IQD.
#
# Most currencies have 2 decimal places (100 minor per major). A few have
# 3 (BHD, IQD, JOD, KWD, OMR) or 0 (JPY). The caller must pass the
# currency's exponent so the function is correct for every currency.


# ISO 4217 exponent lookup — the number of digits after the decimal point.
# Most currencies: 2 (100 minor per major). A few: 3 (BHD, IQD, JOD, KWD,
# OMR) or 0 (JPY, KRW). This table covers the ones this system uses.
_CURRENCY_EXPONENTS: dict[str, int] = {
    "USD": 2, "EUR": 2, "GBP": 2, "SAR": 2, "AED": 2, "EGP": 2,
    "IQD": 3, "BHD": 3, "JOD": 3, "KWD": 3, "OMR": 3,
    "JPY": 0, "KRW": 0,
}


def _exponent_for(currency: str) -> int:
    """Get the decimal exponent for a currency (default 2)."""
    return _CURRENCY_EXPONENTS.get(currency.upper(), 2)


def amount_minor(value: object, currency: str) -> int:
    """§47: convert a Decimal money value to minor units (integer).

    Examples:
        amount_minor(Decimal("19.99"), "USD") -> 1999
        amount_minor(Decimal("19.990"), "IQD") -> 19990
        amount_minor(Decimal("1000"), "JPY") -> 1000

    Raises ValueError if the value is not finite.
    """
    amount = to_money(value)
    exp = _exponent_for(currency)
    # Scale to minor units: multiply by 10^exp, then truncate to int
    scaled = amount * (Decimal(10) ** exp)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def from_amount_minor(minor: int, currency: str) -> Decimal:
    """§47: convert minor units back to a Decimal money value.

    Inverse of ``amount_minor``:
        from_amount_minor(1999, "USD") -> Decimal("19.99")
        from_amount_minor(19990, "IQD") -> Decimal("19.990")
        from_amount_minor(1000, "JPY") -> Decimal("1000")
    """
    exp = _exponent_for(currency)
    result = Decimal(minor) / (Decimal(10) ** exp)
    return result.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
