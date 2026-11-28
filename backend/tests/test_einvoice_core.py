"""Unit tests for E-invoicing core engine, provider interface, and hash chaining."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.errors import ConflictError
from app.applications.apparel.modules.einvoice.models import EInvoiceDevice, EInvoiceDocument
from app.applications.apparel.modules.einvoice.ports import (
    EInvoiceContext,
    InvoiceLineItem,
    PartyInfo,
)
from app.applications.apparel.modules.einvoice.providers.sandbox import (
    INITIAL_PIH_SEED,
    SandboxEInvoiceProvider,
)
from app.applications.apparel.modules.einvoice.registry import get_einvoice_provider
from app.applications.apparel.modules.einvoice.service import EInvoiceService


def _sample_context(
    invoice_number: str = "INV-2026-0001",
    country_code: str = "SA",
) -> EInvoiceContext:
    return EInvoiceContext(
        tenant_id=uuid.uuid4(),
        country_code=country_code,
        document_type="simplified",
        invoice_number=invoice_number,
        issued_at=datetime.now(UTC),
        seller=PartyInfo(
            name="شركة تجارة العصر المحدودة",
            tax_id="300012345600003",
            city="Riyadh",
            country_code=country_code,
        ),
        currency="SAR",
        lines=[
            InvoiceLineItem(
                item_name="قميص أكسفورد أزرق",
                quantity=Decimal("2"),
                unit_price=Decimal("100.00"),
                subtotal=Decimal("200.00"),
                tax_rate=Decimal("0.1500"),
                tax_amount=Decimal("30.00"),
                total=Decimal("230.00"),
            )
        ],
        subtotal=Decimal("200.00"),
        tax_total=Decimal("30.00"),
        grand_total=Decimal("230.00"),
    )


@pytest.mark.asyncio
async def test_sandbox_provider_lifecycle():
    provider = SandboxEInvoiceProvider()
    context = _sample_context()

    # 1. Generate document
    payload = await provider.generate_document(context)
    assert payload.content_type == "application/json"
    assert len(payload.digest_hash) > 0
    assert "شركة تجارة العصر المحدودة" in payload.raw_content

    # 2. Sign document with mock device
    device = EInvoiceDevice(
        tenant_id=context.tenant_id,
        device_name="POS 1",
        device_serial="POS-01",
        country_code="SA",
        icv_counter=0,
        last_pih=None,
    )
    signed = await provider.sign_document(context, payload, device)
    assert signed.icv == 1
    assert signed.pih == INITIAL_PIH_SEED
    assert len(signed.invoice_hash) > 0
    assert len(signed.signature) > 0
    assert len(signed.qr_code) > 0

    # 3. Submit
    submission = await provider.submit(signed, device)
    assert submission.success is True
    assert submission.status == "cleared"
    assert submission.authority_uuid is not None


@pytest.mark.asyncio
async def test_hash_chain_and_monotonic_icv():
    provider = SandboxEInvoiceProvider()
    tenant_id = uuid.uuid4()
    device = EInvoiceDevice(
        tenant_id=tenant_id,
        device_name="POS 1",
        device_serial="POS-01",
        country_code="SA",
        icv_counter=0,
        last_pih=None,
    )

    # Document 1
    ctx1 = _sample_context(invoice_number="INV-001")
    p1 = await provider.generate_document(ctx1)
    s1 = await provider.sign_document(ctx1, p1, device)
    assert s1.icv == 1
    assert s1.pih == INITIAL_PIH_SEED

    # Advance device state
    device.icv_counter = s1.icv
    device.last_pih = s1.invoice_hash

    # Document 2
    ctx2 = _sample_context(invoice_number="INV-002")
    p2 = await provider.generate_document(ctx2)
    s2 = await provider.sign_document(ctx2, p2, device)
    assert s2.icv == 2
    assert s2.pih == s1.invoice_hash  # Hash chain linked!

    # Advance device state
    device.icv_counter = s2.icv
    device.last_pih = s2.invoice_hash

    # Document 3
    ctx3 = _sample_context(invoice_number="INV-003")
    p3 = await provider.generate_document(ctx3)
    s3 = await provider.sign_document(ctx3, p3, device)
    assert s3.icv == 3
    assert s3.pih == s2.invoice_hash  # Tamper-evident sequential linkage!


def test_provider_registry_resolution():
    sandbox = get_einvoice_provider("sandbox")
    assert isinstance(sandbox, SandboxEInvoiceProvider)
    assert sandbox.provider_type == "sandbox"

    # Default fallback
    fallback = get_einvoice_provider(country_code="XX")
    assert isinstance(fallback, SandboxEInvoiceProvider)


@pytest.mark.asyncio
async def test_einvoice_service_rejects_duplicate_invoice_number():
    mock_session = AsyncMock()
    tenant_id = uuid.uuid4()
    context = _sample_context(invoice_number="INV-DUP-01")

    # Mock device return
    mock_device = EInvoiceDevice(
        tenant_id=tenant_id,
        device_name="POS 1",
        device_serial="DEFAULT-POS-01",
        country_code="SA",
        icv_counter=5,
        last_pih="sample-hash",
    )

    # Mock duplicate check returning an existing document
    existing_doc = EInvoiceDocument(
        tenant_id=tenant_id,
        invoice_number="INV-DUP-01",
        country_code="SA",
        provider_type="sandbox",
        document_type="simplified",
        invoice_hash="abc",
        pih="def",
    )

    call_count = 0

    def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        res = MagicMock()
        if call_count == 1:
            # get_or_create_device select with for update
            res.scalar_one_or_none.return_value = mock_device
        else:
            # check duplicate select
            res.scalar_one_or_none.return_value = existing_doc
        return res

    mock_session.execute = AsyncMock(side_effect=mock_execute)

    with pytest.raises(ConflictError, match="has already been issued"):
        await EInvoiceService.issue_einvoice(mock_session, tenant_id, context)
