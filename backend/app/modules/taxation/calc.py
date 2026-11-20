"""Tax arithmetic: pure functions, no database, exact Decimal.

The shelf price in an Egyptian clothing shop is the price the customer pays. So by default a
price INCLUDES tax and the tax is extracted from it: the total the customer pays never changes
because a shop turned VAT on. The alternative (price before tax, tax added on top) is supported
for B2B shops that quote that way.

Rounding rule: each line's tax is rounded to the piaster on its own (that is what is printed and
reported per line), and the document tax is the SUM of the rounded lines. Rounding the document
total once would disagree with the lines on the receipt by a piaster, and the tax authority
reconciles the lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineTax:
    """The tax split of one receipt line. ``gross`` is what the customer pays for the line."""

    net: Decimal
    tax: Decimal
    gross: Decimal
    rate: Decimal


def split_line(amount: Decimal, rate: Decimal, *, prices_include_tax: bool = True) -> LineTax:
    """Split one line's money into net, tax and gross.

    ``amount`` is the line total after any discount. With ``prices_include_tax`` the gross IS
    ``amount`` and the tax is extracted; otherwise the tax is added on top of ``amount``.
    """
    if amount < 0:
        raise ValueError("a line amount cannot be negative")
    if not (Decimal("0") <= rate <= Decimal("1")):
        raise ValueError("a tax rate is a fraction between 0 and 1")
    amount = _money(amount)
    if rate == 0:
        return LineTax(net=amount, tax=_ZERO, gross=amount, rate=rate)
    if prices_include_tax:
        net = _money(amount / (Decimal("1") + rate))
        tax = amount - net
        return LineTax(net=net, tax=tax, gross=amount, rate=rate)
    tax = _money(amount * rate)
    return LineTax(net=amount, tax=tax, gross=amount + tax, rate=rate)


@dataclass(frozen=True)
class DocumentTax:
    lines: tuple[LineTax, ...]
    net: Decimal
    tax: Decimal
    gross: Decimal


def split_document(
    amounts_and_rates: list[tuple[Decimal, Decimal]], *, prices_include_tax: bool = True
) -> DocumentTax:
    """Split every line and total them: the document figures are sums of the printed lines."""
    lines = tuple(
        split_line(a, r, prices_include_tax=prices_include_tax) for a, r in amounts_and_rates
    )
    return DocumentTax(
        lines=lines,
        net=sum((x.net for x in lines), _ZERO),
        tax=sum((x.tax for x in lines), _ZERO),
        gross=sum((x.gross for x in lines), _ZERO),
    )


def allocate_discount(line_nets: list[Decimal], discount: Decimal) -> list[Decimal]:
    """Spread an order-level discount over the lines in proportion to their value.

    The shares add up to ``discount`` EXACTLY: the last line takes what is left after the others
    are rounded, so no piaster is created or lost. A line is never discounted below zero.
    """
    if discount < 0:
        raise ValueError("a discount cannot be negative")
    total = sum(line_nets, _ZERO)
    if discount == 0 or total == 0:
        return [_ZERO for _ in line_nets]
    if discount > total:
        raise ValueError("the discount exceeds the value of the lines")
    shares: list[Decimal] = []
    given = _ZERO
    last = len(line_nets) - 1
    for index, net in enumerate(line_nets):
        share = discount - given if index == last else _money(discount * net / total)
        share = min(share, net)
        shares.append(share)
        given += share
    # A capped line can leave a remainder; put it on the first line that can still take it.
    left = discount - given
    for index, net in enumerate(line_nets):
        if left <= 0:
            break
        room = net - shares[index]
        take = min(room, left)
        shares[index] += take
        left -= take
    return shares
