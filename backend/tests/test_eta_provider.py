"""ETA provider: the shared EInvoiceProvider contract driven end to end against the mock authority.

Replaces the old tests, which asserted the behaviour the authority rejects (receiptType "S"/"R",
``referenceOldUUID`` on returns, a random uuid4, ``status == "reported"`` with no network call).
No database and no network: the device is an in-memory ORM object and the authority is
``MockAuthority`` behind ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.applications.apparel.modules.einvoice.models import EInvoiceDevice
from app.applications.apparel.modules.einvoice.ports import EInvoiceContext, InvoiceLineItem, PartyInfo
from app.applications.apparel.modules.einvoice.providers.eta.mock_authority import MockAuthority
from app.applications.apparel.modules.einvoice.providers.eta.notifications import stored_status
from app.applications.apparel.modules.einvoice.providers.eta.provider import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    EtaEInvoiceProvider,
    EtaValidationError,
)
from app.applications.apparel.modules.einvoice.providers.eta.uuid_ import is_valid_uuid_shape

ISSUED = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
NOW = datetime(
    2026, 11, 20, 12, 0, tzinfo=UTC
)  # fixed 'now' so tests never depend on the wall clock
PROFILE = {
    "environment": "preprod",
    "branch_code": "1",
    "activity_code": "4771",
    "branch_address": {
        "governate": "cairo",
        "region_city": "city center",
        "street": "16 street",
        "building_number": "14",
    },
}
CREDS = {
    "client_id": "mock-client",
    "client_secret": "mock-secret",
    "preshared_key": "mock-psk",
}


def _device(*, configured: bool = True, last_pih: str | None = None) -> EInvoiceDevice:
    return EInvoiceDevice(
        tenant_id=uuid.uuid4(),
        device_name="Cairo POS",
        device_serial="POS-MOCK-1",
        country_code="EG",
        provider_type="eta",
        icv_counter=0,
        last_pih=last_pih,
        metadata_info={"eta": PROFILE},
        credentials={"eta": CREDS} if configured else {},
    )


def _context(device: EInvoiceDevice, **over) -> EInvoiceContext:
    base = dict(
        tenant_id=device.tenant_id,
        country_code="EG",
        document_type="sale_receipt",
        invoice_number="R-0001",
        issued_at=ISSUED,
        seller=PartyInfo(name="متجر الملابس", tax_id="674859545", country_code="EG"),
        currency="EGP",
        lines=[
            InvoiceLineItem(
                item_name="قميص قطن",
                quantity=Decimal("2"),
                unit_price=Decimal("100"),
                tax_rate=Decimal("0.14"),
                sku="SKU1",
                item_code_type="EGS",
                item_code="EG-674859545-1",
                vat_subtype="V009",
            )
        ],
        subtotal=Decimal("200"),
        tax_total=Decimal("28"),
        grand_total=Decimal("228"),
        extras={"payment_tender": "cash", "_device": device},
    )
    base.update(over)
    return EInvoiceContext(**base)


async def _issue(provider: EtaEInvoiceProvider, device: EInvoiceDevice, ctx: EInvoiceContext):
    payload = await provider.generate_document(ctx)
    signed = await provider.sign_document(ctx, payload, device)
    device.icv_counter, device.last_pih = signed.icv, signed.invoice_hash  # what the service does
    return payload, signed


def _provider(mock: MockAuthority) -> EtaEInvoiceProvider:
    return EtaEInvoiceProvider(httpx.AsyncClient(transport=mock.transport()), clock=lambda: NOW)


@pytest.mark.asyncio
async def test_sale_receipt_is_what_the_authority_documents():
    device = _device()
    payload, signed = await _issue(EtaEInvoiceProvider(clock=lambda: NOW), device, _context(device))
    doc = json.loads(payload.raw_content)
    assert doc["documentType"] == {"receiptType": "SR", "typeVersion": "1.2"}
    assert is_valid_uuid_shape(doc["header"]["uuid"])
    assert signed.invoice_hash == doc["header"]["uuid"]
    assert doc["seller"]["activityCode"] == "4771"
    assert doc["totalAmount"] == 228.0
    assert "/share/2026-11-20T09:00Z#Total:228.000,IssuerRIN:674859545" in signed.qr_code


@pytest.mark.asyncio
async def test_return_references_the_sale_via_reference_uuid():
    device = _device()
    prov = EtaEInvoiceProvider(clock=lambda: NOW)
    sale_payload, _ = await _issue(prov, device, _context(device))
    sale_uuid = json.loads(sale_payload.raw_content)["header"]["uuid"]
    ret_ctx = _context(
        device,
        document_type="return_receipt",
        invoice_number="R-0002",
        original_uuid=sale_uuid,
    )
    payload, _ = await _issue(prov, device, ret_ctx)
    doc = json.loads(payload.raw_content)
    assert doc["documentType"]["receiptType"] == "RR"
    assert doc["header"]["referenceUUID"] == sale_uuid
    assert doc["header"]["referenceOldUUID"] == ""
    assert doc["header"]["previousUUID"] == sale_uuid  # chained to the previous receipt


@pytest.mark.asyncio
async def test_chain_follows_the_previous_receipt_uuid_not_a_digest():
    device = _device()
    prov = EtaEInvoiceProvider(clock=lambda: NOW)
    first, _ = await _issue(prov, device, _context(device))
    second, _ = await _issue(prov, device, _context(device, invoice_number="R-0002"))
    f, s = json.loads(first.raw_content), json.loads(second.raw_content)
    assert f["header"]["previousUUID"] == ""  # first receipt of this POS
    assert s["header"]["previousUUID"] == f["header"]["uuid"]


@pytest.mark.asyncio
async def test_missing_egypt_profile_is_refused_not_defaulted():
    device = _device()
    device.metadata_info = {}
    with pytest.raises(EtaValidationError) as e:
        await EtaEInvoiceProvider(clock=lambda: NOW).generate_document(_context(device))
    codes = {i.code for i in e.value.issues}
    assert {"ETA-L-003", "ETA-L-005", "ETA-L-006"} <= codes  # branch, activity, address


@pytest.mark.asyncio
async def test_unregistered_item_code_is_refused():
    device = _device()
    line = InvoiceLineItem(
        item_name="x", quantity=Decimal("1"), unit_price=Decimal("10"), tax_rate=Decimal("0.14")
    )
    with pytest.raises(EtaValidationError) as e:
        await EtaEInvoiceProvider(clock=lambda: NOW).generate_document(
            _context(device, lines=[line])
        )
    assert {"ETA-L-041", "ETA-L-042"} <= {i.code for i in e.value.issues}


@pytest.mark.asyncio
async def test_unconfigured_device_stores_pending_and_claims_nothing():
    device = _device(configured=False)
    prov = EtaEInvoiceProvider(clock=lambda: NOW)
    _, signed = await _issue(prov, device, _context(device))
    result = await prov.submit(signed, device)
    assert result.success is False
    assert result.status == stored_status(STATUS_PENDING)
    assert result.warnings  # says why


@pytest.mark.asyncio
async def test_submit_to_authority_accepts_a_valid_chain():
    mock, device = MockAuthority(), _device()
    prov = _provider(mock)
    _, s1 = await _issue(prov, device, _context(device))
    r1 = await prov.submit(s1, device)
    assert (r1.success, r1.status) == (True, STATUS_SUBMITTED)
    _, s2 = await _issue(prov, device, _context(device, invoice_number="R-0002"))
    r2 = await prov.submit(s2, device)
    assert (r2.success, r2.status) == (True, STATUS_SUBMITTED)
    assert mock.last_uuid_by_pos["POS-MOCK-1"] == device.last_pih


@pytest.mark.asyncio
async def test_submit_sends_the_stored_bytes_unchanged():
    """The authority hashes what it receives; it must be exactly what we stored and printed."""
    seen: list[bytes] = []
    mock = MockAuthority()

    def spy(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/receiptsubmissions":
            seen.append(request.content)
        return mock.handler(request)

    device, prov = (
        _device(),
        EtaEInvoiceProvider(
            httpx.AsyncClient(transport=httpx.MockTransport(spy)), clock=lambda: NOW
        ),
    )
    payload, signed = await _issue(prov, device, _context(device))
    await prov.submit(signed, device)
    assert seen == [('{"receipts":[' + payload.raw_content + "]}").encode("utf-8")]


@pytest.mark.asyncio
async def test_authority_rejection_is_reported_as_rejected_with_reasons():
    mock = MockAuthority(rin="999999999")  # authority believes we are another taxpayer
    device, prov = _device(), _provider(mock)
    _, signed = await _issue(prov, device, _context(device))
    result = await prov.submit(signed, device)
    assert (result.success, result.status) == (False, STATUS_REJECTED)
    assert any("CF301" in e for e in result.errors)


@pytest.mark.asyncio
async def test_bad_credentials_leave_the_receipt_retryable_not_rejected():
    mock = MockAuthority(preshared_key="other")
    device, prov = _device(), _provider(mock)
    _, signed = await _issue(prov, device, _context(device))
    result = await prov.submit(signed, device)
    assert (result.success, result.status) == (False, STATUS_FAILED)


@pytest.mark.asyncio
async def test_check_status_never_invents_valid():
    result = await EtaEInvoiceProvider(clock=lambda: NOW).check_status("a" * 64, _device())
    assert result.success is False
    assert result.status == stored_status(STATUS_PENDING)
