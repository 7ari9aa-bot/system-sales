"""Typed input for the ETA eReceipt builder.

Everything the authority requires that is *not* a property of a sale (who the seller is, which
branch and activity, what the item is registered as) is passed in explicitly. Nothing here is
defaulted to a fake value: the old builder hard-coded branch ``"0"``, activity ``"4719"`` and
device ``"POS-01"``, which the authority rejects. A missing value now fails loudly at the
validator instead of being sent wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.applications.apparel.modules.einvoice.providers.eta.codes import (
    UNIT_EACH,
    BuyerType,
    DeliveryMode,
    PaymentMethod,
    ReceiptType,
    ReturnReason,
    TaxType,
    VatSubtype,
)


@dataclass(frozen=True)
class BranchAddress:
    """Seller branch address; the first five fields are mandatory for the authority."""

    governate: str
    region_city: str
    street: str
    building_number: str
    country: str = "EG"
    postal_code: str = ""
    floor: str = ""
    room: str = ""
    landmark: str = ""
    additional_information: str = ""


@dataclass(frozen=True)
class SellerProfile:
    """The registered taxpayer + branch + device that issues the receipt."""

    rin: str  # 9-digit registration number
    trade_name: str
    branch_code: str  # branch id as shown in the taxpayer profile on the e-invoicing portal
    branch_address: BranchAddress
    device_serial: str
    activity_code: str


@dataclass(frozen=True)
class BuyerProfile:
    type: BuyerType = BuyerType.PERSON
    id: str = ""
    name: str = ""
    mobile_number: str = ""
    payment_number: str = ""


@dataclass(frozen=True)
class ItemTax:
    tax_type: str = TaxType.VAT
    sub_type: str = VatSubtype.GENERAL
    rate: Decimal = Decimal("14")  # percent, 0-100


@dataclass(frozen=True)
class DiscountSpec:
    """An amount discount (``rate`` is informational: the authority recomputes from it)."""

    amount: Decimal
    description: str = "discount"
    rate: Decimal | None = None


@dataclass(frozen=True)
class EtaLine:
    """One receipt line.

    ``unit_price`` is the price *before* VAT and before any discount (the authority computes
    ``totalSale = quantity * unit_price``). Callers holding a tax-inclusive shelf price must
    back the VAT out first: see ``price_excluding_vat``.
    """

    internal_code: str
    description: str
    item_type: str  # "EGS" | "GS1"
    item_code: str
    quantity: Decimal
    unit_price: Decimal
    unit_type: str = UNIT_EACH
    tax: ItemTax = field(default_factory=ItemTax)
    commercial_discounts: tuple[DiscountSpec, ...] = ()
    item_discounts: tuple[DiscountSpec, ...] = ()
    value_difference: Decimal = Decimal("0")


@dataclass(frozen=True)
class EtaReceiptInput:
    """Everything needed to build one eReceipt."""

    receipt_number: str
    issued_at: datetime  # must be timezone-aware
    seller: SellerProfile
    buyer: BuyerProfile
    lines: tuple[EtaLine, ...]
    payment_method: PaymentMethod
    previous_uuid: str = ""  # uuid of the previous receipt from the same POS; "" for the first
    receipt_type: ReceiptType = ReceiptType.SALE
    reference_uuid: str = ""  # RR: the sale receipt being returned
    reference_old_uuid: str = ""  # corrected resend of a rejected receipt
    return_reason: ReturnReason | None = None  # RWR only
    sales_issued_at: datetime | None = None  # RWR only: when the original sale happened
    extra_receipt_discounts: tuple[DiscountSpec, ...] = ()
    currency: str = "EGP"
    exchange_rate: Decimal = Decimal("0")
    delivery_mode: DeliveryMode = DeliveryMode.FROM_COMPANY
