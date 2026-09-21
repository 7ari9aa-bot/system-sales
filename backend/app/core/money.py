"""Spec §47 — Money value object: minor units, no floating point.

All monetary amounts are stored as integer minor units (piasters/cents)
with an ISO 4217 currency code. This eliminates floating-point rounding
errors.

§47: "Not floating point money."
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Money:
    """§47: immutable monetary value in minor units.

    Examples:
        Money(9999, "EGP")   -> 99.99 EGP (9999 piasters)
        Money(1000, "USD")  -> $10.00 (1000 cents)
        Money(0, "SAR")     -> 0.00 SAR

    The amount is ALWAYS in minor units. Use to_major() for display.
    """

    amount_minor: int
    currency: str  # ISO 4217 code

    def __post_init__(self) -> None:
        if self.amount_minor < 0:
            raise ValueError(f"Money amount_minor cannot be negative: {self.amount_minor}")
        if not self.currency or len(self.currency) != 3:
            raise ValueError(f"currency must be a 3-letter ISO code, got: {self.currency!r}")

    # --- Conversions ---

    def to_major(self) -> Decimal:
        """Return the major-unit amount as a Decimal (for display)."""
        exponent = _SUBUNIT_EXPONENTS.get(self.currency, 2)
        return Decimal(self.amount_minor) / (Decimal(10) ** exponent)

    @classmethod
    def from_major(cls, amount: float | Decimal | str, currency: str) -> Money:
        """Create Money from a major-unit amount (e.g. 99.99 EGP)."""
        decimal_amount = Decimal(str(amount))
        exponent = _SUBUNIT_EXPONENTS.get(currency, 2)
        minor = int((decimal_amount * (Decimal(10) ** exponent)).quantize(Decimal("1")))
        return Money(minor, currency)

    # --- Operations ---

    def add(self, other: Money) -> Money:
        """Add two Money values. Must be same currency."""
        self._assert_same_currency(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def subtract(self, other: Money) -> Money:
        """Subtract. Must be same currency."""
        self._assert_same_currency(other)
        result = self.amount_minor - other.amount_minor
        if result < 0:
            raise ValueError("subtraction would result in negative Money")
        return Money(result, self.currency)

    def multiply(self, factor: int | Decimal) -> Money:
        """Multiply by a scalar (e.g. quantity)."""
        if isinstance(factor, Decimal):
            minor = int((Decimal(self.amount_minor) * factor).quantize(Decimal("1")))
        else:
            minor = self.amount_minor * factor
        if minor < 0:
            raise ValueError("multiplication would result in negative Money")
        return Money(minor, self.currency)

    def allocate(self, ratios: list[int]) -> list[Money]:
        """Split across ratios without losing pennies (§47).

        Example: Money(100, "EGP").allocate([1, 1, 1]) -> [34, 33, 33]
        """
        total = sum(ratios)
        if total == 0:
            raise ValueError("ratios cannot sum to zero")

        results: list[Money] = []
        remaining = self.amount_minor
        for i, ratio in enumerate(ratios):
            if i == len(ratios) - 1:
                # Last one gets the remainder to avoid rounding loss
                results.append(Money(remaining, self.currency))
            else:
                share = (self.amount_minor * ratio) // total
                remaining -= share
                results.append(Money(share, self.currency))
        return results

    # --- Comparison ---

    def _assert_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(
                f"cannot operate on different currencies: {self.currency} vs {other.currency}"
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self.amount_minor == other.amount_minor and self.currency == other.currency

    def __lt__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount_minor < other.amount_minor

    def __le__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount_minor <= other.amount_minor

    def __gt__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount_minor > other.amount_minor

    def __ge__(self, other: Money) -> bool:
        self._assert_same_currency(other)
        return self.amount_minor >= other.amount_minor

    def __hash__(self) -> int:
        return hash((self.amount_minor, self.currency))

    def __repr__(self) -> str:
        return f"Money({self.amount_minor}, {self.currency!r})"

    def __str__(self) -> str:
        return f"{self.to_major()} {self.currency}"


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    """§47: exchange rate snapshot for cross-currency analytics.

    The original transaction amount is never changed -- the rate is stored
    alongside for reporting only.
    """

    from_currency: str
    to_currency: str
    rate: Decimal
    rate_timestamp: str  # ISO datetime
    source: str  # e.g. "ecb", "central_bank"

    def convert(self, money: Money) -> Money:
        """Convert money to the target currency at this rate."""
        if money.currency != self.from_currency:
            raise ValueError(
                f"money currency {money.currency!r} does not match rate from_currency {self.from_currency!r}"
            )
        converted_minor = int(
            (Decimal(money.amount_minor) * self.rate).quantize(Decimal("1"))
        )
        return Money(converted_minor, self.to_currency)


# ISO 4217 sub-unit exponents: currency code -> decimal places
_SUBUNIT_EXPONENTS: dict[str, int] = {
    "EGP": 2,  # piasters
    "USD": 2,  # cents
    "EUR": 2,  # cents
    "SAR": 2,  # halalas
    "AED": 2,  # fils
    "GBP": 2,  # pence
    "JPY": 0,  # no sub-unit
    "KRW": 0,  # no sub-unit
    "BHD": 3,  # fils (3 decimal places)
    "KWD": 3,  # fils
    "OMR": 3,  # baisa
    "JOD": 3,  # piasters
}
