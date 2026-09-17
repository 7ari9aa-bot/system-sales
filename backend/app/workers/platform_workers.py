"""PLATFORM workers — notification delivery + webhook delivery.

Both consume the platform.events stream. Retries/DLQ come from StreamWorker.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.core.events.bus import Event
from app.modules.platform.models import Notification
from app.modules.platform.service import NotificationDispatcher, WebhookDispatcher
from app.workers.base import StreamWorker

logger = logging.getLogger(__name__)


class NotificationWorker(StreamWorker):
    stream = "platform.events"
    group = "notification-workers"
    name = "notification-worker"

    async def handle(self, event: Event) -> None:
        if event.payload.get("event_type") != "notification.queued":
            return
        tenant_raw = event.meta.get("tenant_id")
        notification_id = event.payload.get("notification_id")
        if not tenant_raw or not notification_id:
            return
        tenant_id = uuid.UUID(tenant_raw)
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
    stream = "platform.events"
    group = "webhook-workers"
    name = "webhook-worker"

    async def handle(self, event: Event) -> None:
        if event.payload.get("event_type") != "webhook.deliver":
            return
        tenant_raw = event.meta.get("tenant_id")
        delivery_id = event.payload.get("delivery_id")
        if not tenant_raw or not delivery_id:
            return
        tenant_id = uuid.UUID(tenant_raw)
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
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
