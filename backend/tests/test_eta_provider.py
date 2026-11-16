"""Unit tests for ETA (Egypt) eReceipt provider and JSON payload builder."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.einvoice.models import EInvoiceDevice
from app.modules.einvoice.ports import (
    EInvoiceContext,
    InvoiceLineItem,
    PartyInfo,
)
from app.modules.einvoice.providers.eta.provider import EtaEInvoiceProvider
from app.modules.einvoice.providers.eta.receipt import build_eta_ereceipt_json


def _sample_egypt_context(
    invoice_number: str = "REC-EG-0001",
    document_type: str = "sale_receipt",
    original_reference: str | None = None,
    original_uuid: str | None = None,
) -> EInvoiceContext:
    return EInvoiceContext(
        tenant_id=uuid.uuid4(),
        country_code="EG",
        document_type=document_type,
        invoice_number=invoice_number,
        issued_at=datetime(2026, 11, 17, 11, 0, 0, tzinfo=UTC),
        seller=PartyInfo(
            name="شركة الأهرام للتجارة والتوزيع",
            tax_id="100200300",  # 9-digit RIN
            city="Cairo",
            country_code="EG",
        ),
        currency="EGP",
        lines=[
            InvoiceLineItem(
                item_name="قميص قطن مصري فاخر",
                quantity=Decimal("3"),
                unit_price=Decimal("200.00"),
                subtotal=Decimal("600.00"),
                tax_rate=Decimal("0.1400"),
                tax_amount=Decimal("84.00"),
                total=Decimal("684.00"),
                sku="SHIRT-COTTON-01",
            )
        ],
        subtotal=Decimal("600.00"),
        tax_total=Decimal("84.00"),
        grand_total=Decimal("684.00"),
        original_reference=original_reference,
        original_uuid=original_uuid,
    )


def test_eta_ereceipt_sale_payload():
    context = _sample_egypt_context(document_type="sale_receipt")
    json_str = build_eta_ereceipt_json(context, device_serial="POS-CAIRO-01")
    data = json.loads(json_str)

    assert data["documentType"]["receiptType"] == "S"
    assert data["documentType"]["typeVersion"] == "1.2"
    assert data["seller"]["rin"] == "100200300"
    assert data["seller"]["deviceSerialNumber"] == "POS-CAIRO-01"
    assert data["totalAmount"] == 684.00
    assert data["taxTotals"][0]["taxType"] == "T1"
    assert data["taxTotals"][0]["amount"] == 84.00


def test_eta_ereceipt_return_payload():
    # Return receipt linked to original receipt UUID
    orig_uuid = str(uuid.uuid4())
    context = _sample_egypt_context(
        invoice_number="RET-EG-0001",
        document_type="return_receipt",
        original_reference="REC-EG-0001",
        original_uuid=orig_uuid,
    )
    json_str = build_eta_ereceipt_json(context)
    data = json.loads(json_str)

    assert data["documentType"]["receiptType"] == "R"
    # Mandatory reference to the original sale receipt being returned
    assert data["header"]["referenceOldUUID"] == orig_uuid


@pytest.mark.asyncio
async def test_eta_provider_lifecycle():
    provider = EtaEInvoiceProvider()
    context = _sample_egypt_context()

    # 1. Generate
    payload = await provider.generate_document(context)
    assert payload.content_type == "application/json"
    assert "100200300" in payload.raw_content

    # 2. Sign
    device = EInvoiceDevice(
        tenant_id=context.tenant_id,
        device_name="Cairo Mall Register",
        device_serial="POS-EGY-01",
        country_code="EG",
        provider_type="eta",
        icv_counter=0,
        last_pih=None,
    )
    signed = await provider.sign_document(context, payload, device)
    assert signed.icv == 1
    assert "https://invoicing.eta.gov.eg/receipts/search" in signed.qr_code

    # 3. Submit
    submission = await provider.submit(signed, device)
    assert submission.success is True
    assert submission.status == "reported"
    assert submission.authority_uuid is not None
