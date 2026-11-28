"""Local validation of an eReceipt, mirroring the authority's published rules.

Sources: Receipt Issuance FAQ ("Core Fields Validator", "Code Validator", "National ID
Validator") and the Main Calculations page. Running them here means a bad receipt is refused at
the till, with an Arabic-translatable code, instead of being rejected hours later by the
authority after the customer has left.

Codes are our own (``ETA-L-...``). The authority's own codes (e.g. ``CF313``) only ever arrive
in a rejection and are handled in ``client``; the two namespaces never mix.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.applications.apparel.modules.einvoice.providers.eta.calc import compute_line, compute_totals
from app.applications.apparel.modules.einvoice.providers.eta.codes import (
    ITEM_TYPES,
    NATIONAL_ID_THRESHOLD_EGP,
    BuyerType,
    ReceiptType,
)
from app.applications.apparel.modules.einvoice.providers.eta.models import EtaReceiptInput

# The authority checks the sums with +/-0.5; we compute exactly, so any gap is our own bug.
_TOLERANCE = Decimal("0.5")
_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str


def _digits(value: str) -> bool:
    return value.isascii() and value.isdigit()


def validate_receipt(receipt: EtaReceiptInput, *, now: datetime | None = None) -> list[Issue]:
    """Return every problem found (empty list = safe to submit)."""
    issues: list[Issue] = []

    def add(code: str, path: str, message: str) -> None:
        issues.append(Issue(code, path, message))

    now = now or datetime.now(UTC)
    s, b = receipt.seller, receipt.buyer

    # ---- seller ----------------------------------------------------------------------
    if not (_digits(s.rin) and len(s.rin) == 9):
        add("ETA-L-001", "seller.rin", "registration number must be exactly 9 digits")
    if not s.trade_name.strip():
        add("ETA-L-002", "seller.companyTradeName", "trade name is required")
    if not s.branch_code.strip():
        add("ETA-L-003", "seller.branchCode", "branch code is required (portal branch id)")
    if not s.device_serial.strip():
        add("ETA-L-004", "seller.deviceSerialNumber", "POS serial number is required")
    if not (_digits(s.activity_code) and len(s.activity_code) == 4):
        add("ETA-L-005", "seller.activityCode", "activity code must be a 4-digit code")
    a = s.branch_address
    for field_name, value in (
        ("governate", a.governate),
        ("regionCity", a.region_city),
        ("street", a.street),
        ("buildingNumber", a.building_number),
    ):
        if not value.strip():
            add("ETA-L-006", f"seller.branchAddress.{field_name}", "address field is required")
    if a.country != "EG":
        add("ETA-L-007", "seller.branchAddress.country", "country must be EG for local issuers")

    # ---- header ----------------------------------------------------------------------
    if receipt.issued_at.tzinfo is None:
        add("ETA-L-010", "header.dateTimeIssued", "issue time must be timezone-aware")
    elif receipt.issued_at.astimezone(UTC) > now + _CLOCK_SKEW:
        add("ETA-L-011", "header.dateTimeIssued", "issue time cannot be in the future")
    if not receipt.receipt_number.strip() or len(receipt.receipt_number) > 50:
        add("ETA-L-012", "header.receiptNumber", "receipt number is required (max 50 chars)")
    if receipt.currency != "EGP" and receipt.exchange_rate <= 0:
        add("ETA-L-013", "header.exchangeRate", "exchange rate is required for a foreign currency")
    if receipt.previous_uuid and not _is_hex64(receipt.previous_uuid):
        add("ETA-L-014", "header.previousUUID", "previousUUID must be 64 hex characters or empty")

    # ---- references ------------------------------------------------------------------
    if receipt.receipt_type is ReceiptType.RETURN:
        if not _is_hex64(receipt.reference_uuid):
            add("ETA-L-020", "header.referenceUUID", "a return must reference the sale receipt")
    elif receipt.reference_uuid:
        add("ETA-L-021", "header.referenceUUID", "only a return receipt carries referenceUUID")
    if receipt.reference_old_uuid and not _is_hex64(receipt.reference_old_uuid):
        add("ETA-L-022", "header.referenceOldUUID", "referenceOldUUID must be 64 hex characters")
    if receipt.reference_old_uuid and receipt.reference_old_uuid == receipt.previous_uuid:
        add("ETA-L-023", "header.referenceOldUUID", "cannot equal previousUUID")
    if receipt.receipt_type is ReceiptType.RETURN_WITHOUT_REFERENCE:
        if receipt.return_reason is None:
            add("ETA-L-024", "header.documentUseReason", "reason required for a return w/o ref")
        if receipt.sales_issued_at is None:
            add("ETA-L-025", "header.salesIssuedDateTime", "original sale date is required")

    # ---- buyer -----------------------------------------------------------------------
    if b.type is BuyerType.BUSINESS:
        if not (_digits(b.id) and len(b.id) == 9):
            add("ETA-L-030", "buyer.id", "a business buyer needs a 9-digit registration number")
        if not b.name.strip():
            add("ETA-L-031", "buyer.name", "a business buyer needs a name")
        if b.id and b.id == s.rin:
            add("ETA-L-032", "buyer.id", "buyer and seller cannot be the same")
    if b.type is BuyerType.PERSON and b.id and not (_digits(b.id) and len(b.id) == 14):
        add("ETA-L-033", "buyer.id", "a person's national id must be 14 digits")

    # ---- lines -----------------------------------------------------------------------
    if not receipt.lines:
        add("ETA-L-040", "itemData", "at least one line is required")
    for i, line in enumerate(receipt.lines):
        p = f"itemData[{i}]"
        if line.item_type not in ITEM_TYPES:
            add("ETA-L-041", f"{p}.itemType", "itemType must be EGS or GS1")
        if not line.item_code.strip():
            add("ETA-L-042", f"{p}.itemCode", "registered item code is required")
        if not line.internal_code.strip():
            add("ETA-L-043", f"{p}.internalCode", "internal code is required")
        if not line.description.strip():
            add("ETA-L-044", f"{p}.description", "description is required")
        if line.quantity <= 0:
            add("ETA-L-045", f"{p}.quantity", "quantity must be greater than zero")
        if line.unit_price < 0:
            add("ETA-L-046", f"{p}.unitPrice", "unit price cannot be negative")
        if line.tax.tax_type != "T1":
            add("ETA-L-047", f"{p}.taxableItems", "only VAT (T1) is supported by this issuer")
        if not (Decimal(0) <= line.tax.rate <= Decimal(100)):
            add("ETA-L-048", f"{p}.taxableItems.rate", "rate must be between 0 and 100")
        for d in (*line.commercial_discounts, *line.item_discounts):
            if d.amount < 0 or (d.rate is not None and d.rate < 0):
                add("ETA-L-049", f"{p}.discount", "a discount cannot be negative")

    if issues and not receipt.lines:
        return issues

    # ---- arithmetic (only when the inputs are sane enough to compute) ----------------
    if not any(i.code in {"ETA-L-045", "ETA-L-046", "ETA-L-048", "ETA-L-049"} for i in issues):
        amounts = [compute_line(line) for line in receipt.lines]
        totals = compute_totals(amounts, receipt.extra_receipt_discounts)
        for i, amt in enumerate(amounts):
            if amt.net_sale < 0:
                add("ETA-L-050", f"itemData[{i}].netSale", "discounts exceed the line value")
            if amt.total < 0:
                add("ETA-L-051", f"itemData[{i}].total", "line total is negative")
        if totals.total_commercial_discount > totals.total_sales:
            add("ETA-L-052", "totalCommercialDiscount", "exceeds totalSales")
        if totals.total_amount < 0:
            add("ETA-L-053", "totalAmount", "receipt total is negative")
        if (
            b.type is BuyerType.PERSON
            and totals.total_amount >= NATIONAL_ID_THRESHOLD_EGP
            and not (_digits(b.id) and len(b.id) == 14)
        ):
            add(
                "ETA-L-054",
                "buyer.id",
                f"national id is mandatory from {NATIONAL_ID_THRESHOLD_EGP} EGP",
            )
    return issues


def check_document_consistency(doc: dict) -> list[Issue]:
    """Re-check an already-built document's sums (defence in depth against builder bugs)."""
    issues: list[Issue] = []

    def num(x: object) -> Decimal:
        return Decimal(str(x))

    items = doc.get("itemData", [])
    if abs(num(doc["totalSales"]) - sum((num(i["totalSale"]) for i in items), Decimal(0))) > 0:
        issues.append(Issue("ETA-L-060", "totalSales", "does not equal the sum of line totalSale"))
    if abs(num(doc["netAmount"]) - sum((num(i["netSale"]) for i in items), Decimal(0))) > 0:
        issues.append(Issue("ETA-L-061", "netAmount", "does not equal the sum of line netSale"))
    expected = sum((num(i["total"]) for i in items), Decimal(0))
    for extra in doc.get("extraReceiptDiscountData", []):
        expected -= num(extra["amount"])
    expected += num(doc.get("adjustment", 0))
    if abs(num(doc["totalAmount"]) - expected) > _TOLERANCE:
        issues.append(Issue("ETA-L-062", "totalAmount", "does not equal the sum of line totals"))
    return issues


def _is_hex64(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)
