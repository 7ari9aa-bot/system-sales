"""PLATFORM workers — notification delivery + webhook delivery.

Streams follow the outbox writer naming ({aggregate_type}.events):
notification.queued -> notification.events, webhook.deliver -> webhook.events.
(The previous "platform.events" subscription matched a stream nothing
publishes, so notifications and webhook deliveries never fired.)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.core.errors import ValidationError
from app.core.events.bus import Event
from app.core.events.schemas import deserialize_event
from app.modules.platform.models import Notification
from app.modules.platform.service import NotificationDispatcher, WebhookDispatcher
from app.workers.base import StreamWorker, defer_unless_tenant_allows

logger = logging.getLogger(__name__)


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
