"""Build an ETA eReceipt (Retail v1.2) from typed input.

Pure and synchronous: no I/O, no clock, no randomness. The same input always yields the same
document and the same UUID, which is what makes it testable and what lets a resend after an
outage reproduce the exact receipt.

Money is kept as ``Decimal`` all the way and serialised as a JSON *number* with five decimals
(``Decimal`` -> ``_Num``), never as a binary float: ``0.1 + 0.2`` style drift would make the
authority's sum checks disagree with the printed receipt.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from app.modules.einvoice.providers.eta.calc import (
    LineAmounts,
    ReceiptTotals,
    compute_line,
    compute_totals,
    q5,
)
from app.modules.einvoice.providers.eta.codes import (
    RECEIPT_TYPE_VERSION,
    ReceiptType,
)
from app.modules.einvoice.providers.eta.models import (
    BranchAddress,
    BuyerProfile,
    DiscountSpec,
    EtaLine,
    EtaReceiptInput,
    SellerProfile,
)
from app.modules.einvoice.providers.eta.uuid_ import compute_receipt_uuid


def _iso_utc(moment: Any) -> str:
    return moment.astimezone(__import__("datetime").UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _discount(spec: DiscountSpec, amount: Decimal) -> dict[str, Any]:
    out: dict[str, Any] = {"amount": amount, "description": spec.description}
    if spec.rate is not None and spec.rate > 0:
        out["rate"] = spec.rate
    return out


def _address(addr: BranchAddress) -> dict[str, Any]:
    out: dict[str, Any] = {
        "country": addr.country,
        "governate": addr.governate,
        "regionCity": addr.region_city,
        "street": addr.street,
        "buildingNumber": addr.building_number,
    }
    for key, value in (
        ("postalCode", addr.postal_code),
        ("floor", addr.floor),
        ("room", addr.room),
        ("landmark", addr.landmark),
        ("additionalInformation", addr.additional_information),
    ):
        if value:
            out[key] = value
    return out


def _seller(seller: SellerProfile) -> dict[str, Any]:
    return {
        "rin": seller.rin,
        "companyTradeName": seller.trade_name,
        "branchCode": seller.branch_code,
        "branchAddress": _address(seller.branch_address),
        "deviceSerialNumber": seller.device_serial,
        "activityCode": seller.activity_code,
    }


def _buyer(buyer: BuyerProfile) -> dict[str, Any]:
    out: dict[str, Any] = {"type": buyer.type.value}
    # id/name are optional for a walk-in person; omit rather than send empty strings.
    for key, value in (
        ("id", buyer.id),
        ("name", buyer.name),
        ("mobileNumber", buyer.mobile_number),
        ("paymentNumber", buyer.payment_number),
    ):
        if value:
            out[key] = value
    return out


def _item(line: EtaLine, amounts: LineAmounts) -> dict[str, Any]:
    item: dict[str, Any] = {
        "internalCode": line.internal_code,
        "description": line.description,
        "itemType": line.item_type,
        "itemCode": line.item_code,
        "unitType": line.unit_type,
        "quantity": q5(line.quantity),
        "unitPrice": q5(line.unit_price),
        "netSale": amounts.net_sale,
        "totalSale": amounts.total_sale,
        "total": amounts.total,
    }
    if line.commercial_discounts:
        item["commercialDiscountData"] = [
            _discount(d, a)
            for d, a in zip(line.commercial_discounts, amounts.commercial, strict=True)
        ]
    if line.item_discounts:
        item["itemDiscountData"] = [
            _discount(d, a) for d, a in zip(line.item_discounts, amounts.item, strict=True)
        ]
    if line.value_difference:
        item["valueDifference"] = q5(line.value_difference)
    item["taxableItems"] = [
        {
            "taxType": line.tax.tax_type,
            "amount": amounts.vat,
            "subType": line.tax.sub_type,
            "rate": line.tax.rate,
        }
    ]
    return item


def build_receipt(receipt: EtaReceiptInput) -> dict[str, Any]:
    """Return the receipt dict (the element that goes into ``receipts[]``), UUID filled in."""
    amounts = [compute_line(line) for line in receipt.lines]
    totals = compute_totals(amounts, receipt.extra_receipt_discounts)

    header: dict[str, Any] = {
        "dateTimeIssued": _iso_utc(receipt.issued_at),
        "receiptNumber": receipt.receipt_number,
        "uuid": "",
        "previousUUID": receipt.previous_uuid,
    }
    # A return always names its sale. A return WITHOUT reference may name one too (optional, a
    # 64-character id), but an empty value is not a 64-character id: leave the field out instead.
    if receipt.receipt_type is ReceiptType.RETURN or (
        receipt.receipt_type is ReceiptType.RETURN_WITHOUT_REFERENCE and receipt.reference_uuid
    ):
        header["referenceUUID"] = receipt.reference_uuid
    header["referenceOldUUID"] = receipt.reference_old_uuid
    header["currency"] = receipt.currency
    header["exchangeRate"] = receipt.exchange_rate
    header["orderdeliveryMode"] = receipt.delivery_mode.value
    if receipt.receipt_type is ReceiptType.RETURN_WITHOUT_REFERENCE:
        if receipt.return_reason is not None:
            header["documentUseReason"] = receipt.return_reason.value
        if receipt.sales_issued_at is not None:
            header["salesIssuedDateTime"] = _iso_utc(receipt.sales_issued_at)

    doc: dict[str, Any] = {
        "header": header,
        "documentType": {
            "receiptType": receipt.receipt_type.value,
            "typeVersion": RECEIPT_TYPE_VERSION,
        },
        "seller": _seller(receipt.seller),
        "buyer": _buyer(receipt.buyer),
        "itemData": [_item(line, a) for line, a in zip(receipt.lines, amounts, strict=True)],
    }
    _attach_totals(doc, totals, receipt)
    doc["header"]["uuid"] = compute_receipt_uuid(_jsonable(doc))
    return doc


def _attach_totals(doc: dict[str, Any], totals: ReceiptTotals, receipt: EtaReceiptInput) -> None:
    doc["totalSales"] = totals.total_sales
    if totals.total_commercial_discount:
        doc["totalCommercialDiscount"] = totals.total_commercial_discount
    if totals.total_items_discount:
        doc["totalItemsDiscount"] = totals.total_items_discount
    if receipt.extra_receipt_discounts:
        doc["extraReceiptDiscountData"] = [
            _discount(d, a)
            for d, a in zip(receipt.extra_receipt_discounts, totals.extra_discounts, strict=True)
        ]
    doc["netAmount"] = totals.net_amount
    doc["feesAmount"] = Decimal("0")
    doc["totalAmount"] = totals.total_amount
    doc["taxTotals"] = [{"taxType": "T1", "amount": totals.vat_total}]
    doc["paymentMethod"] = receipt.payment_method.value
    doc["adjustment"] = Decimal("0")


def _jsonable(node: Any) -> Any:
    """Decimal -> fixed 5-place string so hashing is independent of float formatting."""
    if isinstance(node, dict):
        return {k: _jsonable(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_jsonable(v) for v in node]
    if isinstance(node, Decimal):
        return format(q5(node), "f")
    return node


def dumps(node: Any) -> str:
    """Serialise a receipt/batch to compact JSON.

    ``Decimal`` values are written as bare JSON numbers with exactly five decimals. The standard
    ``json`` module can only do that by going through ``float``, which reintroduces the binary
    drift this module exists to avoid, so the (small, closed) JSON grammar is written out here.
    """
    if isinstance(node, dict):
        body = ",".join(f"{json.dumps(k, ensure_ascii=False)}:{dumps(v)}" for k, v in node.items())
        return "{" + body + "}"
    if isinstance(node, list):
        return "[" + ",".join(dumps(v) for v in node) + "]"
    if isinstance(node, Decimal):
        return format(q5(node), "f")
    return json.dumps(node, ensure_ascii=False)
