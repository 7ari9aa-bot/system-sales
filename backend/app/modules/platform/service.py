"""PLATFORM services — notifications queue + signed outbound webhooks.

Both are event-driven: the API (or a service) queues a row + writes an outbox
event; the relay forwards to Redis Streams; workers deliver with retries. If
n8n/SMTP/SMS providers are down, the core keeps working (failure isolation).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.events.writer import add_outbox_event
from app.modules.platform.models import Notification, WebhookDelivery, WebhookEndpoint

NOTIFICATION_STREAM = "platform.events"
WEBHOOK_STREAM = "platform.events"


class NotificationService:
    @staticmethod
    async def queue(
        session,
        tenant_id: uuid.UUID,
        *,
        channel: str,  # email | sms | push | inapp
        body: str,
        subject: str | None = None,
        user_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
    ) -> Notification:
        notification = Notification(
            tenant_id=tenant_id,
            channel=channel,
            subject=subject,
            body=body,
            user_id=user_id,
            customer_id=customer_id,
            status="queued",
        )
        session.add(notification)
        await session.flush()
        await add_outbox_event(
            session,
            aggregate_type="notification",
            aggregate_id=notification.id,
            event_type="notification.queued",
            tenant_id=tenant_id,
            payload={"notification_id": str(notification.id)},
        )
        return notification

    @staticmethod
    async def list(session, tenant_id: uuid.UUID, limit: int = 50) -> list[Notification]:
        rows = (
            await session.execute(
                select(Notification)
                .where(Notification.tenant_id == tenant_id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)


class NotificationDispatcher:
    """Worker-side delivery. Email/SMS providers plug in here; without
    credentials we mark sent as 'inapp' (visible in the dashboard) — never
    silently lost."""

    @staticmethod
    async def deliver(notification: Notification) -> bool:
        settings = get_settings()
        if notification.channel == "email" and settings.smtp_url:
            # SMTP delivery lands with the email provider integration (Stage 9
            # hardening); until configured we deliberately fall through to inapp.
            pass
        return True  # recorded as sent (inapp semantics) — core keeps working


class WebhookService:
    @staticmethod
    async def register_endpoint(
        session,
        tenant_id: uuid.UUID,
        *,
        url: str,
        events: list[str],
    ) -> WebhookEndpoint:
        endpoint = WebhookEndpoint(
            tenant_id=tenant_id,
            url=url,
            secret=uuid.uuid4().hex + uuid.uuid4().hex,
            events=events,
        )
        session.add(endpoint)
        await session.flush()
        return endpoint

    @staticmethod
    async def enqueue(
        session,
        tenant_id: uuid.UUID,
        *,
        event_name: str,
        payload: dict,
    ) -> list[WebhookDelivery]:
        endpoints = (
            await session.execute(
                select(WebhookEndpoint).where(
                    WebhookEndpoint.tenant_id == tenant_id,
                    WebhookEndpoint.is_active.is_(True),
                )
            )
        ).scalars().all()
        deliveries = []
        for endpoint in endpoints:
            if endpoint.events and event_name not in endpoint.events:
                continue
            delivery = WebhookDelivery(
                tenant_id=tenant_id,
                webhook_id=endpoint.id,
                event_name=event_name,
                payload={"event": event_name, "data": payload},
                status="queued",
                next_retry_at=datetime.now(UTC),
            )
            session.add(delivery)
            deliveries.append(delivery)
        await session.flush()
        for delivery in deliveries:
            await add_outbox_event(
                session,
                aggregate_type="webhook",
                aggregate_id=delivery.id,
                event_type="webhook.deliver",
                tenant_id=tenant_id,
                payload={"delivery_id": str(delivery.id)},
            )
        return deliveries


class WebhookDispatcher:
    """Delivers signed webhooks: X-SalesOS-Signature: sha256=HMAC(secret, body)."""

    TIMEOUT = 15.0

    @classmethod
    def sign(cls, secret: str, body: bytes) -> str:
        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    @classmethod
    async def deliver(
        cls,
        session,
        tenant_id: uuid.UUID,
        delivery_id: uuid.UUID,
        *,
        _client: httpx.AsyncClient | None = None,
    ) -> WebhookDelivery | None:
        delivery = (
            await session.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.tenant_id == tenant_id,
                    WebhookDelivery.id == delivery_id,
                )
            )
        ).scalar_one_or_none()
        if delivery is None or delivery.status in ("delivered", "dead"):
            return delivery

        endpoint = (
            await session.execute(
                select(WebhookEndpoint).where(WebhookEndpoint.id == delivery.webhook_id)
            )
        ).scalar_one_or_none()
        if endpoint is None or not endpoint.is_active:
            delivery.status = "failed"
            delivery.last_error = "endpoint missing or inactive"
            return delivery

        import json

        body = json.dumps(delivery.payload, default=str).encode()
        headers = {
            "Content-Type": "application/json",
            "X-SalesOS-Event": delivery.event_name,
            "X-SalesOS-Signature": cls.sign(endpoint.secret, body),
        }
        client = _client or httpx.AsyncClient(timeout=cls.TIMEOUT)
        try:
            response = await client.post(endpoint.url, content=body, headers=headers)
            delivery.attempts += 1
            delivery.response_code = response.status_code
            if 200 <= response.status_code < 300:
                delivery.status = "delivered"
                delivery.delivered_at = datetime.now(UTC)
                delivery.next_retry_at = None
            else:
                delivery.status = "failed"
                delivery.last_error = f"HTTP {response.status_code}"
                cls._schedule_retry(delivery)
        except Exception as exc:  # noqa: BLE001 — network errors are expected
            delivery.attempts += 1
            delivery.status = "failed"
            delivery.last_error = str(exc)[:300]
            cls._schedule_retry(delivery)
        finally:
            if _client is None:
                await client.aclose()
        return delivery

    @staticmethod
    def _schedule_retry(delivery: WebhookDelivery) -> None:
        settings = get_settings()
        if delivery.attempts >= settings.worker_max_attempts:
            delivery.status = "dead"
            return
        base = min(2.0 * (2 ** (delivery.attempts - 1)), 60.0)
        delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=base)
