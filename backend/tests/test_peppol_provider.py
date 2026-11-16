"""Unit tests for UAE Peppol PINT AE provider and XML builder."""

from __future__ import annotations

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
from app.modules.einvoice.providers.peppol_ae.pint import (
    CUSTOMIZATION_ID,
    PROFILE_ID,
    build_pint_ae_xml,
)
from app.modules.einvoice.providers.peppol_ae.provider import PeppolAeEInvoiceProvider


def _sample_uae_context() -> EInvoiceContext:
    return EInvoiceContext(
        tenant_id=uuid.uuid4(),
        country_code="AE",
        document_type="tax_invoice",
        invoice_number="INV-DXB-0001",
        issued_at=datetime(2026, 11, 17, 12, 0, 0, tzinfo=UTC),
        seller=PartyInfo(
            name="Gulf Digital Retail LLC",
            tax_id="100345678900003",
            city="Dubai",
            country_code="AE",
        ),
        currency="AED",
        lines=[
            InvoiceLineItem(
                item_name="Smart Home Sensor Hub",
                quantity=Decimal("1"),
                unit_price=Decimal("400.00"),
                subtotal=Decimal("400.00"),
                tax_rate=Decimal("0.0500"),
                tax_amount=Decimal("20.00"),
                total=Decimal("420.00"),
            )
        ],
        subtotal=Decimal("400.00"),
        tax_total=Decimal("20.00"),
        grand_total=Decimal("420.00"),
    )


def test_pint_ae_xml_structure():
    context = _sample_uae_context()
    xml_str = build_pint_ae_xml(context)

    assert f"<cbc:CustomizationID>{CUSTOMIZATION_ID}</cbc:CustomizationID>" in xml_str
    assert f"<cbc:ProfileID>{PROFILE_ID}</cbc:ProfileID>" in xml_str
    assert "<cbc:ID>INV-DXB-0001</cbc:ID>" in xml_str
    assert "100345678900003" in xml_str  # TRN
    assert "5.00" in xml_str  # 5% UAE VAT
    assert "420.00" in xml_str  # Grand total


@pytest.mark.asyncio
async def test_peppol_provider_lifecycle():
    provider = PeppolAeEInvoiceProvider()
    context = _sample_uae_context()

    # 1. Generate
    payload = await provider.generate_document(context)
    assert payload.content_type == "application/xml"
    assert "Gulf Digital Retail LLC" in payload.raw_content

    # 2. Sign
    device = EInvoiceDevice(
        tenant_id=context.tenant_id,
        device_name="Dubai Branch POS",
        device_serial="POS-DXB-01",
        country_code="AE",
        provider_type="peppol_ae",
        icv_counter=0,
        last_pih=None,
    )
    signed = await provider.sign_document(context, payload, device)
    assert signed.icv == 1

    # 3. Submit
    submission = await provider.submit(signed, device)
    assert submission.success is True
    assert submission.status == "submitted"
    assert submission.authority_uuid is not None
