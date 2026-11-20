"""End-to-end integration tests for POS sales and returns with ZATCA and ETA fiscal compliance."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.einvoice.models import EInvoiceDevice, EInvoiceDocument
from app.modules.einvoice.ports import (
    EInvoiceContext,
    InvoiceLineItem,
    PartyInfo,
)
from app.modules.einvoice.providers.zatca.tlv import decode_zatca_tlv
from app.modules.einvoice.service import EInvoiceService


@pytest.mark.asyncio
async def test_zatca_pos_sale_and_return_lifecycle():
    """Simulates a Saudi POS sale followed by customer return, verifying UBL XML and hash chain."""
    mock_session = AsyncMock()
    tenant_id = uuid.uuid4()
    receipt_sale_id = uuid.uuid4()
    receipt_return_id = uuid.uuid4()

    # 1. Device initialized for Saudi POS till
    device = EInvoiceDevice(
        tenant_id=tenant_id,
        device_name="Jeddah Branch POS 1",
        device_serial="POS-JED-01",
        country_code="SA",
        provider_type="zatca",
        icv_counter=0,
        last_pih=None,
    )

    persisted_docs: dict[str, EInvoiceDocument] = {}

    def mock_execute(stmt):
        res = MagicMock()
        # Intercept device lookup with for update
        if "einvoice_devices" in str(stmt):
            res.scalar_one_or_none.return_value = device
        elif "einvoice_documents" in str(stmt):
            # Duplicate check
            res.scalar_one_or_none.return_value = None
        return res

    mock_session.execute = AsyncMock(side_effect=mock_execute)
    mock_session.add = MagicMock(
        side_effect=lambda doc: persisted_docs.update({doc.invoice_number: doc})
    )

    # 2. Issue POS Sale Receipt
    sale_ctx = EInvoiceContext(
        tenant_id=tenant_id,
        country_code="SA",
        document_type="simplified",
        invoice_number="POS-20261117-0001",
        issued_at=datetime.now(UTC),
        seller=PartyInfo(
            name="شركة المتاجر العصرية",
            tax_id="300999888700003",
            city="Jeddah",
            country_code="SA",
        ),
        currency="SAR",
        lines=[
            InvoiceLineItem(
                item_name="عطر شرقي فاخر 100 مل",
                quantity=Decimal("1"),
                unit_price=Decimal("400.00"),
                subtotal=Decimal("400.00"),
                tax_rate=Decimal("0.1500"),
                tax_amount=Decimal("60.00"),
                total=Decimal("460.00"),
            )
        ],
        subtotal=Decimal("400.00"),
        tax_total=Decimal("60.00"),
        grand_total=Decimal("460.00"),
    )

    doc_sale = await EInvoiceService.issue_einvoice(
        mock_session,
        tenant_id,
        sale_ctx,
        receipt_id=receipt_sale_id,
    )

    assert doc_sale.status == "reported"
    assert doc_sale.icv == 1
    assert "0200000" in doc_sale.raw_payload
    assert doc_sale.qr_code is not None

    # Verify ZATCA TLV QR code contains correct tags
    tlv_data = decode_zatca_tlv(doc_sale.qr_code)
    assert tlv_data[1].decode("utf-8") == "شركة المتاجر العصرية"
    assert tlv_data[2].decode("utf-8") == "300999888700003"
    assert tlv_data[4].decode("utf-8") == "460.00"

    # Device counter and hash chain updated
    assert device.icv_counter == 1
    assert device.last_pih == doc_sale.invoice_hash

    # 3. Issue POS Return (Credit Note)
    return_ctx = EInvoiceContext(
        tenant_id=tenant_id,
        country_code="SA",
        document_type="credit_note",
        invoice_number="RET-20261117-0001",
        issued_at=datetime.now(UTC),
        seller=PartyInfo(
            name="شركة المتاجر العصرية",
            tax_id="300999888700003",
            city="Jeddah",
            country_code="SA",
        ),
        currency="SAR",
        lines=[
            InvoiceLineItem(
                item_name="عطر شرقي فاخر 100 مل (مرتجع)",
                quantity=Decimal("1"),
                unit_price=Decimal("400.00"),
                subtotal=Decimal("400.00"),
                tax_rate=Decimal("0.1500"),
                tax_amount=Decimal("60.00"),
                total=Decimal("460.00"),
            )
        ],
        subtotal=Decimal("400.00"),
        tax_total=Decimal("60.00"),
        grand_total=Decimal("460.00"),
        original_reference="POS-20261117-0001",
        original_uuid=doc_sale.authority_uuid,
        return_reason="Customer return at till",
    )

    doc_return = await EInvoiceService.issue_einvoice(
        mock_session,
        tenant_id,
        return_ctx,
        receipt_id=receipt_return_id,
    )

    # 4. Assert Return is properly chained and compliant
    assert doc_return.status == "reported"
    assert doc_return.icv == 2  # Monotonic counter advanced
    assert doc_return.pih == doc_sale.invoice_hash  # Hash chain linked!
    assert "381" in doc_return.raw_payload  # Credit note type code
    assert "<cac:BillingReference>" in doc_return.raw_payload
    assert "POS-20261117-0001" in doc_return.raw_payload


@pytest.mark.asyncio
async def test_eta_pos_sale_and_return_lifecycle():
    """Simulates an Egyptian POS sale and subsequent return receipt with ETA eReceipt compliance."""
    mock_session = AsyncMock()
    tenant_id = uuid.uuid4()

    device = EInvoiceDevice(
        tenant_id=tenant_id,
        device_name="Alexandria POS 1",
        device_serial="POS-ALX-01",
        country_code="EG",
        provider_type="eta",
        icv_counter=0,
        last_pih=None,
        metadata_info={
            "eta": {
                "environment": "preprod",
                "branch_code": "1",
                "activity_code": "4771",
                "branch_address": {
                    "governate": "alexandria",
                    "region_city": "city center",
                    "street": "1 corniche",
                    "building_number": "1",
                },
            }
        },
    )

    def mock_execute(stmt):
        res = MagicMock()
        if "einvoice_devices" in str(stmt):
            res.scalar_one_or_none.return_value = device
        elif "einvoice_documents" in str(stmt):
            res.scalar_one_or_none.return_value = None
        return res

    mock_session.execute = AsyncMock(side_effect=mock_execute)
    mock_session.add = MagicMock()

    # 1. POS Sale
    sale_ctx = EInvoiceContext(
        tenant_id=tenant_id,
        country_code="EG",
        document_type="sale_receipt",
        invoice_number="REC-EGY-001",
        issued_at=datetime.now(UTC),
        seller=PartyInfo(
            name="مكتبة الإسكندرية التجارية",
            tax_id="200300400",
            city="Alexandria",
            country_code="EG",
        ),
        currency="EGP",
        lines=[
            InvoiceLineItem(
                item_name="أدوات مكتبية",
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                subtotal=Decimal("100.00"),
                tax_rate=Decimal("0.1400"),
                tax_amount=Decimal("14.00"),
                total=Decimal("114.00"),
                sku="STAT-1",
                item_code_type="EGS",
                item_code="EG-200300400-1",
                vat_subtype="V009",
            )
        ],
        subtotal=Decimal("100.00"),
        tax_total=Decimal("14.00"),
        grand_total=Decimal("114.00"),
        extras={"payment_tender": "cash"},
    )

    doc_sale = await EInvoiceService.issue_einvoice(mock_session, tenant_id, sale_ctx)
    sale_data = json.loads(doc_sale.raw_payload)
    assert sale_data["documentType"]["receiptType"] == "SR"
    assert "/receipts/search/" in doc_sale.qr_code and "IssuerRIN:200300400" in doc_sale.qr_code
    # No ETA credentials on this device: stored for later, never claimed as reported.
    assert doc_sale.status == "pending"
    assert doc_sale.authority_uuid is None

    # 2. POS Return Receipt
    return_ctx = EInvoiceContext(
        tenant_id=tenant_id,
        country_code="EG",
        document_type="return_receipt",
        invoice_number="RET-EGY-001",
        issued_at=datetime.now(UTC),
        seller=PartyInfo(
            name="مكتبة الإسكندرية التجارية",
            tax_id="200300400",
            city="Alexandria",
            country_code="EG",
        ),
        currency="EGP",
        lines=[
            InvoiceLineItem(
                item_name="أدوات مكتبية (مرتجع)",
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                subtotal=Decimal("100.00"),
                tax_rate=Decimal("0.1400"),
                tax_amount=Decimal("14.00"),
                total=Decimal("114.00"),
                sku="STAT-1",
                item_code_type="EGS",
                item_code="EG-200300400-1",
                vat_subtype="V009",
            )
        ],
        subtotal=Decimal("100.00"),
        tax_total=Decimal("14.00"),
        grand_total=Decimal("114.00"),
        original_reference="REC-EGY-001",
        original_uuid=sale_data["header"]["uuid"],
        extras={"payment_tender": "cash"},
    )

    doc_return = await EInvoiceService.issue_einvoice(mock_session, tenant_id, return_ctx)
    return_data = json.loads(doc_return.raw_payload)
    assert return_data["documentType"]["receiptType"] == "RR"
    assert return_data["header"]["referenceUUID"] == sale_data["header"]["uuid"]
    assert return_data["header"]["previousUUID"] == sale_data["header"]["uuid"]
