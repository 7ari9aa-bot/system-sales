"""Exact money parsing shared by every module that accepts an amount from a person.

`to_money` (orders) ROUNDS to two places, which silently turns 10.005 into 10.01: money the user
never typed. Anything a person keys in goes through `exact_money`, which REJECTS a third decimal.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.modules.errors import ValidationError

_CENT = Decimal("0.01")
_MAX_AMOUNT = Decimal("999999999.99")  # MONEY is Numeric(14, 2)


def exact_money(value: object, field: str = "amount") -> Decimal:
    """A strictly positive amount with at most 2 decimals. Never rounds."""
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError(f"{field} must be a valid number") from exc
    if not amount.is_finite():
        raise ValidationError(f"{field} must be a finite number")
    if amount != amount.quantize(_CENT):
        raise ValidationError(f"{field} must have at most 2 decimal places")
    if amount <= 0:
        raise ValidationError(f"{field} must be greater than zero")
    if amount > _MAX_AMOUNT:
        raise ValidationError(f"{field} is too large")
    return amount.quantize(_CENT)
