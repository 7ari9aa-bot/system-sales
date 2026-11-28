"""Receipt arithmetic, following the authority's published validation equations.

Source: sdk.invoicing.eta.gov.eg/main-calculations. All of those equations are checked by the
authority with a tolerance of +/-0.5, but we compute them exactly in ``Decimal`` so a receipt
never relies on that slack and so the printed receipt, the stored receipt and the submitted one
are the same numbers.

Only the subset the retail flow needs is implemented: VAT (T1) per line, commercial and item
discounts, a value difference, and receipt-level extra discounts. Table taxes (T2/T3), withholding
(T4) and the fee taxes (T5-T20) are rejected by the validator rather than silently mis-computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.applications.apparel.modules.einvoice.providers.eta.codes import MAX_DECIMAL_PLACES
from app.applications.apparel.modules.einvoice.providers.eta.models import DiscountSpec, EtaLine

_Q5 = Decimal(1).scaleb(-MAX_DECIMAL_PLACES)  # 0.00001
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def q5(value: Decimal) -> Decimal:
    """Round to the five decimal places the schema allows (half-up, like a till would)."""
    return value.quantize(_Q5, rounding=ROUND_HALF_UP)


def discount_amount(spec: DiscountSpec, base: Decimal) -> Decimal:
    """Resolve a discount to money.

    The authority's rule: when ``rate > 0`` the amount must equal ``rate * base / 100``. A
    discount given as a rate therefore always wins over a stale ``amount``.
    """
    if spec.rate is not None and spec.rate > 0:
        return q5(spec.rate * base / _HUNDRED)
    return q5(spec.amount)


def price_excluding_vat(price_including_vat: Decimal, vat_rate_percent: Decimal) -> Decimal:
    """Back VAT out of a tax-inclusive shelf price (Egyptian shelf prices include VAT)."""
    if vat_rate_percent <= 0:
        return q5(price_including_vat)
    return q5(price_including_vat / (Decimal(1) + vat_rate_percent / _HUNDRED))


@dataclass(frozen=True)
class LineAmounts:
    total_sale: Decimal
    net_sale: Decimal
    vat: Decimal
    total: Decimal
    commercial: tuple[Decimal, ...]
    item: tuple[Decimal, ...]


@dataclass(frozen=True)
class ReceiptTotals:
    total_sales: Decimal
    total_commercial_discount: Decimal
    total_items_discount: Decimal
    net_amount: Decimal
    vat_total: Decimal
    extra_discounts: tuple[Decimal, ...]
    total_amount: Decimal


def compute_line(line: EtaLine) -> LineAmounts:
    """Compute one line exactly as the authority's equations define it."""
    total_sale = q5(line.quantity * line.unit_price)
    commercial = tuple(discount_amount(d, total_sale) for d in line.commercial_discounts)
    net_sale = q5(total_sale - sum(commercial, _ZERO))
    # Item discounts are a percentage of netSale (not of totalSale).
    item = tuple(discount_amount(d, net_sale) for d in line.item_discounts)

    vat = _ZERO
    if line.tax.rate > 0:
        vat = q5((net_sale + line.value_difference) * line.tax.rate / _HUNDRED)

    total = q5(net_sale + vat - sum(item, _ZERO))
    return LineAmounts(
        total_sale=total_sale,
        net_sale=net_sale,
        vat=vat,
        total=total,
        commercial=commercial,
        item=item,
    )


def compute_totals(
    lines: list[LineAmounts],
    extra_discounts: tuple[DiscountSpec, ...] = (),
    adjustment: Decimal = _ZERO,
) -> ReceiptTotals:
    """Receipt-level sums (all are plain sums of the line values)."""
    net_amount = q5(sum((a.net_sale for a in lines), _ZERO))
    extra = tuple(discount_amount(d, net_amount) for d in extra_discounts)
    total_amount = q5(sum((a.total for a in lines), _ZERO) - sum(extra, _ZERO) + adjustment)
    return ReceiptTotals(
        total_sales=q5(sum((a.total_sale for a in lines), _ZERO)),
        total_commercial_discount=q5(sum((sum(a.commercial, _ZERO) for a in lines), _ZERO)),
        total_items_discount=q5(sum((sum(a.item, _ZERO) for a in lines), _ZERO)),
        net_amount=net_amount,
        vat_total=q5(sum((a.vat for a in lines), _ZERO)),
        extra_discounts=extra,
        total_amount=total_amount,
    )
