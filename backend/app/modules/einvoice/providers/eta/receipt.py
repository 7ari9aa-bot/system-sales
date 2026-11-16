"""Egyptian Tax Authority (ETA) eReceipt payload builder (v1.2).

Constructs compliant JSON payloads for:
- Retail POS Sales (receiptType: 'S')
- Return Receipts (receiptType: 'R') with referenceOldUUID link
"""

from __future__ import annotations

import json
import uuid

from app.modules.einvoice.ports import EInvoiceContext


def build_eta_ereceipt_json(
    context: EInvoiceContext,
    *,
    device_serial: str = "POS-01",
    previous_uuid: str | None = None,
    document_uuid: str | None = None,
) -> str:
    """Build canonical ETA eReceipt JSON payload string."""
    doc_uuid = document_uuid or str(uuid.uuid4())
    issued_iso = context.issued_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    is_return = context.document_type in ("return_receipt", "credit_note")
    receipt_type = "R" if is_return else "S"

    item_data = []
    for idx, line in enumerate(context.lines, start=1):
        line_subtotal = float(line.subtotal)
        line_tax = float(line.tax_amount)
        line_total = float(line.total)
        item_data.append(
            {
                "internalCode": line.sku or str(idx),
                "description": line.item_name,
                "itemType": "EGS",
                "itemCode": f"EG-{context.seller.tax_id}-{line.sku or idx}",
                "unitType": "EA",
                "quantity": float(line.quantity),
                "unitPrice": float(line.unit_price),
                "netSale": round(line_subtotal, 2),
                "totalSale": round(line_total, 2),
                "commercialDiscountData": [],
                "itemDiscountData": [],
                "taxableItems": [
                    {
                        "taxType": "T1",  # Value Added Tax
                        "amount": round(line_tax, 2),
                        "subType": "V009",  # General taxable goods
                        "rate": float(line.tax_rate * 100),
                    }
                ],
            }
        )

    header = {
        "dateTimeIssued": issued_iso,
        "receiptNumber": context.invoice_number,
        "uuid": doc_uuid,
        "previousUUID": previous_uuid or "",
    }
    if is_return and context.original_reference:
        header["referenceOldUUID"] = context.original_uuid or context.original_reference

    payload = {
        "header": header,
        "documentType": {
            "receiptType": receipt_type,
            "typeVersion": "1.2",
        },
        "seller": {
            "rin": context.seller.tax_id,
            "companyTradeName": context.seller.name,
            "branchCode": "0",
            "deviceSerialNumber": device_serial,
            "activityCode": "4719",
        },
        "buyer": {
            "type": "P" if not (context.buyer and context.buyer.tax_id) else "B",
            "id": context.buyer.tax_id if context.buyer else "",
            "name": context.buyer.name if context.buyer else "Walk-in Customer",
        },
        "itemData": item_data,
        "totalSales": round(float(context.subtotal), 2),
        "totalCommercialDiscount": round(float(context.discount_total), 2),
        "totalItemsDiscount": 0.0,
        "netAmount": round(float(context.subtotal), 2),
        "taxTotals": [
            {
                "taxType": "T1",
                "amount": round(float(context.tax_total), 2),
            }
        ],
        "totalAmount": round(float(context.grand_total), 2),
    }

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
