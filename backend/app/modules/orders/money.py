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
* ``lifetime_value`` — nothing on the order path ever wrote
  ``customers.lifetime_value``, so every segment built on it matched nobody.
  The number is money that ARRIVED (so an authorization is not in it, and
  neither is an unpaid order), and it is floored: an over-refunded ledger reads
  as zero, never as a negative customer.

The module reaches for one thing outside the standard library — the ISO 4217
table in ``app.core.currency``, which is itself data and arithmetic with no
session and no domain import — so it stays a pure rule set, and it adds no
cross-module edge (``tests/test_module_boundaries.py`` ratchets those). The
caller owns the transaction AND the error type — these functions return a
reason, they never raise a domain error.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.currency import exponent_of

__all__ = [
    "COLLECTED_PAYMENT_STATUSES",
    "MONEY_QUANTUM",
    "REFUNDED_PAYMENT_STATUSES",
    "REFUND_STATES",
    "SETTLED_PAYMENT_STATUSES",
    "amount_minor",
    "compute_totals",
    "from_amount_minor",
    "lifetime_value",
    "net_collected",
    "order_balance",
    "positive_money",
    "reconciliation_refusal",
    "refund_state",
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

# Statuses that mean money ARRIVED at the merchant — the gross side of a
# customer's lifetime value. ``SETTLED_PAYMENT_STATUSES`` minus ``authorized``:
# an authorization is still the provider's promise, and promising is not
# paying. ``refunded`` stays on the gross side for the same reason as above —
# its refund rows are what subtract it.
COLLECTED_PAYMENT_STATUSES = ("captured", "partially_refunded", "refunded")

# A refund is a MONEY position, not a lifecycle step, so it is DERIVED from the
# ledger instead of stored as an ``orders.status`` word (see ``refund_state``).
# The vocabulary is closed so a read model never invents a fourth answer.
REFUND_STATES = frozenset({"none", "partial", "full"})


def to_money(
    value: object, field: str = "amount", quantum: Decimal = MONEY_QUANTUM
) -> Decimal:
    """Coerce ``value`` to a ``Decimal`` at the currency's scale, rounding as
    Postgres will.

    Quantizing here (not at the column) is the point: every comparison the
    service makes must be about the value that is actually going to be stored.
    ``quantum`` defaults to the two places every MONEY column in this schema
    has; a caller converting to a currency's MINOR units passes that
    currency's own scale instead (§47).
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
    return amount.quantize(quantum, rounding=ROUND_HALF_UP)


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


def refund_state(settled_gross: object, refunded: object) -> str:
    """Whether the order gave its money back: ``none`` / ``partial`` / ``full``.

    Derived, deliberately, rather than stored as an ``orders.status`` word.
    ``status`` answers "where is this order in its life" — the axis
    ``TRANSITIONS`` and every status reader in the module walk — and giving
    money back does not move the goods: a partially refunded order is still
    ``shipped``, and ``shipped -> partial_refunded -> shipped`` is not a
    lifecycle. The payment rows and ``refunds`` rows already hold the truth, so
    a stored flag would be a second owner of one fact, wrong the moment a
    refund is rejected or a row is corrected by hand.

    ``refunded`` must be the same non-rejected total ``net_collected`` runs on.
    ``refunded <= 0`` answers FIRST: an unpaid order holds nothing, but it gave
    nothing back either, so the naive "net is zero, therefore full" reads every
    draft as fully refunded. A net at or below zero is ``full`` — money given
    back past the total is fully given back, never a negative order.
    """
    returned = to_money(refunded, "refunded")
    if returned <= 0:
        return "none"
    if net_collected(settled_gross, returned) <= 0:
        return "full"
    return "partial"


def lifetime_value(collected_gross: object, refunded: object) -> Decimal:
    """A customer's worth: money that arrived, minus what went back, not below
    zero.

    ``net_collected`` on the customer's own ledger, floored. The floor is the
    rule and not decoration: ``customers.lifetime_value`` feeds segment
    arithmetic (``segments.service`` compares it directly), and a ledger that
    has given back more than it holds — a refund row written before the
    over-refund cap, a manual correction — would otherwise turn the customer
    into a negative number that every report then averages in.
    """
    return max(net_collected(collected_gross, refunded), Decimal("0.00"))


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


def compute_totals(
    *,
    subtotal: object,
    discount: object = None,
    shipping: object = None,
    tax: object = None,
) -> dict[str, Decimal]:
    """The money an order actually charges, from the four components.

    ``grand_total = subtotal - discount + shipping + tax``, every term quantized
    first so the sum is the sum of what the columns will hold.

    This exists because checkout used to write ``grand_total = subtotal`` and
    leave the other three at zero, so a merchant who discounted an order still
    collected full price and one who charged shipping invoiced it nowhere.
    """
    sub = to_money(subtotal, "subtotal")
    parts = {
        "subtotal": sub,
        "discount_total": (
            Decimal("0.00") if discount is None else to_money(discount, "discount_total")
        ),
        "shipping_total": (
            Decimal("0.00") if shipping is None else to_money(shipping, "shipping_total")
        ),
        "tax_total": Decimal("0.00") if tax is None else to_money(tax, "tax_total"),
    }
    for field in ("discount_total", "shipping_total", "tax_total"):
        if parts[field] < 0:
            raise ValueError(f"{field} must not be negative")

    grand = (
        parts["subtotal"]
        - parts["discount_total"]
        + parts["shipping_total"]
        + parts["tax_total"]
    )
    if grand < 0:
        raise ValueError(
            f"discount_total {parts['discount_total']} exceeds the order total "
            f"{parts['subtotal'] + parts['shipping_total'] + parts['tax_total']} "
            "— a negative total is a refund, and a refund is a money movement "
            "with a row of its own"
        )
    parts["grand_total"] = grand
    return parts


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
# The exponent table lives in ``app.core.currency`` beside the rule that a
# three-decimal currency cannot be this tenant's default, so the two halves of
# "how is this currency quoted" cannot drift apart. The import is stdlib-only
# data: this module still reaches for no session and no domain service.


def _exponent_for(currency: str) -> int:
    """This currency's minor-unit scale.

    ``or`` would be wrong here: a zero-exponent currency (JPY, KRW) is quoted in
    whole units, and ``0 or 2`` reads that as cents.
    """
    exponent = exponent_of(currency)
    return 2 if exponent is None else exponent


def _quantum_for(currency: str) -> Decimal:
    """The smallest unit the currency is quoted in: 0.01, 0.001, or 1."""
    return Decimal(1).scaleb(-_exponent_for(currency))


def amount_minor(value: object, currency: str) -> int:
    """§47: convert a Decimal money value to minor units (integer).

    Examples:
        amount_minor(Decimal("19.99"), "USD") -> 1999
        amount_minor(Decimal("19.995"), "IQD") -> 19995
        amount_minor(Decimal("1000"), "JPY") -> 1000

    Quantized to the CURRENCY's own scale, not to ``MONEY_QUANTUM``: a
    three-decimal currency is quoted in thirds of a fil, and rounding it to
    two places here loses a whole minor unit on the way to the provider.

    Raises ValueError if the value is not finite.
    """
    amount = to_money(value, "amount", _quantum_for(currency))
    exp = _exponent_for(currency)
    scaled = amount * (Decimal(10) ** exp)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def from_amount_minor(minor: int, currency: str) -> Decimal:
    """§47: convert minor units back to a Decimal money value.

    Inverse of ``amount_minor``:
        from_amount_minor(1999, "USD") -> Decimal("19.99")
        from_amount_minor(19995, "IQD") -> Decimal("19.995")
        from_amount_minor(1000, "JPY") -> Decimal("1000")

    The quantum is the currency's, so a three-decimal amount survives the round
    trip instead of being flattened to two places by ``MONEY_QUANTUM``.
    """
    exp = _exponent_for(currency)
    result = Decimal(minor) / (Decimal(10) ** exp)
    return result.quantize(_quantum_for(currency), rounding=ROUND_HALF_UP)
