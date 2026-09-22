"""PLATFORM workers — notification delivery + webhook delivery + §24 retry.

Streams follow the outbox writer naming ({aggregate_type}.events):
notification.queued -> notification.events, webhook.deliver -> webhook.events.
(The previous "platform.events" subscription matched a stream nothing
publishes, so notifications and webhook deliveries never fired.)

§22: the webhook route no longer runs the long ingest block inline — it
persists the raw delivery and stages a ``webhook.ingest`` event in the same
transaction; this worker runs that block off the request path.

§24: failed inbound webhook ingress rows are reprocessed on the same stream —
a ``webhook.event.retry`` event (staged by the platform-admin retry endpoint
for one row, or as a per-tenant sweep) re-runs the exact ingest block the
queued path runs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.core.errors import ValidationError
from app.core.events.bus import Event
from app.core.events.schemas import EventEnvelope, deserialize_event
from app.modules.platform.models import Notification, WebhookEvent
from app.modules.platform.service import NotificationDispatcher, WebhookDispatcher
from app.workers.base import StreamWorker, defer_unless_tenant_allows

logger = logging.getLogger(__name__)

# Upper bound on how many failed ingress rows one sweep event may retry.
_RETRY_SWEEP_LIMIT = 50


class NotificationWorker(StreamWorker):
    stream = "notification.events"
    group = "notification-workers"
    name = "notification-worker"

    async def handle(self, event: Event) -> None:
        # Read through the §19 envelope's read half (finding 2); a non-envelope
        # entry fails CLOSED rather than being processed without a tenant.
        try:
            envelope = deserialize_event(event)
        except (ValidationError, KeyError, TypeError, ValueError):
            logger.warning("notification.event_without_envelope id=%s", event.id)
            return
        if envelope.type != "notification.queued":
            return
        notification_id = envelope.payload.get("notification_id")
        if not notification_id:
            return
        tenant_id = envelope.tenant_id
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                row = (
                    await session.execute(
                        select(Notification).where(
                            Notification.tenant_id == tenant_id,
                            Notification.id == uuid.UUID(notification_id),
                        )
                    )
                ).scalar_one_or_none()
                if row is None or row.status == "sent":
                    return
                await NotificationDispatcher.deliver(row)
                row.status = "sent"
                row.sent_at = datetime.now(UTC)


class WebhookWorker(StreamWorker):
    stream = "webhook.events"
    group = "webhook-workers"
    name = "webhook-worker"

    async def handle(self, event: Event) -> None:
        # Read through the §19 envelope's read half (finding 2); a non-envelope
        # entry fails CLOSED rather than being processed without a tenant.
        try:
            envelope = deserialize_event(event)
        except (ValidationError, KeyError, TypeError, ValueError):
            logger.warning("webhook.event_without_envelope id=%s", event.id)
            return
        if envelope.type == "webhook.event.retry":
            await self._retry_webhook_events(envelope)
            return
        if envelope.type == "webhook.ingest":
            await self._ingest_queued_event(envelope)
            return
        if envelope.type != "webhook.deliver":
            return
        delivery_id = envelope.payload.get("delivery_id")
        if not delivery_id:
            return
        tenant_id = envelope.tenant_id
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                # §48 — outbound integrations stop for a non-operational tenant.
                # Deferred, not dead-lettered: the delivery row keeps its retry
                # schedule and resumes if the tenant is reactivated.
                #
                # NotificationWorker deliberately does NOT get this gate:
                # in-app/email notifications are the channel through which a
                # suspended tenant learns why it was suspended, and the API
                # allowlist in identity.deps keeps /notifications reachable for
                # exactly that reason.
                await defer_unless_tenant_allows(
                    session, tenant_id, "allows_automation"
                )
                delivery = await WebhookDispatcher.deliver(
                    session, tenant_id, uuid.UUID(delivery_id)
                )
                if delivery is not None and delivery.status == "failed":
                    # Re-enqueue through the outbox so the relay re-fires it;
                    # the retry schedule lives on the delivery row.
                    from app.core.events.writer import add_outbox_event

                    if delivery.next_retry_at and delivery.next_retry_at <= datetime.now(
                        UTC
                    ) + timedelta(minutes=5):
                        await add_outbox_event(
                            session,
                            aggregate_type="webhook",
                            aggregate_id=delivery.id,
                            event_type="webhook.deliver",
                            tenant_id=tenant_id,
                            payload={"delivery_id": str(delivery.id)},
                        )

    async def _retry_webhook_events(self, envelope: EventEnvelope) -> None:
        """§24: re-ingest webhook rows the synchronous path failed on.

        The platform-admin retry endpoint schedules ONE row (payload carries
        ``webhook_event_id``); a sweep event (no id) retries the tenant's
        failed rows under the retry budget. The tenant GUC is bound before any
        load — webhook_events is FORCE-RLS, so an unbound sweep silently
        returned zero rows and nothing was ever retried.
        """
        tenant_id = envelope.tenant_id
        event_id = envelope.payload.get("webhook_event_id")
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                # §48 — a non-operational tenant's ingress is deferred, not
                # dead-lettered: it resumes if the tenant is reactivated.
                await defer_unless_tenant_allows(
                    session, tenant_id, "allows_channels"
                )
                retried = await retry_failed_webhook_events(
                    session,
                    tenant_id,
                    event_id=uuid.UUID(str(event_id)) if event_id else None,
                )
                logger.info(
                    "webhook.retry_swept tenant=%s rows=%s", tenant_id, retried
                )

    async def _ingest_queued_event(self, envelope: EventEnvelope) -> None:
        """§22: run the ingest block the request path deliberately skipped.

        Same tenant discipline as the retry path: own transaction, GUC bound
        before any load, and the §48 gate — a non-operational tenant's queued
        ingress defers rather than dead-letters.
        """
        tenant_id = envelope.tenant_id
        event_id = envelope.payload.get("webhook_event_id")
        if not event_id:
            return
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                await defer_unless_tenant_allows(
                    session, tenant_id, "allows_channels"
                )
                await ingest_queued_webhook_event(
                    session, tenant_id, uuid.UUID(str(event_id))
                )


async def retry_failed_webhook_events(
    session,
    tenant_id: uuid.UUID,
    *,
    event_id: uuid.UUID | None = None,
) -> int:
    """§24: re-run the ingest path for failed OR dead-lettered webhook ingress rows.

    Tenant-scoped by construction; the caller binds the tenant GUC and owns
    the transaction (services never commit). With ``event_id`` exactly that
    row is retried regardless of its attempts budget AND regardless of whether
    it already dead-lettered — a human decided (§24: the DLQ supports
    Replay/Retry). Without it, the sweep retries only the tenant's ``failed``
    rows whose budget is not yet spent; the budget-spent rows are already
    ``dead`` and leave the automatic rotation.

    The re-ingest IS the webhook router's block —
    ``IngestService.process_webhook_event`` — so idempotency keys make a
    replay safe (already-ingested messages dedupe) and success flips the row
    to processed. Returns the number of rows handled (processed or re-marked
    failed/dead).
    """
    from app.core.config import get_settings
    from app.modules.conversations.gateway.ingest import IngestService
    from app.modules.conversations.gateway.registry import get_adapter

    stmt = (
        select(WebhookEvent)
        .where(WebhookEvent.tenant_id == tenant_id)
        .order_by(WebhookEvent.received_at)
        .limit(_RETRY_SWEEP_LIMIT)
    )
    if event_id is not None:
        stmt = stmt.where(
            WebhookEvent.id == event_id,
            WebhookEvent.processing_status.in_(("failed", "dead")),
        )
    else:
        stmt = stmt.where(
            WebhookEvent.processing_status == "failed",
            WebhookEvent.attempts < get_settings().worker_max_attempts,
        )

    rows = (await session.execute(stmt)).scalars().all()
    handled = 0
    for row in rows:
        try:
            adapter = get_adapter(row.provider)
            if adapter is None:
                raise ValidationError(f"no adapter for provider: {row.provider}")
            await IngestService.process_webhook_event(
                session,
                adapter=adapter,
                channel=row.provider,
                tenant_id=tenant_id,
                event_id=row.id,
                payload=row.payload or {},
            )
        except Exception as exc:  # noqa: BLE001 — §24: recorded on the row
            await IngestService.mark_webhook_event_failed(session, row.id, exc)
            logger.warning(
                "webhook.retry_failed event=%s err=%s", row.id, exc
            )
        handled += 1
    return handled


async def ingest_queued_webhook_event(
    session,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
) -> int:
    """§22: process ONE queued ingress row — the block the route skipped.

    The webhook route persists the raw delivery and stages a ``webhook.ingest``
    event in the same transaction; this is the other half: it runs the EXACT
    ingest block (``IngestService.process_webhook_event``) the synchronous
    path used to run inline, so queued processing and request-path processing
    can never diverge.

    At-least-once delivery means the worker may see the same event twice
    (redelivery after a crash-reclaim). An already-processed row is a no-op —
    ``accepted`` stays 0 and nothing double-ingests (idempotency keys are the
    second line of defense for the messages themselves).

    A failure is quarantined under the §24 budget via
    ``mark_webhook_event_failed`` and NOT re-raised: re-raising would NAK the
    stream entry into endless redelivery of a deterministic bug. The §24
    sweep, and later the human DLQ, own the replay.

    Returns 1 if the row was handled (processed or quarantined), 0 if it was
    already terminal (no-op).
    """
    from app.modules.conversations.gateway.ingest import IngestService
    from app.modules.conversations.gateway.registry import get_adapter

    # isolation twice: explicit tenant filter + the bound GUC on FORCE-RLS.
    row = (
        await session.execute(
            select(WebhookEvent).where(
                WebhookEvent.tenant_id == tenant_id,
                WebhookEvent.id == event_id,
            )
        )
    ).scalar_one_or_none()
    if row is None or row.processing_status not in ("pending", "processing"):
        return 0
    try:
        adapter = get_adapter(row.provider)
        if adapter is None:
            raise ValidationError(f"no adapter for provider: {row.provider}")
        await IngestService.process_webhook_event(
            session,
            adapter=adapter,
            channel=row.provider,
            tenant_id=tenant_id,
            event_id=row.id,
            payload=row.payload or {},
        )
    except Exception as exc:  # noqa: BLE001 — §24: quarantine, never re-raise
        await IngestService.mark_webhook_event_failed(session, row.id, exc)
        logger.warning("webhook.ingest_failed event=%s err=%s", row.id, exc)
    return 1
