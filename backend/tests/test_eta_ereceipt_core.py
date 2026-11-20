"""ETA eReceipt core: arithmetic, builder, validator, QR, client, mock authority.

These tests pin the behaviour the authority *documents* (sdk.invoicing.eta.gov.eg). They run
without a database or network. They do NOT prove acceptance by the live service: see
``app/modules/einvoice/providers/eta/uuid_.py`` (UUID normalization is unverified) and
``docs`` for what still needs a PreProd account.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal as D

import httpx
import pytest

from app.modules.einvoice.providers.eta.builder import build_receipt, dumps
from app.modules.einvoice.providers.eta.calc import (
    compute_line,
    compute_totals,
    price_excluding_vat,
)
from app.modules.einvoice.providers.eta.client import (
    EtaAuthError,
    EtaClient,
    EtaCredentials,
    EtaEndpoints,
    EtaPermanentError,
    EtaTransientError,
)
from app.modules.einvoice.providers.eta.codes import (
    BuyerType,
    PaymentMethod,
    ReceiptType,
    payment_method_for_tender,
)
from app.modules.einvoice.providers.eta.mock_authority import MockAuthority
from app.modules.einvoice.providers.eta.models import (
    BranchAddress,
    BuyerProfile,
    DiscountSpec,
    EtaLine,
    EtaReceiptInput,
    ItemTax,
    SellerProfile,
)
from app.modules.einvoice.providers.eta.qr import build_qr_payload
from app.modules.einvoice.providers.eta.uuid_ import (
    compute_receipt_uuid,
    is_valid_uuid_shape,
)
from app.modules.einvoice.providers.eta.validator import (
    check_document_consistency,
    validate_receipt,
)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
ISSUED = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def _seller(**over) -> SellerProfile:
    base = dict(
        rin="674859545",
        trade_name="متجر الملابس",
        branch_code="1",
        branch_address=BranchAddress("cairo", "city center", "16 street", "14"),
        device_serial="POS-MOCK-1",
        activity_code="4771",
    )
    base.update(over)
    return SellerProfile(**base)


def _line(**over) -> EtaLine:
    base = dict(
        internal_code="SKU1",
        description="قميص قطن",
        item_type="EGS",
        item_code="EG-674859545-1",
        quantity=D("2"),
        unit_price=D("100"),
    )
    base.update(over)
    return EtaLine(**base)


def _receipt(**over) -> EtaReceiptInput:
    base = dict(
        receipt_number="R-0001",
        issued_at=ISSUED,
        seller=_seller(),
        buyer=BuyerProfile(),
        lines=(_line(),),
        payment_method=PaymentMethod.CASH,
    )
    base.update(over)
    return EtaReceiptInput(**base)


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


# ------------------------------------------------------------------ arithmetic ------------
def test_vat_matches_authority_published_example():
    """Numbers from the authority's own Postman 'Submit Receipt - Retail' sample."""
    line = _line(
        quantity=D("35"),
        unit_price=D("247.96"),
        commercial_discounts=(DiscountSpec(D("867.86"), rate=D("10")),),
        value_difference=D("20"),
    )
    a = compute_line(line)
    assert a.total_sale == D("8678.60000")
    assert a.net_sale == D("7810.74000")
    assert a.vat == D("1096.30360")  # (net + valueDifference) * 14%


def test_item_discount_is_taken_after_vat_and_percent_applies_to_net_sale():
    a = compute_line(_line(item_discounts=(DiscountSpec(D("0"), rate=D("10")),)))
    assert a.net_sale == D("200.00000")
    assert a.item == (D("20.00000"),)  # 10% of netSale, not of totalSale+VAT
    assert a.total == D("208.00000")  # 200 + 28 VAT - 20


def test_item_discount_percent_uses_net_sale_when_a_commercial_discount_exists():
    """netSale != totalSale here, so basing the % on the wrong one changes the answer."""
    a = compute_line(
        _line(
            commercial_discounts=(DiscountSpec(D("50")),),  # totalSale 200 -> netSale 150
            item_discounts=(DiscountSpec(D("0"), rate=D("10")),),
        )
    )
    assert a.net_sale == D("150.00000")
    assert a.item == (D("15.00000"),)  # 10% of 150 (not 20 = 10% of 200)


def test_rate_discount_overrides_stale_amount():
    a = compute_line(_line(commercial_discounts=(DiscountSpec(D("1"), rate=D("10")),)))
    assert a.commercial == (D("20.00000"),)


def test_totals_are_sums_of_lines():
    amts = [compute_line(_line()), compute_line(_line(quantity=D("1"), unit_price=D("50")))]
    t = compute_totals(amts)
    assert t.total_sales == D("250.00000")
    assert t.net_amount == D("250.00000")
    assert t.vat_total == D("35.00000")
    assert t.total_amount == D("285.00000")


def test_no_binary_float_drift():
    a = compute_line(_line(quantity=D("3"), unit_price=D("0.1")))
    assert a.total_sale == D("0.30000")  # 0.1*3 in float is 0.30000000000000004


def test_vat_inclusive_price_back_out():
    assert price_excluding_vat(D("114"), D("14")) == D("100.00000")
    assert price_excluding_vat(D("100"), D("0")) == D("100.00000")


# ------------------------------------------------------------------ builder ---------------
def test_sale_receipt_has_the_fields_the_old_builder_got_wrong():
    doc = build_receipt(_receipt())
    assert doc["documentType"] == {"receiptType": "SR", "typeVersion": "1.2"}
    assert doc["seller"]["branchCode"] == "1"
    assert doc["seller"]["activityCode"] == "4771"
    assert doc["seller"]["branchAddress"]["governate"] == "cairo"
    assert doc["paymentMethod"] == "C"
    assert doc["header"]["currency"] == "EGP"
    assert doc["header"]["orderdeliveryMode"] == "FC"
    assert "referenceUUID" not in doc["header"]
    assert is_valid_uuid_shape(doc["header"]["uuid"])  # not a random uuid4


def test_return_uses_reference_uuid_not_reference_old_uuid():
    sale = build_receipt(_receipt())
    ret = build_receipt(
        _receipt(
            receipt_type=ReceiptType.RETURN,
            receipt_number="R-0002",
            previous_uuid=sale["header"]["uuid"],
            reference_uuid=sale["header"]["uuid"],
        )
    )
    assert ret["documentType"]["receiptType"] == "RR"
    assert ret["header"]["referenceUUID"] == sale["header"]["uuid"]
    assert ret["header"]["referenceOldUUID"] == ""  # correction field stays empty


def test_walk_in_buyer_sends_no_empty_id_or_name():
    doc = build_receipt(_receipt())
    assert doc["buyer"] == {"type": "P"}


def test_dumps_writes_decimals_as_real_json_numbers():
    text = dumps({"receipts": [build_receipt(_receipt())]})
    parsed = json.loads(text)["receipts"][0]
    assert parsed["totalAmount"] == 228.0
    assert isinstance(parsed["itemData"][0]["quantity"], float)
    assert '"totalAmount":228.00000' in text  # exactly 5 decimals, no quotes


def test_reserved_fields_are_always_zero():
    """The authority accepts only 0 for feesAmount and adjustment (reserved for the future)."""
    doc = build_receipt(_receipt())
    assert doc["feesAmount"] == 0
    assert doc["adjustment"] == 0


def test_builder_is_deterministic():
    a = build_receipt(_receipt())
    b = build_receipt(_receipt())
    assert a == b


# ------------------------------------------------------------------ uuid ------------------
def test_uuid_depends_on_content_and_on_previous_uuid():
    base = build_receipt(_receipt())["header"]["uuid"]
    changed_amount = build_receipt(_receipt(lines=(_line(unit_price=D("101")),)))
    chained = build_receipt(_receipt(previous_uuid="a" * 64))
    assert changed_amount["header"]["uuid"] != base
    assert chained["header"]["uuid"] != base


def test_uuid_ignores_the_uuid_field_itself():
    doc = build_receipt(_receipt())
    from app.modules.einvoice.providers.eta.builder import _jsonable

    j = _jsonable(doc)
    assert compute_receipt_uuid(j) == doc["header"]["uuid"]
    j["header"]["uuid"] = "f" * 64  # a different embedded uuid must not change the result
    assert compute_receipt_uuid(j) == doc["header"]["uuid"]


# ------------------------------------------------------------------ validator -------------
def test_valid_receipt_has_no_issues():
    assert validate_receipt(_receipt(), now=NOW) == []


def test_validator_rejects_what_the_old_code_sent():
    bad = _receipt(
        seller=_seller(
            branch_code="",
            activity_code="47",
            device_serial="",
            branch_address=BranchAddress("", "", "", ""),
        )
    )
    codes = _codes(validate_receipt(bad, now=NOW))
    assert {"ETA-L-003", "ETA-L-004", "ETA-L-005", "ETA-L-006"} <= codes


@pytest.mark.parametrize("rin", ["", "12345678", "1234567890", "12345678a", "٦٧٤٨٥٩٥٤٥"])
def test_seller_rin_must_be_exactly_nine_ascii_digits(rin):
    assert "ETA-L-001" in _codes(validate_receipt(_receipt(seller=_seller(rin=rin)), now=NOW))


def test_future_receipt_is_refused():
    future = _receipt(issued_at=datetime(2027, 1, 1, tzinfo=UTC))
    assert "ETA-L-011" in _codes(validate_receipt(future, now=NOW))


def test_return_requires_reference_and_sale_must_not_have_one():
    assert "ETA-L-020" in _codes(
        validate_receipt(_receipt(receipt_type=ReceiptType.RETURN), now=NOW)
    )
    assert "ETA-L-021" in _codes(validate_receipt(_receipt(reference_uuid="a" * 64), now=NOW))


def test_business_buyer_rules():
    biz = _receipt(buyer=BuyerProfile(BuyerType.BUSINESS, id="123", name=""))
    codes = _codes(validate_receipt(biz, now=NOW))
    assert {"ETA-L-030", "ETA-L-031"} <= codes
    same = _receipt(buyer=BuyerProfile(BuyerType.BUSINESS, id="674859545", name="x"))
    assert "ETA-L-032" in _codes(validate_receipt(same, now=NOW))


def test_national_id_mandatory_from_150k():
    big = _receipt(lines=(_line(quantity=D("1"), unit_price=D("150000")),))
    assert "ETA-L-054" in _codes(validate_receipt(big, now=NOW))
    ok = _receipt(
        lines=big.lines, buyer=BuyerProfile(BuyerType.PERSON, id="29001011234567", name="x")
    )
    assert "ETA-L-054" not in _codes(validate_receipt(ok, now=NOW))


def test_unsupported_taxes_are_refused_not_miscomputed():
    bad = _receipt(lines=(_line(tax=ItemTax(tax_type="T2")),))
    assert "ETA-L-047" in _codes(validate_receipt(bad, now=NOW))


def test_document_consistency_catches_a_tampered_total():
    doc = build_receipt(_receipt())
    assert check_document_consistency(doc) == []
    doc["totalAmount"] = D("999")
    assert "ETA-L-062" in _codes(check_document_consistency(doc))


# ------------------------------------------------------------------ qr / codes ------------
def test_qr_matches_the_authority_example_exactly():
    qr = build_qr_payload(
        portal_base_url="http://invoicing.eta.gov.eg/",
        receipt_uuid="68e656b251e67e8358bef8483ab0d51c6619f3e7a1a9f0e75838d41ff368f320",
        issued_at=datetime(2022, 2, 19, 2, 0, tzinfo=UTC),
        total_amount=D("1000"),
        issuer_rin="674859545",
    )
    assert qr == (
        "http://invoicing.eta.gov.eg/receipts/search/"
        "68e656b251e67e8358bef8483ab0d51c6619f3e7a1a9f0e75838d41ff368f320"
        "/share/2022-02-19T02:00Z#Total:1000.000,IssuerRIN:674859545"
    )


@pytest.mark.parametrize(
    ("tender", "code"),
    [("cash", "C"), ("card", "V"), ("gift_card", "GC"), ("vodafone_cash", "O"), (None, "O")],
)
def test_payment_method_mapping(tender, code):
    assert payment_method_for_tender(tender).value == code


# ------------------------------------------------------------------ client + mock ---------
CRED = EtaCredentials("mock-client", "mock-secret", "POS-MOCK-1", "linux", "1", "mock-psk")


def _client(mock: MockAuthority, sleeps: list[float] | None = None):
    clock = {"t": 0.0}

    async def fake_sleep(s: float) -> None:
        if sleeps is not None:
            sleeps.append(s)

    http = httpx.AsyncClient(transport=mock.transport())
    return EtaClient(
        http,
        EtaEndpoints.for_environment("preprod"),
        CRED,
        clock=lambda: clock["t"],
        sleep=fake_sleep,
    ), clock


def _doc(prev: str = "", number: str = "R-1", **over):
    return build_receipt(_receipt(previous_uuid=prev, receipt_number=number, **over))


@pytest.mark.asyncio
async def test_token_is_cached_across_calls():
    mock = MockAuthority()
    client, _ = _client(mock)
    await client.submit_receipts([_doc()])
    await client.submit_receipts([_doc("", "R-2", lines=(_line(unit_price=D("7")),))])
    assert mock.token_requests == 1


@pytest.mark.asyncio
async def test_token_refreshes_before_expiry():
    mock = MockAuthority()
    client, clock = _client(mock)
    await client.access_token()
    clock["t"] = 3600 - 30  # inside the 60s safety margin
    await client.access_token()
    assert mock.token_requests == 2


@pytest.mark.asyncio
async def test_bad_credentials_raise_auth_error_without_retry():
    mock = MockAuthority(preshared_key="other")
    client, _ = _client(mock)
    with pytest.raises(EtaAuthError) as e:
        await client.access_token()
    assert "invalid_presharedkey" in str(e.value)
    assert mock.token_requests == 1


@pytest.mark.asyncio
async def test_accepted_receipt_and_hash_chain():
    mock = MockAuthority()
    client, _ = _client(mock)
    first = _doc()
    r1 = await client.submit_receipts([first])
    assert r1.accepted[0].uuid == first["header"]["uuid"] and not r1.rejected
    second = _doc(first["header"]["uuid"], "R-2", lines=(_line(unit_price=D("9")),))
    r2 = await client.submit_receipts([second])
    assert r2.accepted and not r2.rejected


@pytest.mark.asyncio
async def test_broken_chain_is_rejected_with_authority_style_error():
    mock = MockAuthority()
    client, _ = _client(mock)
    await client.submit_receipts([_doc()])
    orphan = _doc("b" * 64, "R-9", lines=(_line(unit_price=D("3")),))
    resp = await client.submit_receipts([orphan])
    assert not resp.accepted
    assert resp.rejected[0].details[0]["code"] == "CF321"


@pytest.mark.asyncio
async def test_rejected_receipt_does_not_advance_the_chain():
    mock = MockAuthority()
    client, _ = _client(mock)
    good = _doc()
    bad = _doc(good["header"]["uuid"], "R-2", lines=(_line(unit_price=D("5")),))
    bad["paymentMethod"] = ""  # authority will reject this one
    resp = await client.submit_receipts([good, bad])
    assert len(resp.accepted) == 1 and len(resp.rejected) == 1
    assert mock.last_uuid_by_pos["POS-MOCK-1"] == good["header"]["uuid"]


@pytest.mark.asyncio
async def test_throttle_429_waits_longer_than_retry_after_then_succeeds():
    mock = MockAuthority(fail_next=[429], retry_after=2)
    sleeps: list[float] = []
    client, _ = _client(mock, sleeps)
    resp = await client.submit_receipts([_doc()])
    assert resp.accepted
    assert sleeps and sleeps[0] > 2  # strictly longer than Retry-After


@pytest.mark.asyncio
async def test_503_retries_with_short_backoff():
    mock = MockAuthority(fail_next=[503])
    sleeps: list[float] = []
    client, _ = _client(mock, sleeps)
    assert (await client.submit_receipts([_doc()])).accepted
    assert 1 <= sleeps[0] <= 3


@pytest.mark.asyncio
async def test_persistent_throttle_surfaces_as_transient_error():
    mock = MockAuthority(fail_next=[429, 429, 429, 429])
    client, _ = _client(mock, [])
    with pytest.raises(EtaTransientError):
        await client.submit_receipts([_doc()])


@pytest.mark.asyncio
async def test_identical_resubmission_is_a_duplicate_not_a_second_receipt():
    mock = MockAuthority()
    client, _ = _client(mock, [])
    doc = _doc()
    await client.submit_receipts([doc])
    with pytest.raises(EtaTransientError) as e:  # 422 inside the 10-minute window
        await client.submit_receipts([doc])
    assert e.value.status == 422
    assert len(mock.submissions) == 1


@pytest.mark.asyncio
async def test_bad_structure_is_permanent_and_not_retried():
    mock = MockAuthority()
    client, _ = _client(mock)
    with pytest.raises(EtaPermanentError):
        await client.submit_receipts([])
    assert mock.token_requests == 1


@pytest.mark.asyncio
async def test_revoked_token_triggers_exactly_one_relogin():
    mock = MockAuthority()
    client, _ = _client(mock)
    await client.access_token()
    mock._issued_tokens.clear()  # authority forgot our token
    resp = await client.submit_receipts([_doc()])
    assert resp.accepted
    assert mock.token_requests == 2


@pytest.mark.asyncio
async def test_submission_status_lookup():
    mock = MockAuthority()
    client, _ = _client(mock)
    resp = await client.submit_receipts([_doc()])
    detail = await client.get_submission(resp.submission_uuid)
    assert detail["receiptsCount"] == 1
