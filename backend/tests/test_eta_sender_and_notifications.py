"""ETA send planning, the official correction scenario, and authority notifications.

The correction scenario is the worked example from the authority's Receipt Issuance FAQ
("resubmitting the corrected batch"): R1, R2 rejected, R2* (new uuid, same previousUUID,
referenceOldUUID=R2), and R3 whose previousUUID stays R2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest

from app.modules.einvoice.providers.eta.builder import build_receipt
from app.modules.einvoice.providers.eta.client import (
    EtaClient,
    EtaCredentials,
    EtaEndpoints,
)
from app.modules.einvoice.providers.eta.codes import PaymentMethod
from app.modules.einvoice.providers.eta.mock_authority import MockAuthority
from app.modules.einvoice.providers.eta.models import (
    BranchAddress,
    BuyerProfile,
    EtaLine,
    EtaReceiptInput,
    SellerProfile,
)
from app.modules.einvoice.providers.eta.notifications import (
    DeviceEventType,
    NotificationError,
    ReceiptEventType,
    api_key_matches,
    parse_general_notification,
    parse_receipt_notification,
)
from app.modules.einvoice.providers.eta.sender import (
    AMENDMENT_WITH_REFERENCE,
    DocState,
    QueuedDoc,
    after_accepted,
    after_rejected,
    after_transient_failure,
    backoff_for,
    plan_device,
)

T0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def _q(n: int, state: DocState = DocState.PENDING, **kw) -> QueuedDoc:
    base = dict(
        id=f"d{n}",
        device_serial="POS-1",
        uuid=f"{n:064x}",
        previous_uuid=f"{n - 1:064x}" if n > 1 else "",
        issued_at=T0 + timedelta(minutes=n),
        state=state,
    )
    base.update(kw)
    return QueuedDoc(**base)


NOW = T0 + timedelta(hours=1)


# ------------------------------------------------------------------ planner ----------------
def test_pending_receipts_go_out_oldest_first_even_if_given_shuffled():
    plan = plan_device([_q(3), _q(1), _q(2)], now=NOW)
    assert [d.id for d in plan.send] == ["d1", "d2", "d3"]


def test_nothing_to_send_when_everything_is_final():
    docs = [_q(1, DocState.VALID), _q(2, DocState.SUBMITTED), _q(3, DocState.CANCELLED)]
    assert plan_device(docs, now=NOW).send == ()


def test_a_receipt_waiting_to_retry_blocks_the_ones_behind_it():
    """Sending #2 before #1 would put the chain out of order at the authority."""
    waiting = _q(1, DocState.FAILED, next_attempt_at=NOW + timedelta(minutes=5))
    plan = plan_device([waiting, _q(2)], now=NOW)
    assert plan.send == ()
    assert plan.blocked_by and "waiting to retry" in plan.blocked_by


def test_batch_stops_at_the_first_receipt_that_is_not_due():
    docs = [_q(1), _q(2, DocState.FAILED, next_attempt_at=NOW + timedelta(minutes=5)), _q(3)]
    assert [d.id for d in plan_device(docs, now=NOW).send] == ["d1"]


def test_rejected_receipts_are_never_resent_blindly():
    plan = plan_device([_q(1, DocState.INVALID), _q(2)], now=NOW)
    assert [d.id for d in plan.send] == ["d2"]


def test_correction_window_is_96_hours_and_is_flagged_before_and_after():
    assert AMENDMENT_WITH_REFERENCE == timedelta(hours=96)
    rejected = _q(1, DocState.INVALID)
    soon = plan_device([rejected], now=T0 + timedelta(hours=80))
    assert soon.expiring == (rejected,) and soon.expired == ()
    late = plan_device([rejected], now=T0 + timedelta(hours=97))
    assert late.expired == (rejected,)
    early = plan_device([rejected], now=T0 + timedelta(hours=2))
    assert early.expiring == () and early.expired == ()


def test_outcomes():
    doc = _q(1, attempts=1)
    ok = after_accepted(doc)
    assert (ok.state, ok.next_attempt_at, ok.attempts) == (DocState.SUBMITTED, None, 2)
    retry = after_transient_failure(doc, now=NOW)
    assert retry.state is DocState.FAILED and retry.next_attempt_at > NOW
    throttled = after_transient_failure(doc, now=NOW, retry_after=600)
    assert throttled.next_attempt_at - NOW > timedelta(seconds=600)  # longer than Retry-After
    assert after_rejected(doc, now=NOW).needs_correction is True
    too_late = after_rejected(doc, now=T0 + timedelta(hours=100))
    assert too_late.state is DocState.INVALID and too_late.needs_correction is False


def test_backoff_grows_and_is_capped():
    steps = [backoff_for(n) for n in range(8)]
    assert steps == sorted(steps) and steps[-1] == steps[-2]


# ------------------------------------------------------------------ official scenario ------
def _input(number: str, previous: str, price: str, **over) -> EtaReceiptInput:
    base = dict(
        receipt_number=number,
        issued_at=T0,
        seller=SellerProfile(
            "674859545",
            "متجر",
            "1",
            BranchAddress("cairo", "city center", "16 street", "14"),
            "POS-MOCK-1",
            "4771",
        ),
        buyer=BuyerProfile(),
        lines=(EtaLine("S", "x", "EGS", "EG-1", D("1"), D(price)),),
        payment_method=PaymentMethod.CASH,
        previous_uuid=previous,
    )
    base.update(over)
    return EtaReceiptInput(**base)


def _client(mock: MockAuthority) -> EtaClient:
    async def no_sleep(_: float) -> None:
        return None

    return EtaClient(
        httpx.AsyncClient(transport=mock.transport()),
        EtaEndpoints.for_environment("preprod"),
        EtaCredentials("mock-client", "mock-secret", "POS-MOCK-1", "linux", "1", "mock-psk"),
        sleep=no_sleep,
    )


@pytest.mark.asyncio
async def test_official_correction_scenario_r1_r2_rejected_r2star_r3():
    mock = MockAuthority()
    client = _client(mock)

    r1 = build_receipt(_input("R1", "", "10"))
    r2_bad = build_receipt(_input("R2", r1["header"]["uuid"], "20"))
    r2_bad["paymentMethod"] = ""  # something the authority will refuse
    first = await client.submit_receipts([r1, r2_bad])
    assert [a.receipt_number for a in first.accepted] == ["R1"]
    assert [r.receipt_number for r in first.rejected] == ["R2"]

    # Corrected R2*: new uuid, SAME previousUUID, referenceOldUUID = the rejected R2.
    r2_fixed = build_receipt(
        _input("R2", r1["header"]["uuid"], "20", reference_old_uuid=r2_bad["header"]["uuid"])
    )
    assert r2_fixed["header"]["uuid"] != r2_bad["header"]["uuid"]
    # R3 keeps pointing at the ORIGINAL R2 (the authority's own example), not at R2*.
    r3 = build_receipt(_input("R3", r2_bad["header"]["uuid"], "30"))
    second = await client.submit_receipts([r2_fixed, r3])
    assert not second.rejected, [r.details for r in second.rejected]
    assert {a.receipt_number for a in second.accepted} == {"R2", "R3"}


@pytest.mark.asyncio
async def test_after_a_correction_the_next_receipt_must_point_at_the_original_not_the_fix():
    """The FAQ's example chains R3 to the rejected R2, not to R2*. Pointing at R2* is refused."""
    mock = MockAuthority()
    client = _client(mock)
    r1 = build_receipt(_input("R1", "", "10"))
    r2_bad = build_receipt(_input("R2", r1["header"]["uuid"], "20"))
    r2_bad["paymentMethod"] = ""
    await client.submit_receipts([r1, r2_bad])
    r2_fixed = build_receipt(
        _input("R2", r1["header"]["uuid"], "20", reference_old_uuid=r2_bad["header"]["uuid"])
    )
    await client.submit_receipts([r2_fixed])
    wrong = build_receipt(_input("R3", r2_fixed["header"]["uuid"], "30"))
    resp = await client.submit_receipts([wrong])
    assert resp.rejected and resp.rejected[0].details[0]["code"] == "CF321"
    right = build_receipt(_input("R3", r2_bad["header"]["uuid"], "31"))
    assert (await client.submit_receipts([right])).accepted


@pytest.mark.asyncio
async def test_a_correction_for_a_receipt_that_is_already_valid_is_refused():
    mock = MockAuthority()
    client = _client(mock)
    r1 = build_receipt(_input("R1", "", "10"))
    await client.submit_receipts([r1])
    dup = build_receipt(_input("R1b", "", "11", reference_old_uuid=r1["header"]["uuid"]))
    resp = await client.submit_receipts([dup])
    assert resp.rejected[0].details[0]["code"] == "CF322"


@pytest.mark.asyncio
async def test_a_correction_that_references_nothing_known_is_refused():
    mock = MockAuthority()
    resp = await _client(mock).submit_receipts(
        [build_receipt(_input("R1", "", "10", reference_old_uuid="c" * 64))]
    )
    assert resp.rejected[0].details[0]["code"] == "CF323"


# ------------------------------------------------------------------ notifications ----------
def test_api_key_check():
    assert api_key_matches("ApiKey s3cret", "s3cret")
    assert api_key_matches("apikey s3cret", "s3cret")
    assert not api_key_matches("ApiKey wrong", "s3cret")
    assert not api_key_matches("Bearer s3cret", "s3cret")
    assert not api_key_matches(None, "s3cret")
    assert not api_key_matches("ApiKey ", "")  # an unset key never authenticates


def _receipt_body(**over):
    body = {
        "deliveryId": "838847HS2",
        "type": "Receipt",
        "count": 2,
        "message": [
            {
                "type": "Validated",
                "uuid": "a" * 64,
                "submissionUUID": "S1",
                "longId": "L1",
                "internalId": "R-1",
                "status": "Valid",
            },
            {
                "type": "Validated",
                "uuid": "b" * 64,
                "submissionUUID": "S1",
                "longId": "L2",
                "internalId": "R-2",
                "status": "Invalid",
            },
        ],
    }
    body.update(over)
    return body


def test_receipt_notification_maps_to_document_statuses():
    ok, bad = parse_receipt_notification(_receipt_body())
    assert (ok.new_status, bad.new_status) == ("valid", "invalid")
    assert ok.delivery_id == bad.delivery_id == "838847HS2"
    cancelled = parse_receipt_notification(
        _receipt_body(message=[{"type": "Cancelled", "uuid": "c" * 64, "status": "Cancelled"}])
    )[0]
    assert cancelled.type is ReceiptEventType.CANCELLED and cancelled.new_status == "cancelled"
    received = parse_receipt_notification(
        _receipt_body(message=[{"type": "Received", "uuid": "d" * 64, "status": "Valid"}])
    )[0]
    assert received.new_status == "received"  # "received" is not "valid yet"


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"deliveryId": "x"},
        {"deliveryId": "", "message": []},
        {"deliveryId": "x", "message": ["nope"]},
        {"deliveryId": "x", "message": [{"type": "Weird", "uuid": "a"}]},
        {"deliveryId": "x", "message": [{"type": "Validated"}]},
    ],
)
def test_malformed_receipt_notifications_are_refused(body):
    with pytest.raises(NotificationError):
        parse_receipt_notification(body)


def test_device_notifications():
    deact = parse_general_notification(
        {"Id": "POS-1", "Type": "PosDeactivated", "Message": {"Reason": "Out of service"}}
    )
    assert deact.type is DeviceEventType.DEACTIVATED
    assert deact.blocks_issuing and deact.needs_merchant_attention
    unused = parse_general_notification({"Id": "POS-1", "Type": "PosDeviceUnused", "Message": {}})
    assert not unused.blocks_issuing and not unused.needs_merchant_attention
    expiring = parse_general_notification(
        {"Id": "POS-1", "Type": "PosCredentialExpiration", "Message": {"ExpirationPeriod": 1}}
    )
    assert not expiring.blocks_issuing and expiring.needs_merchant_attention
    for bad in (None, {"Type": "PosDeactivated"}, {"Id": "x", "Type": "Nope"}):
        with pytest.raises(NotificationError):
            parse_general_notification(bad)


class TestCorrectionWindowDependsOnTheReceiptKind:
    """ETA: a rejected receipt may be corrected within 96 hours, but a return WITHOUT a reference
    within 72 (its reference_less flag is how the planner knows which clock applies)."""

    NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

    def _rejected(self, hours_old: int, **kw):
        return _q(1, DocState.INVALID, issued_at=self.NOW - timedelta(hours=hours_old), **kw)

    def test_a_normal_receipt_can_still_be_corrected_at_80_hours(self):
        assert after_rejected(self._rejected(80), now=self.NOW).needs_correction is True

    def test_a_return_without_reference_can_not_at_80_hours(self):
        doc = self._rejected(80, reference_less=True)
        assert after_rejected(doc, now=self.NOW).needs_correction is False

    def test_a_return_without_reference_can_at_70_hours(self):
        doc = self._rejected(70, reference_less=True)
        assert after_rejected(doc, now=self.NOW).needs_correction is True

    def test_the_planner_counts_the_shorter_window_as_closed(self):
        late = self._rejected(80, reference_less=True)
        plan = plan_device([late], now=self.NOW)
        assert [d.id for d in plan.expired] == [late.id]
        normal = self._rejected(80)
        assert plan_device([normal], now=self.NOW).expired == ()

    def test_the_planner_warns_sooner_for_the_shorter_window(self):
        # 60h old: 12h left of 72 (warn), but 36h left of 96 (do not warn yet at a 24h notice)
        short = self._rejected(60, reference_less=True)
        assert [d.id for d in plan_device([short], now=self.NOW).expiring] == [short.id]
        normal = self._rejected(60)
        assert plan_device([normal], now=self.NOW).expiring == ()
