"""POS workers — the daily sales projection + receipt email (§189 phase 4/5).

Stream follows the outbox writer naming (``{aggregate_type}.events``):
``pos.session.closed`` and ``pos.receipt.email_requested`` both ride the
``pos_session.events`` stream, so one pool carries the till's whole async
surface — the ERPNext consolidation/async-closing jobs, rebuilt as an
event-fed projection (§190) plus the queued receipt mail.
"""

from __future__ import annotations

import logging
from datetime import date
from html import escape
from uuid import UUID

from app.core.db import SessionLocal, bind_tenant
from app.core.errors import ValidationError
from app.core.events.bus import Event
from app.core.events.schemas import EventEnvelope, deserialize_event
from app.modules.pos.service import PosService
from app.workers.base import StreamWorker

logger = logging.getLogger(__name__)


class PosWorker(StreamWorker):
    """Consumes pos_session.events: recompute the daily projection, send
    queued receipt emails."""

    stream = "pos_session.events"
    group = "pos-workers"
    name = "pos-worker"

    async def handle(self, event: Event) -> None:
        # A non-envelope entry fails CLOSED rather than being processed
        # without a tenant (the house rule every worker follows).
        try:
            envelope = deserialize_event(event)
        except (ValidationError, KeyError, TypeError, ValueError):
            logger.warning("pos.event_without_envelope id=%s", event.id)
            return
        if envelope.type == "pos.session.closed":
            await self._project_closed(envelope)
        elif envelope.type == "pos.receipt.email_requested":
            await self._email_receipt(envelope)
        # Anything else on the stream is acknowledged untouched — the worker
        # owns two event types, not the stream.

    async def _project_closed(self, envelope: EventEnvelope) -> None:
        business_date_raw = envelope.payload.get("business_date")
        if not business_date_raw:
            # A close event without its date is a producer bug; dead-letter it
            # rather than silently projecting nothing.
            raise ValidationError("pos.session.closed event has no business_date")
        tenant_id = envelope.tenant_id
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                written = await PosService.upsert_daily_projection(
                    session,
                    tenant_id,
                    business_date=date.fromisoformat(str(business_date_raw)),
                )
        logger.info(
            "pos.daily_projected tenant=%s date=%s rows=%s",
            tenant_id,
            business_date_raw,
            written,
        )

    async def _email_receipt(self, envelope: EventEnvelope) -> None:
        from app.modules.identity.email_delivery import ResendEmailSender

        receipt_id = envelope.payload.get("receipt_id")
        recipient = envelope.payload.get("email")
        if not receipt_id or not recipient:
            raise ValidationError("pos.receipt.email_requested event is incomplete")
        tenant_id = envelope.tenant_id
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                payload = await PosService.get_receipt(session, tenant_id, UUID(str(receipt_id)))
        # The mail goes out OUTSIDE the read transaction: a Resend timeout
        # must never roll a projection/session read back with it. The event's
        # own outbox id is the provider idempotency key — a redelivered event
        # cannot send the same receipt twice.
        sender = ResendEmailSender()
        await sender.send_receipt(
            delivery_id=UUID(str(envelope.id)),
            recipient=str(recipient),
            subject=payload["receipt"]["number"],
            html=_receipt_html(payload),
            text=_receipt_text(payload),
        )
        logger.info("pos.receipt_emailed tenant=%s receipt=%s", tenant_id, receipt_id)


def _receipt_html(payload: dict) -> str:
    """Minimal thermal-style HTML — the copy lives here, the transport does
    not (identity/email_delivery.py owns the wire, never the words)."""
    receipt = payload["receipt"]
    order = payload["order"]
    rows = "".join(
        "<tr>"
        f"<td>{escape(line.get('title') or line.get('sku') or '')} ×{line['quantity']}</td>"
        f"<td style='text-align:right'>{escape(str(line['total']))}</td>"
        "</tr>"
        for line in payload["lines"]
    )
    tenders = "".join(
        f"<div>{escape(str(t['amount']))} — {escape(str(t['method']))}</div>"
        for t in payload["tenders"]
    )
    return (
        '<!doctype html><html><body style="font-family:monospace">'
        f"<h2>{escape(receipt['number'])}</h2>"
        f"<p>{escape(str(order.get('number') or ''))}</p>"
        "<table>" + rows + "</table>"
        f"<p><b>{escape(str(order.get('grand_total') or ''))}</b></p>" + tenders + "</body></html>"
    )


def _receipt_text(payload: dict) -> str:
    receipt = payload["receipt"]
    order = payload["order"]
    lines = "\n".join(
        f"{line.get('title') or line.get('sku') or ''} x{line['quantity']} = {line['total']}"
        for line in payload["lines"]
    )
    return (
        f"{receipt['number']}\n{order.get('number') or ''}\n\n"
        f"{lines}\n\nTOTAL {order.get('grand_total') or ''}"
    )
