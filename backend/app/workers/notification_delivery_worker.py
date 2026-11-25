"""Notification delivery worker — consumes ``notification.email`` and
``notification.push`` events from the outbox stream and delivers them through
provider adapters.

The notification service ``dispatch`` method already gates delivery on
``notifications.email_enabled`` / ``notifications.push_enabled`` before staging
the outbox event.  This worker is the SECOND gate: it re-checks the setting at
delivery time so a tenant that disables email after an event was staged does
not send a stale message.

Provider selection:

* Email: ``ResendEmailProvider`` (production) or ``FakeEmailProvider`` (tests).
* Push: ``FakePushProvider`` for now — a real push adapter plugs in the same way.

The worker subscribes to the ``notification.events`` stream (same stream the
existing ``NotificationWorker`` uses for ``notification.queued``) with its own
consumer group so the two workers do not steal from each other.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.db import SessionLocal, bind_tenant
from app.core.errors import ValidationError
from app.core.events.bus import Event
from app.core.events.schemas import deserialize_event
from app.core.settings_read import setting_bool
from app.modules.notifications.providers import (
    EmailProvider,
    PushProvider,
    ResendEmailProvider,
)
from app.workers.base import StreamWorker

logger = logging.getLogger(__name__)

#: Type of the injectable settings checker.  In production the default opens
#: its own ``SessionLocal()``; tests pass a closure over the shared fixture
#: session so it sees uncommitted data.
SettingsChecker = Callable[[uuid.UUID, str], Awaitable[bool]]


async def _default_email_enabled(tenant_id: uuid.UUID, key: str) -> bool:
    async with SessionLocal() as session:
        async with session.begin():
            await bind_tenant(session, tenant_id)
            return await setting_bool(session, tenant_id, key)


class NotificationDeliveryWorker(StreamWorker):
    """Drains ``notification.email`` and ``notification.push`` from the outbox."""

    stream = "notification.events"
    group = "notification-delivery"
    name = "notification-delivery-worker"

    def __init__(
        self,
        bus: Any,
        *,
        email_provider: EmailProvider | None = None,
        push_provider: PushProvider | None = None,
        settings_checker: SettingsChecker | None = None,
    ) -> None:
        super().__init__(bus)
        self._email_provider = email_provider or ResendEmailProvider()
        self._push_provider = push_provider
        self._settings_checker = settings_checker or _default_email_enabled

    async def handle(self, event: Event) -> None:
        try:
            envelope = deserialize_event(event)
        except (ValidationError, KeyError, TypeError, ValueError):
            logger.warning("notification_delivery.event_without_envelope id=%s", event.id)
            return

        if envelope.type == "notification.email":
            await self._handle_email(envelope)
        elif envelope.type == "notification.push":
            await self._handle_push(envelope)
        # Other event types (notification.queued etc.) are left to the
        # existing NotificationWorker.

    async def _handle_email(self, envelope) -> None:
        payload = envelope.payload
        to = payload.get("to")
        subject = payload.get("subject", "")
        body = payload.get("body", "")
        if not to:
            logger.warning("notification.email missing 'to' — skipping")
            return

        # Second gate: re-check email_enabled at delivery time.
        enabled = await self._settings_checker(envelope.tenant_id, "notifications.email_enabled")
        if not enabled:
            logger.info(
                "notification.email skipped — email_enabled is False for %s",
                envelope.tenant_id,
            )
            return

        await self._email_provider.send(to=to, subject=subject, body=body)

    async def _handle_push(self, envelope) -> None:
        payload = envelope.payload
        title = payload.get("title", "")
        body = payload.get("body", "")
        user_id = payload.get("user_id")
        if not user_id:
            logger.warning("notification.push missing 'user_id' — skipping")
            return

        # Second gate: re-check push_enabled at delivery time.
        enabled = await self._settings_checker(envelope.tenant_id, "notifications.push_enabled")
        if not enabled:
            logger.info(
                "notification.push skipped — push_enabled is False for %s",
                envelope.tenant_id,
            )
            return

        if self._push_provider is None:
            logger.debug(
                "notification.push no provider configured — skipping for %s",
                envelope.tenant_id,
            )
            return

        # Push tokens are a future feature (device-token table).  When a
        # provider IS configured the caller is expected to also provide the
        # token lookup; for now the push path is ready but tokenless.
        token = payload.get("token")
        if not token:
            logger.debug("notification.push no token for user %s — skipping", user_id)
            return

        await self._push_provider.send(token=token, title=title, body=body)
