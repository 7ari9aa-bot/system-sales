"""Unit tests for ZATCA Fatoora Phase 2 provider, UBL 2.1 XML builder, and TLV QR encoding."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.applications.apparel.modules.einvoice.models import EInvoiceDevice
from app.applications.apparel.modules.einvoice.ports import (
    EInvoiceContext,
    InvoiceLineItem,
    PartyInfo,
)
from app.applications.apparel.modules.einvoice.providers.sandbox import INITIAL_PIH_SEED
from app.applications.apparel.modules.einvoice.providers.zatca.provider import ZatcaEInvoiceProvider
from app.applications.apparel.modules.einvoice.providers.zatca.tlv import decode_zatca_tlv, encode_zatca_tlv
from app.applications.apparel.modules.einvoice.providers.zatca.ubl import build_zatca_ubl_xml


def _sample_saudi_context(
    invoice_number: str = "INV-SA-0001",
    document_type: str = "simplified",
    original_reference: str | None = None,
) -> EInvoiceContext:
    return EInvoiceContext(
        tenant_id=uuid.uuid4(),
        country_code="SA",
        document_type=document_type,
        invoice_number=invoice_number,
        issued_at=datetime(2026, 11, 17, 10, 30, 0, tzinfo=UTC),
        seller=PartyInfo(
            name="شركة المتجر السعودي للتجارة",
            tax_id="310123456700003",
            street="شارع التحلية",
            building_number="1234",
            city="Riyadh",
            postal_code="12331",
            country_code="SA",
            commercial_register="1010123456",
        ),
        buyer=PartyInfo(
            name="شركة الأفق للحلول",
            tax_id="310987654300003",
            city="Jeddah",
            country_code="SA",
        ),
        currency="SAR",
        lines=[
            InvoiceLineItem(
                item_name="شاشة عرض ذكية 4K",
                quantity=Decimal("1"),
                unit_price=Decimal("1000.00"),
                subtotal=Decimal("1000.00"),
                tax_rate=Decimal("0.1500"),
                tax_amount=Decimal("150.00"),
                total=Decimal("1150.00"),
            ),
            InvoiceLineItem(
                item_name="كابل توصيل HDMI",
                quantity=Decimal("2"),
                unit_price=Decimal("50.00"),
                subtotal=Decimal("100.00"),
                tax_rate=Decimal("0.1500"),
                tax_amount=Decimal("15.00"),
                total=Decimal("115.00"),
            ),
        ],
        subtotal=Decimal("1100.00"),
        tax_total=Decimal("165.00"),
        grand_total=Decimal("1265.00"),
        original_reference=original_reference,
    )


def test_zatca_tlv_encoding_and_decoding():
    tags = {
        1: "شركة المتجر السعودي للتجارة",
        2: "310123456700003",
        3: "2026-11-17T10:30:00",
        4: "1265.00",
        5: "165.00",
        6: "MEQCIDf123456hash==",
        7: "MEQCIDf123456sig==",
    }
    b64_encoded = encode_zatca_tlv(tags)
    assert len(b64_encoded) > 0

    decoded = decode_zatca_tlv(b64_encoded)
    assert decoded[1].decode("utf-8") == "شركة المتجر السعودي للتجارة"
    assert decoded[2].decode("utf-8") == "310123456700003"
    assert decoded[3].decode("utf-8") == "2026-11-17T10:30:00"
    assert decoded[4].decode("utf-8") == "1265.00"
    assert decoded[5].decode("utf-8") == "165.00"
    assert decoded[6].decode("utf-8") == "MEQCIDf123456hash=="
    assert decoded[7].decode("utf-8") == "MEQCIDf123456sig=="


def test_zatca_ubl_xml_simplified_invoice():
    context = _sample_saudi_context(document_type="simplified")
    xml_str = build_zatca_ubl_xml(context, icv=5, pih="sample_pih_base64")

    assert "<cbc:ProfileID>reporting:1.0</cbc:ProfileID>" in xml_str
    assert '<cbc:InvoiceTypeCode name="0200000">388</cbc:InvoiceTypeCode>' in xml_str
    assert "<cbc:ID>INV-SA-0001</cbc:ID>" in xml_str
    assert "<cbc:DocumentCurrencyCode>SAR</cbc:DocumentCurrencyCode>" in xml_str
    assert "310123456700003" in xml_str  # Seller VAT
    assert "1265.00" in xml_str  # Grand total
    assert "<cbc:UUID>5</cbc:UUID>" in xml_str  # ICV


def test_zatca_ubl_xml_credit_note_returns():
    # Credit note for POS return
    context = _sample_saudi_context(
        invoice_number="CN-SA-0001",
        document_type="credit_note",
        original_reference="INV-SA-0001",
    )
    xml_str = build_zatca_ubl_xml(context)

    # Type 381 is Credit Note
    assert "381" in xml_str
    # Must reference the original invoice
    assert "<cac:BillingReference>" in xml_str
    assert "<cbc:ID>INV-SA-0001</cbc:ID>" in xml_str


@pytest.mark.asyncio
async def test_zatca_provider_lifecycle():
    provider = ZatcaEInvoiceProvider()
    context = _sample_saudi_context()

    # 1. Generate document
    payload = await provider.generate_document(context)
    assert payload.content_type == "application/xml"
    assert len(payload.digest_hash) > 0
    assert "Invoice" in payload.raw_content

    # 2. Sign document
    device = EInvoiceDevice(
        tenant_id=context.tenant_id,
        device_name="Riyadh POS Register 1",
        device_serial="POS-RUH-01",
        country_code="SA",
        provider_type="zatca",
        icv_counter=0,
        last_pih=None,
    )
    signed = await provider.sign_document(context, payload, device)
    assert signed.icv == 1
    assert signed.pih == INITIAL_PIH_SEED
    assert len(signed.invoice_hash) > 0
    assert len(signed.signature) > 0
    assert len(signed.qr_code) > 0

    # Verify generated QR code contains valid TLV structure
    decoded_qr = decode_zatca_tlv(signed.qr_code)
    assert decoded_qr[1].decode("utf-8") == "شركة المتجر السعودي للتجارة"
    assert decoded_qr[2].decode("utf-8") == "310123456700003"

    # 3. Submit
    submission = await provider.submit(signed, device)
    assert submission.success is True
    assert submission.status == "reported"  # Simplified B2C reported to ZATCA
    assert submission.authority_uuid is not None
