"""Applying the ETA rules to the database: delivering receipts and recording what comes back.

Three entry points, each working inside the caller's tenant-bound transaction:

* ``deliver_device``  the periodic sender for ONE till: pick its undelivered receipts, ask the
  planner what to send, send the stored bytes, record the outcome.
* ``apply_receipt_event``  a callback told us a receipt is valid / invalid / cancelled.
* ``apply_device_event``  a callback told us something about the till itself.

Rules that matter here, all about not lying about a fiscal document:

* The bytes sent are the bytes stored (``raw_payload``). They were hashed to make the receipt's
  id, so rebuilding them would change the id.
* A till is locked ``FOR UPDATE SKIP LOCKED`` while its batch is claimed, so two workers can
  never send the same receipts twice.
* An accepted answer is final; nothing here ever resends it.
* A repeated callback is recognised by its delivery id and ignored, never applied twice.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.einvoice.models import EInvoiceDevice, EInvoiceDocument, EInvoiceNotification
from app.modules.einvoice.providers.eta.client import (
    EtaAuthError,
    EtaError,
    EtaTransientError,
)
from app.modules.einvoice.providers.eta.notifications import (
    DeviceEvent,
    ReceiptEvent,
    stored_status,
)
from app.modules.einvoice.providers.eta.provider import EtaEInvoiceProvider
from app.modules.einvoice.providers.eta.sender import (
    DocState,
    Outcome,
    Plan,
    QueuedDoc,
    after_accepted,
    after_rejected,
    after_transient_failure,
    plan_device,
)

logger = logging.getLogger(__name__)

# Stored status (the table's words) <-> the planner's states.
_TO_STATE = {
    "signed": DocState.PENDING,
    "failed": DocState.FAILED,
    "submitted": DocState.SUBMITTED,
    "reported": DocState.VALID,
    "rejected": DocState.INVALID,
    "cancelled": DocState.CANCELLED,
}
# Documents the planner needs to see: anything still moving or awaiting correction.
_OPEN_STORED = ("signed", "failed", "rejected")


@dataclass
class DeliveryReport:
    """What one run did for one till (returned to the job log; also what tests assert on)."""

    device_serial: str
    sent: int = 0
    accepted: int = 0
    rejected: int = 0
    failed: int = 0
    blocked_by: str | None = None
    needs_correction: list[str] = field(default_factory=list)  # receipt numbers
    window_closing: list[str] = field(default_factory=list)
    window_closed: list[str] = field(default_factory=list)


def _queued(doc: EInvoiceDocument, serial: str) -> QueuedDoc:
    return QueuedDoc(
        id=str(doc.id),
        device_serial=serial,
        uuid=doc.invoice_hash,
        previous_uuid=doc.pih,
        issued_at=doc.issued_at,
        sequence=doc.icv or 0,
        state=_TO_STATE[doc.status],
        attempts=doc.delivery_attempts or 0,
        next_attempt_at=doc.next_attempt_at,
        reference_old_uuid=doc.reference_old_uuid or "",
    )


def _apply(doc: EInvoiceDocument, outcome: Outcome) -> None:
    doc.status = stored_status(outcome.state.value)
    doc.delivery_attempts = outcome.attempts
    doc.next_attempt_at = outcome.next_attempt_at


async def deliver_device(
    session: AsyncSession,
    device_id: uuid.UUID,
    *,
    now: datetime | None = None,
    provider: EtaEInvoiceProvider | None = None,
) -> DeliveryReport | None:
    """Send what is due for one till. ``None`` when another worker already holds it."""
    now = now or datetime.now(UTC)
    device = (
        await session.execute(
            select(EInvoiceDevice)
            .where(EInvoiceDevice.id == device_id)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if device is None:
        return None
    report = DeliveryReport(device_serial=device.device_serial)
    if device.status != "active" or device.provider_type != "eta":
        report.blocked_by = (
            f"till is {device.status}/{device.provider_type}, not an active ETA till"
        )
        return report
    if not (device.credentials or {}).get("eta"):
        report.blocked_by = "ETA credentials are not configured on this till"
        return report

    docs = (
        (
            await session.execute(
                select(EInvoiceDocument)
                .where(
                    EInvoiceDocument.device_id == device.id,
                    EInvoiceDocument.status.in_(_OPEN_STORED),
                )
                .order_by(EInvoiceDocument.icv, EInvoiceDocument.issued_at, EInvoiceDocument.id)
            )
        )
        .scalars()
        .all()
    )
    by_id = {str(d.id): d for d in docs}
    from app.modules.settings.service import SettingsService

    # How early the owner wants to be warned is the merchant's own choice (Settings > e-receipt).
    warn_hours = int(
        await SettingsService(session, device.tenant_id).value(
            "einvoice.warn_hours_before_deadline"
        )
    )
    plan: Plan = plan_device(
        [_queued(d, device.device_serial) for d in docs],
        now=now,
        warn_before=timedelta(hours=warn_hours),
    )
    report.blocked_by = plan.blocked_by
    report.window_closing = [by_id[q.id].invoice_number for q in plan.expiring]
    report.window_closed = [by_id[q.id].invoice_number for q in plan.expired]
    if not plan.send:
        return report

    provider = provider or EtaEInvoiceProvider()
    cfg = device.credentials["eta"]
    batch = [by_id[q.id] for q in plan.send]
    report.sent = len(batch)
    try:
        client = provider._client(device, cfg)  # noqa: SLF001 - same module family
        body = ('{"receipts":[' + ",".join(d.raw_payload or "" for d in batch) + "]}").encode()
        resp = await client.submit_raw(body)
    except (EtaAuthError, EtaTransientError) as exc:
        retry_after = float(getattr(exc, "retry_after", 0.0) or 0.0)
        for d in batch:
            _apply(
                d,
                after_transient_failure(
                    _queued(d, device.device_serial), now=now, retry_after=retry_after
                ),
            )
            d.errors = [str(exc)]
        report.failed = len(batch)
        return report
    except EtaError as exc:
        # The whole request was refused (bad structure, wrong submitter): a bug or a setup
        # problem, not something a retry fixes. Keep them deliverable but visible.
        for d in batch:
            _apply(d, after_transient_failure(_queued(d, device.device_serial), now=now))
            d.errors = [f"submission refused: {exc}"]
        report.failed = len(batch)
        report.blocked_by = f"submission refused: {exc}"
        return report

    accepted = {a.uuid: a for a in resp.accepted}
    rejected = {r.uuid: r for r in resp.rejected}
    for d in batch:
        q = _queued(d, device.device_serial)
        d.submission_uuid = resp.submission_uuid or None
        if d.invoice_hash in accepted:
            _apply(d, after_accepted(q))
            d.authority_long_id = accepted[d.invoice_hash].long_id or None
            d.authority_uuid = d.invoice_hash
            d.errors = []
            report.accepted += 1
        elif d.invoice_hash in rejected:
            outcome = after_rejected(q, now=now)
            _apply(d, outcome)
            r = rejected[d.invoice_hash]
            d.errors = [
                f"{r.message}: {x.get('code')} {x.get('message')}" for x in (r.details or ({},))
            ]
            d.authority_response = resp.raw
            report.rejected += 1
            if outcome.needs_correction:
                report.needs_correction.append(d.invoice_number)
        else:
            # Neither accepted nor rejected in a 2xx answer: do not guess. Leave it deliverable
            # and let the planner retry; the duplicate rule makes a resend harmless.
            _apply(d, after_transient_failure(q, now=now))
            d.errors = ["authority answered without a verdict for this receipt"]
            report.failed += 1
    await session.flush()
    return report


# ---------------------------------------------------------------------------------------------
async def _record_notification(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    device_id: uuid.UUID,
    kind: str,
    delivery_id: str,
    payload: dict,
) -> bool:
    """Write the ledger row. False when this delivery was already recorded (a repeat)."""
    try:
        async with session.begin_nested():
            session.add(
                EInvoiceNotification(
                    tenant_id=tenant_id,
                    device_id=device_id,
                    kind=kind,
                    delivery_id=delivery_id,
                    payload=payload,
                )
            )
            await session.flush()
    except IntegrityError:
        return False
    return True


async def apply_receipt_events(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    device_id: uuid.UUID,
    events: list[ReceiptEvent],
    raw_body: dict,
    now: datetime | None = None,
) -> dict[str, int]:
    """Record a receipt callback. Returns counts; a repeated delivery changes nothing."""
    now = now or datetime.now(UTC)
    if not events:
        return {"applied": 0, "unknown": 0, "repeat": 0}
    if not await _record_notification(
        session,
        tenant_id=tenant_id,
        device_id=device_id,
        kind="receipt",
        delivery_id=events[0].delivery_id,
        payload=raw_body,
    ):
        return {"applied": 0, "unknown": 0, "repeat": len(events)}

    applied = unknown = 0
    for ev in events:
        doc = (
            await session.execute(
                select(EInvoiceDocument)
                .where(
                    EInvoiceDocument.tenant_id == tenant_id,
                    EInvoiceDocument.device_id == device_id,
                    EInvoiceDocument.invoice_hash == ev.uuid,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if doc is None:
            unknown += 1  # not ours (or not stored yet): the authority is still answered 200
            logger.warning("eta.callback.unknown_receipt device=%s uuid=%s", device_id, ev.uuid)
            continue
        if doc.status == "cancelled":
            continue  # a voided receipt does not come back to life
        new = stored_status(ev.new_status)
        if new == "reported" and doc.status == "reported":
            continue
        doc.status = new
        doc.next_attempt_at = None
        if ev.long_id:
            doc.authority_long_id = ev.long_id
        if ev.submission_uuid:
            doc.submission_uuid = ev.submission_uuid
        doc.authority_uuid = ev.uuid
        if new == "reported":
            doc.reported_at = now
            doc.errors = []
        applied += 1
    for_row = (
        await session.execute(
            select(EInvoiceNotification).where(
                EInvoiceNotification.tenant_id == tenant_id,
                EInvoiceNotification.kind == "receipt",
                EInvoiceNotification.delivery_id == events[0].delivery_id,
            )
        )
    ).scalar_one()
    for_row.processed_at = now
    await session.flush()
    return {"applied": applied, "unknown": unknown, "repeat": 0}


async def apply_device_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    device_id: uuid.UUID,
    event: DeviceEvent,
    raw_body: dict,
    now: datetime | None = None,
) -> str:
    """Record a till-level callback. Returns what happened: ``applied`` | ``repeat``."""
    now = now or datetime.now(UTC)
    delivery_id = (
        f"{event.type.value}:{event.device_serial}:{json.dumps(event.message, sort_keys=True)}"
    )
    if not await _record_notification(
        session,
        tenant_id=tenant_id,
        device_id=device_id,
        kind="general",
        delivery_id=delivery_id[:127],
        payload=raw_body,
    ):
        return "repeat"
    device = (
        await session.execute(
            select(EInvoiceDevice)
            .where(EInvoiceDevice.id == device_id, EInvoiceDevice.tenant_id == tenant_id)
            .with_for_update()
        )
    ).scalar_one()
    notes = dict(device.metadata_info or {})
    eta = dict(notes.get("eta") or {})
    alerts = list(eta.get("alerts") or [])
    alerts.append(
        {
            "type": event.type.value,
            "message": event.message,
            "at": now.isoformat(),
            "needs_attention": event.needs_merchant_attention,
        }
    )
    eta["alerts"] = alerts[-20:]
    if event.blocks_issuing:
        device.status = "suspended"  # stop sending until the merchant reactivates the till
        eta["deactivated_reason"] = event.message.get("Reason") or event.message.get("reason", "")
    notes["eta"] = eta
    device.metadata_info = notes
    await session.flush()
    return "applied"


async def deliver_tenant(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    now: datetime | None = None,
    provider: EtaEInvoiceProvider | None = None,
) -> dict:
    """Run the sender for every active, configured ETA till of one store.

    A till that fails must not stop the others (one till's bad credentials are not another's
    problem), so each runs in its own savepoint and a failure is counted, logged without any
    credential, and left for the next run.
    """
    ids = (
        (
            await session.execute(
                select(EInvoiceDevice.id)
                .where(
                    EInvoiceDevice.tenant_id == tenant_id,
                    EInvoiceDevice.provider_type == "eta",
                    EInvoiceDevice.status == "active",
                )
                .order_by(EInvoiceDevice.created_at, EInvoiceDevice.id)
            )
        )
        .scalars()
        .all()
    )
    totals = {"tills": 0, "sent": 0, "accepted": 0, "rejected": 0, "failed": 0, "errors": 0}
    attention: list[dict] = []
    for device_id in ids:
        try:
            async with session.begin_nested():
                report = await deliver_device(session, device_id, now=now, provider=provider)
        except Exception:  # noqa: BLE001 - one till must never stop the others
            logger.exception("eta.deliver.till_failed tenant=%s device=%s", tenant_id, device_id)
            totals["errors"] += 1
            continue
        if report is None:
            continue  # another worker holds this till right now
        totals["tills"] += 1
        for k in ("sent", "accepted", "rejected", "failed"):
            totals[k] += getattr(report, k)
        if report.needs_correction or report.window_closing or report.window_closed:
            attention.append(
                {
                    "till": report.device_serial,
                    "needs_correction": report.needs_correction,
                    "window_closing": report.window_closing,
                    "window_closed": report.window_closed,
                }
            )
    return {**totals, "attention": attention}


def owner_messages(attention: list[dict]) -> list[tuple[str, str, str]]:
    """What to tell the owner, as (key, title, body), from ``deliver_tenant``'s attention list.

    One message per till and per kind of problem, each saying what happened and what to do. Plain
    Arabic, no codes: the owner is a shop keeper, not an integrator.
    """
    out: list[tuple[str, str, str]] = []
    for a in attention:
        till = a["till"]
        if a["needs_correction"]:
            n = len(a["needs_correction"])
            out.append(
                (
                    f"{till}:rejected",
                    "إيصال إلكتروني مرفوض من مصلحة الضرائب",
                    f"{n} إيصال على الجهاز {till} رفضته المصلحة وينتظر تصحيحه. "
                    "راجع بيانات المحل والأصناف (الرقم الضريبي، كود الفرع، كود الصنف).",
                )
            )
        if a["window_closing"]:
            n = len(a["window_closing"])
            out.append(
                (
                    f"{till}:closing",
                    "مهلة إرسال إيصالات إلكترونية على وشك الانتهاء",
                    f"{n} إيصال على الجهاز {till} لم يصل للمصلحة وتنتهي مهلته قريبًا. "
                    "تأكد من الاتصال بالإنترنت ومن اكتمال إعدادات الإيصال الإلكتروني.",
                )
            )
        if a["window_closed"]:
            n = len(a["window_closed"])
            out.append(
                (
                    f"{till}:closed",
                    "إيصالات إلكترونية انتهت مهلة إرسالها",
                    f"{n} إيصال على الجهاز {till} انتهت مهلته قبل وصوله للمصلحة. "
                    "يلزم طلب إرسال متأخر من بوابة الممول.",
                )
            )
    return out


async def notify_owners(
    session: AsyncSession, tenant_id: uuid.UUID, attention: list[dict], owner_ids: list[uuid.UUID]
) -> int:
    """Put what needs the owner's attention in their bell. Returns how many it wrote.

    The job runs every minute, so a problem that stays is reminded once per till, per kind, per
    day (the dedup key carries the date), never once a minute.
    """
    from app.modules.notifications.service import NotificationService

    messages = owner_messages(attention)
    if not messages or not owner_ids:
        return 0
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    written = 0
    for user_id in owner_ids:
        for key, title, body in messages:
            till, problem = key.split(":")
            await NotificationService.create(
                session,
                tenant_id,
                user_id,
                kind="einvoice",
                title=title,
                body=body,
                payload={"till": till, "problem": problem},
                dedup_key=f"eta:{key}:{today}",
            )
            written += 1
    return written
