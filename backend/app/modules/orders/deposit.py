"""Deterministic deposit arithmetic; policies and orders remain caller-owned."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.currency import exponent_of, storage_refusal
from app.modules.orders.money import amount_minor, from_amount_minor, to_money

TYPE_NONE = "none"
TYPE_PERCENTAGE = "percentage"
TYPE_FIXED = "fixed"
DEPOSIT_TYPES = frozenset({TYPE_NONE, TYPE_PERCENTAGE, TYPE_FIXED})
BASE_ITEMS_AFTER_DISCOUNTS = "items_after_discounts"
BASE_GRAND_TOTAL = "grand_total"
CALCULATION_BASES = frozenset({BASE_ITEMS_AFTER_DISCOUNTS, BASE_GRAND_TOTAL})
_HUNDRED = Decimal(100)
# Match the application's manually entered money limit, below Numeric(14, 2)'s capacity.
MAX_POLICY_AMOUNT = Decimal("999999999.99")


def currency_amount(value: object, field: str, currency: str) -> Decimal:
    return from_amount_minor(amount_minor(value, currency), currency)


@dataclass(frozen=True)
class DepositRule:
    deposit_type: str
    deposit_value: Decimal = Decimal("0")
    calculation_base: str = BASE_GRAND_TOTAL
    minimum_deposit: Decimal | None = None
    maximum_deposit: Decimal | None = None

    @classmethod
    def from_policy(cls, policy) -> DepositRule:
        return cls(
            deposit_type=policy.deposit_type,
            deposit_value=Decimal(str(policy.deposit_value)),
            calculation_base=policy.calculation_base,
            minimum_deposit=(
                None if policy.minimum_deposit is None else Decimal(str(policy.minimum_deposit))
            ),
            maximum_deposit=(
                None if policy.maximum_deposit is None else Decimal(str(policy.maximum_deposit))
            ),
        )


def _policy_refusal(rule: DepositRule) -> str | None:
    for field, value in (
        ("deposit_value", rule.deposit_value),
        ("minimum_deposit", rule.minimum_deposit),
        ("maximum_deposit", rule.maximum_deposit),
    ):
        if value is not None and not value.is_finite():
            return f"{field} must be a finite number"
    if rule.deposit_type not in DEPOSIT_TYPES:
        return f"'{rule.deposit_type}' is not a deposit type this system computes"
    if rule.calculation_base not in CALCULATION_BASES:
        return f"'{rule.calculation_base}' is not a calculation base this system computes"
    if rule.deposit_type == TYPE_PERCENTAGE:
        if rule.deposit_value <= 0:
            return "a percentage deposit needs a value above zero — use 'none' to collect nothing"
        if rule.deposit_value > 100:
            return "a percentage deposit cannot exceed 100 — that is more than the order"
    if rule.deposit_type == TYPE_FIXED and rule.deposit_value <= 0:
        return "a fixed deposit needs an amount above zero — use 'none' to collect nothing"
    if rule.minimum_deposit is not None and rule.minimum_deposit < 0:
        return "minimum_deposit must not be negative"
    if rule.maximum_deposit is not None and rule.maximum_deposit < 0:
        return "maximum_deposit must not be negative"
    if (
        rule.minimum_deposit is not None
        and rule.maximum_deposit is not None
        and rule.minimum_deposit > rule.maximum_deposit
    ):
        return "minimum_deposit is above maximum_deposit — no amount can satisfy both"
    return None


def deposit_refusal(rule: DepositRule, *, currency: str) -> str | None:
    return storage_refusal(currency) or _policy_refusal(rule)


def deposit_for(
    rule: DepositRule,
    *,
    currency: str,
    subtotal: object,
    discount_total: object = None,
    shipping_total: object = None,
    tax_total: object = None,
    grand_total: object,
) -> Decimal:
    if exponent_of(currency) is None:
        raise ValueError(f"currency must be one this system trades in, got '{currency}'")
    refusal = _policy_refusal(rule)
    if refusal:
        raise ValueError(refusal)

    def in_currency(value: object, field: str) -> Decimal:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise ValueError(f"{field} must be a finite number")
        if amount < 0:
            raise ValueError(f"{field} must not be negative")
        return currency_amount(amount, field, currency)

    money = {
        "subtotal": in_currency(subtotal, "subtotal"),
        "discount_total": in_currency(discount_total or 0, "discount_total"),
        "shipping_total": in_currency(shipping_total or 0, "shipping_total"),
        "tax_total": in_currency(tax_total or 0, "tax_total"),
        "grand_total": in_currency(grand_total, "grand_total"),
    }
    if rule.deposit_type == TYPE_NONE:
        return in_currency(0, "deposit")
    if rule.deposit_type == TYPE_FIXED:
        raw = rule.deposit_value
    else:
        base = (
            money["grand_total"]
            if rule.calculation_base == BASE_GRAND_TOTAL
            else max(money["subtotal"] - money["discount_total"], Decimal(0))
        )
        raw = base * rule.deposit_value / _HUNDRED
    # Apply the merchant's minimum even when the percentage rounds below a minor unit.
    if rule.minimum_deposit is not None:
        raw = max(raw, rule.minimum_deposit)
    if rule.maximum_deposit is not None:
        raw = min(raw, rule.maximum_deposit)
    return in_currency(min(raw, money["grand_total"]), "deposit")


def remaining_balance(
    grand_total: object, deposit_paid: object, *, currency: str | None = None
) -> Decimal:
    if currency is None:
        total = to_money(grand_total, "grand_total")
        paid = to_money(deposit_paid, "deposit_paid")
        zero = Decimal("0.00")
    else:
        total = currency_amount(grand_total, "grand_total", currency)
        paid = currency_amount(deposit_paid, "deposit_paid", currency)
        zero = currency_amount(0, "balance", currency)
    return max(total - paid, zero)
