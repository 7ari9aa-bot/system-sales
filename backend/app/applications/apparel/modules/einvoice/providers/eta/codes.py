"""ETA eReceipt code tables (official SDK: sdk.invoicing.eta.gov.eg/codes).

Static subsets only. The authoritative lists change at the tax authority's discretion, so
anything a merchant can *choose* (activity code, branch id, item codes) is configuration on the
device, never a constant here.
"""

from __future__ import annotations

from enum import StrEnum


class ReceiptType(StrEnum):
    """`documentType.receiptType` values for the Retail family (v1.2)."""

    SALE = "SR"
    RETURN = "RR"
    RETURN_WITHOUT_REFERENCE = "RWR"


class ReturnReason(StrEnum):
    """`header.documentUseReason` for a return without a reference receipt."""

    INTERNATIONAL = "I"
    BEFORE_ADOPTION = "B"


RECEIPT_TYPE_VERSION = "1.2"


class BuyerType(StrEnum):
    PERSON = "P"
    BUSINESS = "B"
    FOREIGNER = "F"


class PaymentMethod(StrEnum):
    """Official payment method codes."""

    CASH = "C"
    VISA = "V"
    CASH_WITH_CONTRACTOR = "CC"
    VISA_WITH_CONTRACTOR = "VC"
    VOUCHER = "VO"
    PROMOTION = "PR"
    GIFT_CARD = "GC"
    POINTS = "P"
    OTHER = "O"


class DeliveryMode(StrEnum):
    FROM_COMPANY = "FC"
    TRANSPORT_BY_OTHERS = "TO"
    TRANSPORT_BY_COMPANY = "TC"


# Sales OS tender kinds -> ETA code. The authority publishes no code for wallets or instant
# payments, so they map to OTHER. TODO(eta-support): confirm that mapping and how a split
# tender (cash + card on one receipt) must be expressed: the schema has one paymentMethod.
_TENDER_TO_ETA: dict[str, PaymentMethod] = {
    "cash": PaymentMethod.CASH,
    "card": PaymentMethod.VISA,
    "visa": PaymentMethod.VISA,
    "credit_card": PaymentMethod.VISA,
    "debit_card": PaymentMethod.VISA,
    "gift_card": PaymentMethod.GIFT_CARD,
    "voucher": PaymentMethod.VOUCHER,
    "loyalty_points": PaymentMethod.POINTS,
    "points": PaymentMethod.POINTS,
}


def payment_method_for_tender(tender: str | None) -> PaymentMethod:
    """Map an internal tender kind to the ETA code (unknown/wallet/transfer -> OTHER)."""
    return _TENDER_TO_ETA.get((tender or "").strip().lower(), PaymentMethod.OTHER)


class TaxType(StrEnum):
    VAT = "T1"


class VatSubtype(StrEnum):
    """T1 subtypes the retail flow uses."""

    EXPORT = "V001"
    EXPORT_FREE_ZONE = "V002"
    EXEMPT = "V003"
    NON_TAXABLE = "V004"
    GENERAL = "V009"
    OTHER_RATE = "V010"


# Unit code for "each" (a piece), the default for retail goods.
UNIT_EACH = "EA"

# Retail activity codes relevant to the first vertical (clothing). The merchant's own activity
# code is configuration; these are only the sanctioned defaults offered in the UI.
ACTIVITY_CLOTHING_RETAIL = "4751"  # retail in clothing-specialised stores
ACTIVITY_SHOES_CLOTHING_LEATHER_RETAIL = "4771"  # shoes, clothing and leather retail

ITEM_TYPES = frozenset({"EGS", "GS1"})
CURRENCY_EGP = "EGP"

# National id becomes mandatory for a person buyer at/above this total (receipt v1.2+).
NATIONAL_ID_THRESHOLD_EGP = 150_000
# The schema accepts at most five decimal digits.
MAX_DECIMAL_PLACES = 5
