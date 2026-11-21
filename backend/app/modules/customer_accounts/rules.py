"""The rules of a customer account: pure, exact, no database.

Sign convention (one place, never flipped): a POSITIVE balance is what the customer OWES the
shop; a NEGATIVE balance is credit the shop OWES the customer (an unused deposit).

    charge          +  a sale on account: the customer now owes more
    payment         -  the customer paid down what they owe
    deposit         -  money taken in advance: the shop now holds the customer's credit
    deposit_applied +  an advance used up against a sale (it stops being credit)
    adjustment      +/- a manager's correction, always with a reason
    reversal        +/- undoes an earlier entry, equal and opposite

The balance is the SUM of the entries and is never stored as a number to edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ENTRY_TYPES = ("charge", "payment", "deposit", "deposit_applied", "adjustment", "reversal")
# What each kind does to the balance, as a sign applied to a POSITIVE amount.
# adjustment and reversal carry their own sign in the amount, so they are not listed here.
SIGN = {"charge": 1, "payment": -1, "deposit": -1, "deposit_applied": 1}
SIGNED_BY_CALLER = frozenset({"adjustment", "reversal"})
_CENT = Decimal("0.01")
MAX_ENTRY = Decimal("999999999.99")


class AccountRuleError(ValueError):
    """A ledger rule was broken; the message is written for the cashier."""


def money(value: object, field: str = "amount") -> Decimal:
    try:
        d = Decimal(str(value).strip())
    except Exception as exc:  # noqa: BLE001 - any parse failure is the same refusal
        raise AccountRuleError(f"{field} must be a number") from exc
    if not d.is_finite():
        raise AccountRuleError(f"{field} must be a finite number")
    if d != d.quantize(_CENT, rounding=ROUND_HALF_UP):
        raise AccountRuleError(f"{field} cannot have fractions of a piaster")
    d = d.quantize(_CENT, rounding=ROUND_HALF_UP)
    if abs(d) > MAX_ENTRY:
        raise AccountRuleError(f"{field} is too large")
    return d


def signed_amount(entry_type: str, amount: object) -> Decimal:
    """The effect of one entry on the balance. Positive amount in, signed effect out."""
    if entry_type not in ENTRY_TYPES:
        raise AccountRuleError(f"unknown entry type {entry_type!r}")
    value = money(amount)
    if entry_type in SIGNED_BY_CALLER:
        if value == 0:
            raise AccountRuleError("an adjustment or reversal cannot be zero")
        return value
    if value <= 0:
        raise AccountRuleError("the amount must be more than zero")
    return value * SIGN[entry_type]


def balance(effects: list[Decimal]) -> Decimal:
    return sum(effects, Decimal("0.00"))


@dataclass(frozen=True)
class CreditDecision:
    allowed: bool
    reason: str | None
    owed_after: Decimal
    available_after: Decimal | None  # None means no limit is set


def check_credit_sale(
    *,
    current_balance: Decimal,
    sale_total: Decimal,
    paid_now: Decimal,
    credit_limit: Decimal | None,
    blocked: bool = False,
) -> CreditDecision:
    """May this sale go on the customer's account, and what would they owe afterwards?

    ``paid_now`` is what the customer hands over at the till; only the rest goes on account. A
    customer holding an unused deposit (negative balance) has that credit count in their favour.
    A limit of ``None`` means no limit; a limit of 0 means no credit at all.
    """
    if sale_total <= 0:
        raise AccountRuleError("the sale total must be more than zero")
    if paid_now < 0:
        raise AccountRuleError("the amount paid now cannot be negative")
    if paid_now > sale_total:
        raise AccountRuleError("the amount paid now is more than the sale")
    on_account = sale_total - paid_now
    owed_after = current_balance + on_account
    if on_account == 0:
        return CreditDecision(True, None, owed_after, _available(credit_limit, owed_after))
    if blocked:
        return CreditDecision(False, "العميل موقوف، لا بيع آجل", owed_after, None)
    if credit_limit is None:
        return CreditDecision(True, None, owed_after, None)
    if owed_after > credit_limit:
        over = owed_after - credit_limit
        return CreditDecision(
            False,
            f"يتجاوز حد الائتمان بمقدار {over}",
            owed_after,
            _available(credit_limit, current_balance),
        )
    return CreditDecision(True, None, owed_after, _available(credit_limit, owed_after))


def _available(limit: Decimal | None, owed: Decimal) -> Decimal | None:
    if limit is None:
        return None
    return max(limit - owed, Decimal("0.00"))


def apply_deposit(*, balance_now: Decimal, sale_total: Decimal) -> Decimal:
    """How much of a customer's unused deposit a sale can use: never more than they hold, never
    more than the sale. A customer who owes money (positive balance) has no deposit to use."""
    held = max(-balance_now, Decimal("0.00"))
    return min(held, sale_total)
