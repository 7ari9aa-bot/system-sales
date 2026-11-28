"""``settings.changed`` consumer — cache invalidation + security audit.

Listens on the ``settings.events`` stream and handles ``settings.changed``
events emitted by :class:`SettingsService._record_change`.

For every event:
1. **Cache invalidation** — removes the ``(tenant_id, key)`` entry from the
   in-process settings cache (:mod:`app.platform.settings.cache`), so the next
   read picks up the new value from the database instead of a stale cached one.

2. **Security audit** — when the changed key starts with ``security.``, the
   consumer stages a ``security.setting_changed`` event in the outbox so the
   platform's security-audit pipeline can record it (who changed what, when,
   from where).  This is a *new* outbox event, not a side-effect on the
   original transaction: the consumer opens its own transaction.

The consumer is idempotent: the processed_events marker (handled by
:class:`StreamWorker`) prevents double-processing, and the cache invalidation
is safe to repeat.
"""

from __future__ import annotations

import logging
import uuid

from app.core import db as _db
from app.core.db import bind_tenant
from app.core.errors import ValidationError
from app.core.events.bus import Event
from app.core.events.schemas import deserialize_event
from app.core.events.writer import add_outbox_event
from app.platform.settings.cache import invalidate
from app.workers.base import StreamWorker

logger = logging.getLogger(__name__)


class SettingsConsumer(StreamWorker):
    """Consumes ``settings.changed`` events: invalidates cache, audits security keys."""

    stream = "settings.events"
    group = "settings-consumers"
    name = "settings-consumer"

    async def handle(self, event: Event) -> None:
        try:
            envelope = deserialize_event(event)
        except (ValidationError, KeyError, TypeError, ValueError):
            logger.warning("settings_consumer.event_without_envelope id=%s", event.id)
            return

        if envelope.type != "settings.changed":
            return

        tenant_id = envelope.tenant_id
        payload = envelope.payload
        key: str = payload.get("key", "")

        # 1. Invalidate the in-process cache for this (tenant, key).
        invalidate(tenant_id, key)
        logger.info("settings_consumer.cache_invalidated tenant=%s key=%s", tenant_id, key)

        # 2. For security.* settings, stage an audit event in the outbox.
        if key.startswith("security."):
            await self._audit_security_change(tenant_id, payload)

    async def _audit_security_change(self, tenant_id: uuid.UUID, payload: dict) -> None:
        """Stage a ``security.setting_changed`` outbox event for the audit pipeline."""
        # Access through the module (not a module-level import) so tests can
        # monkeypatch ``app.core.db.get_sessionmaker`` via the
        # ``app_sessions_on_test_connection`` fixture.
        session_factory = _db.get_sessionmaker()
        async with session_factory() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                await add_outbox_event(
                    session,
                    aggregate_type="security",
                    aggregate_id=tenant_id,
                    event_type="security.setting_changed",
                    tenant_id=tenant_id,
                    producer="settings-consumer",
                    payload={
                        "key": payload.get("key"),
                        "scope": payload.get("scope"),
                        "scope_id": payload.get("scope_id"),
                        "revision": payload.get("revision"),
                        "action": payload.get("action"),
                        "changed_by": payload.get("changed_by"),
                    },
                )
        logger.info(
            "settings_consumer.security_audit_staged tenant=%s key=%s",
            tenant_id,
            payload.get("key"),
        )
