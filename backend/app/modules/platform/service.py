"""PLATFORM services — jobs, notifications queue + signed outbound webhooks.

Notifications and webhooks are event-driven: the API (or a service) queues a
row + writes an outbox event; the relay forwards to Redis Streams; workers
deliver with retries. If n8n/SMTP/SMS providers are down, the core keeps
working (failure isolation). Jobs are different: ``JobService.create`` only
writes the durable record — the ``job-runner`` worker pool executes it, never
the request path.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationError
from app.core.events.writer import add_outbox_event
from app.core.net_guard import assert_public_url
from app.modules.platform.models import (
    AuditLog,
    Job,
    Notification,
    SecretReference,
    WebhookDelivery,
    WebhookEndpoint,
)

NOTIFICATION_STREAM = "platform.events"
WEBHOOK_STREAM = "platform.events"


class AuditService:
    """§66 — append-only audit log writer (cross-module safe, §8).

    Every critical mutation is auditable. Modules call this instead of
    touching AuditLog directly.
    """

    @staticmethod
    async def write(
        session,
        tenant_id: uuid.UUID | None,
        actor_user_id: uuid.UUID | None,
        action: str,
        resource_type: str,
        resource_id: str,
        *,
        before: dict | None = None,
        after: dict | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
            ip=ip,
            user_agent=user_agent,
        )
        session.add(entry)
        await session.flush()
        return entry


class SecretService:
    """§68-69: manage secret references + delegate to SecretStorePort.

    Business tables hold SecretReference rows (metadata + vault_key), never
    raw secret values. The actual values live behind SecretStorePort.
    """

    @staticmethod
    async def create_reference(
        session,
        tenant_id: uuid.UUID,
        *,
        provider: str,
        scope: str = "tenant",
        vault_key: str,
        workspace_id: uuid.UUID | None = None,
    ) -> SecretReference:
        """Register a secret reference. The actual value is stored via the port."""
        ref = SecretReference(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            provider=provider,
            scope=scope,
            vault_key=vault_key,
            status="active",
            version=1,
        )
        session.add(ref)
        await session.flush()
        return ref

    @staticmethod
    async def get_secret_value(
        session,
        tenant_id: uuid.UUID,
        provider: str,
    ) -> str | None:
        """Fetch the actual secret value through SecretStorePort (§68)."""
        from app.core.secrets import get_secret_store

        ref = (
            await session.execute(
                select(SecretReference).where(
                    SecretReference.tenant_id == tenant_id,
                    SecretReference.provider == provider,
                    SecretReference.status == "active",
                )
            )
        ).scalar_one_or_none()
        if ref is None:
            return None
        store = get_secret_store()
        return await store.get_or_none(ref.vault_key)

    @staticmethod
    async def rotate_secret(
        session,
        tenant_id: uuid.UUID,
        provider: str,
        new_value: str,
    ) -> SecretReference:
        """§69: rotate a secret — old version stays for grace period."""
        from datetime import UTC, datetime

        from app.core.secrets import get_secret_store

        ref = (
            await session.execute(
                select(SecretReference).where(
                    SecretReference.tenant_id == tenant_id,
                    SecretReference.provider == provider,
                    SecretReference.status == "active",
                )
            )
        ).scalar_one_or_none()
        if ref is None:
            raise NotFoundError(f"no secret reference found for provider {provider}")

        store = get_secret_store()
        new_version = await store.rotate(ref.vault_key, new_value)
        ref.version = new_version
        ref.rotated_at = datetime.now(UTC)
        ref.status = "active"
        await session.flush()
        return ref


class JobService:
    """Creates the user-facing Job record (§84) — the control surface only.

    The Job row is the durable handle a user watches and controls; the
    ``job-runner`` worker pool executes it. Creation is deliberately a plain
    insert with no scheduling: ``jobs`` carries no ``run_at``/``next_attempt_at``
    (that is ``scheduled_jobs``), so a new job is simply ``queued`` and the
    runner picks it up on its next poll. Nothing runs inside the request.
    """

    @staticmethod
    async def create(
        session,
        tenant_id: uuid.UUID,
        *,
        kind: str,
        actor_user_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
        max_attempts: int = 3,
    ) -> Job:
        """Queue a job of ``kind`` for this tenant.

        ``kind`` must match a handler registered with
        ``app.workers.job_runner.register_job_handler``; an unregistered kind is
        not rejected here (this layer must not import the worker registry) —
        the runner fails it with a clear error rather than leaving it queued.
        """
        if not kind:
            raise ValidationError("job kind is required")
        if max_attempts < 1:
            raise ValidationError("max_attempts must be at least 1")
        job = Job(
            tenant_id=tenant_id,
            kind=kind,
            status="queued",
            progress=0,
            attempts=0,
            max_attempts=max_attempts,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )
        session.add(job)
        await session.flush()
        return job


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
        # S6: reject internal/metadata targets at registration time so a tenant
        # cannot turn our delivery worker into an SSRF proxy. Re-validated at
        # send time in WebhookDispatcher.deliver (DNS rebinding).
        assert_public_url(url)
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

        # S6: re-validate at SEND time. A hostname that resolved to a public
        # address at registration can be re-pointed at an internal one later
        # (DNS rebinding) — the check has to happen on the request that
        # actually goes out, not only on the one that stored the URL.
        try:
            assert_public_url(endpoint.url)
        except ValidationError as exc:
            delivery.status = "dead"
            delivery.last_error = f"endpoint url rejected: {exc.message}"
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
