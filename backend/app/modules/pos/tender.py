"""Tender rules: how a counter sale is paid, what change is owed, what the drawer should hold.

Pure functions only: no database, no clock, no session. The cashier service resolves the shop's
settings and the sale total, hands them in, and writes whatever this module returns. Keeping the
arithmetic here means it is tested without a database and cannot drift between the sale, the
return and the shift close.

The vocabulary is the closed set of ``PAYMENT_METHODS`` in ``profiles.py``. Cash is the only
method that can be tendered above the amount owed (the customer hands over a 200 note for a
170 sale); every other method is charged exactly what it covers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.modules.errors import ValidationError

CASH = "cash"
ZERO = Decimal("0.00")


_QUANTUM = Decimal("0.01")


def to_money(value: object, field: str = "amount") -> Decimal:
    """A finite amount rounded half-up to two places, the scale of every MONEY column.

    Mirrors ``orders.money.to_money`` on purpose instead of importing it: this module is pure
    arithmetic and must not add a dependency from ``pos`` on ``orders`` internals. A bad figure
    is a ``ValidationError`` (a 422), never a bare ``ValueError``.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f"{field} must be a valid number") from None
    if not amount.is_finite():
        raise ValidationError(f"{field} must be a finite number")
    return amount.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class TenderLine:
    """One way the customer paid.

    ``amount`` is what this line covers of the sale. ``tendered`` is only for cash: the money
    physically handed over, which may exceed ``amount``. ``reference`` is the approval, RRN or
    transfer number a non-cash line may need.
    """

    method: str
    amount: Decimal
    tendered: Decimal | None = None
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class TenderResult:
    """What a validated set of tender lines means for the till."""

    lines: tuple[TenderLine, ...]
    paid: Decimal
    cash_kept: Decimal
    tendered_cash: Decimal | None
    change: Decimal
    by_method: Mapping[str, Decimal]


def parse_lines(raw: object) -> list[TenderLine]:
    """Turn the request's payment list into ``TenderLine`` values, or refuse it."""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValidationError("payments must be a list")
    lines: list[TenderLine] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValidationError(f"payments[{index}] must be an object")
        method = str(item.get("method", "")).strip()
        if not method:
            raise ValidationError(f"payments[{index}].method is required")
        amount = to_money(item.get("amount"), f"payments[{index}].amount")
        if amount <= ZERO:
            raise ValidationError(f"payments[{index}].amount must be greater than zero")
        raw_tendered = item.get("tendered")
        tendered = (
            to_money(raw_tendered, f"payments[{index}].tendered")
            if raw_tendered is not None
            else None
        )
        reference = item.get("reference")
        reference = str(reference).strip() if reference is not None else None
        lines.append(TenderLine(method, amount, tendered, reference or None))
    return lines


def settle(
    lines: Iterable[TenderLine],
    *,
    total: Decimal,
    allowed_methods: Iterable[str],
    reference_required: Iterable[str] = (),
) -> TenderResult:
    """Check a sale's tender lines against the total and the shop's rules.

    Rules:
    * every method must be one the till accepts;
    * only cash may be tendered above the amount it covers, and ``tendered`` can never be less
      than ``amount``;
    * the lines must cover the whole total (a short payment is not a settled sale: a shop that
      sells on account does so by using no payment lines at all, which the caller decides);
    * the amounts may not exceed the total, because change is a cash matter handled through
      ``tendered``, never a second way to over-collect;
    * a method the shop marked as needing a reference (card approval, transfer number) must carry
      one.
    """
    allowed = set(allowed_methods)
    needs_reference = set(reference_required)
    total = to_money(total, "total")
    chosen = tuple(lines)
    if not chosen:
        raise ValidationError("at least one payment line is required")

    paid = ZERO
    cash_amount = ZERO
    cash_tendered = ZERO
    saw_cash = False
    by_method: dict[str, Decimal] = {}
    for line in chosen:
        if line.method not in allowed:
            raise ValidationError(
                f"payment method {line.method!r} is not enabled on this till; "
                f"allowed {sorted(allowed)}"
            )
        if line.method in needs_reference and not line.reference:
            raise ValidationError(f"payment method {line.method!r} needs a reference number")
        if line.method == CASH:
            saw_cash = True
            handed = line.tendered if line.tendered is not None else line.amount
            if handed < line.amount:
                raise ValidationError("cash tendered cannot be less than the amount it covers")
            cash_amount += line.amount
            cash_tendered += handed
        elif line.tendered is not None and line.tendered != line.amount:
            raise ValidationError(f"only cash can be tendered above its amount ({line.method})")
        paid += line.amount
        by_method[line.method] = by_method.get(line.method, ZERO) + line.amount

    if paid > total:
        raise ValidationError(f"payments {paid} exceed the sale total {total}")
    if paid < total:
        raise ValidationError(f"payments {paid} do not cover the sale total {total}")

    change = to_money(cash_tendered - cash_amount, "change") if saw_cash else ZERO
    return TenderResult(
        lines=chosen,
        paid=to_money(paid, "paid"),
        cash_kept=to_money(cash_amount, "cash_kept"),
        tendered_cash=to_money(cash_tendered, "tendered_cash") if saw_cash else None,
        change=change,
        by_method={m: to_money(v, m) for m, v in by_method.items()},
    )


def expected_drawer_cash(
    *, opening_float: Decimal, movements: Iterable[tuple[str, str, Decimal]]
) -> Decimal:
    """The cash a drawer should hold, computed from its ledger rows.

    ``movements`` are ``(direction, reason, amount)`` rows from ``pos_cash_movements``. The
    figure is never stored by hand: a close is arithmetic over rows, so a missing row shows up
    as a variance instead of being hidden.
    """
    total = to_money(opening_float, "opening_float")
    for direction, _reason, amount in movements:
        value = to_money(amount, "amount")
        if direction == "in":
            total += value
        elif direction == "out":
            total -= value
        else:
            raise ValidationError(f"cash movement direction must be in or out, got {direction!r}")
    return to_money(total, "expected_cash")


def variance(*, counted: Decimal, expected: Decimal) -> Decimal:
    """Counted minus expected: positive is an overage, negative a shortage."""
    return to_money(to_money(counted, "counted") - to_money(expected, "expected"), "variance")
