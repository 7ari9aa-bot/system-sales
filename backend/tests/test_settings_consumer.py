"""Tests for the ``settings.changed`` consumer worker.

Verifies that the consumer:
* invalidates the in-process settings cache for the changed (tenant, key);
* stages a ``security.setting_changed`` outbox event when the key is a
  ``security.*`` setting;
* does NOT stage a security audit event for non-security keys;
* ignores events that are not ``settings.changed``.

The consumer opens its own short-lived session via ``get_sessionmaker()``.
In production that resolves to the process-wide engine; in tests we patch it
through ``app_sessions_on_test_connection`` so the consumer's writes land on
the **same** connection as the test's ``db`` fixture — otherwise the
consumer's outbox inserts are invisible to the test (transaction isolation).
"""

from __future__ import annotations

import json
import uuid

import pytest

import app.core.model_registry  # noqa: F401 — complete table registration
from app.core.db import bind_tenant
from app.core.events.bus import Event
from app.core.events.schemas import build_envelope, serialize
from app.platform.settings import cache
from app.platform.settings.cache import put
from app.workers.settings_consumer import SettingsConsumer


def _uuid_hex() -> str:
    return uuid.uuid4().hex[:8]


async def _create_tenant(db) -> tuple:
    from app.platform.identity.service import AuthService

    email = f"sc-{_uuid_hex()}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Settings Consumer Tenant",
        tenant_slug=f"sc-{_uuid_hex()}",
        email=email,
        password="strong-password-1",
        full_name="Consumer Owner",
    )
    await db.flush()
    return user, tenant


def _make_event(
    event_type: str,
    tenant_id: uuid.UUID,
    payload: dict,
) -> Event:
    """Build a realistic bus Event with a §19 envelope."""
    envelope = serialize(
        build_envelope(
            event_type=event_type,
            tenant_id=tenant_id,
            aggregate_type="settings",
            aggregate_id=str(uuid.uuid4()),
            producer="settings",
            payload=payload,
        )
    )
    return Event(
        id=str(uuid.uuid4()),
        stream="settings.events",
        payload=json.loads(envelope["payload"]),
        meta={**json.loads(envelope["meta"]), "outbox_id": str(uuid.uuid4())},
    )


class TestSettingsConsumer:
    """The consumer invalidates cache and audits security-key changes."""

    @pytest.mark.asyncio
    async def test_invalidates_cache_for_changed_key(self, db) -> None:
        cache.clear()
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)

        # Pre-populate the cache with a stale value.
        put(tenant.id, "tenant", None, "pos.max_discount_pct", 15.0)
        assert cache.get(tenant.id, "tenant", None, "pos.max_discount_pct") == 15.0

        consumer = SettingsConsumer.__new__(SettingsConsumer)
        consumer._bus = None  # type: ignore[assignment]
        consumer._running = False

        event = _make_event(
            "settings.changed",
            tenant.id,
            {
                "key": "pos.max_discount_pct",
                "scope": "tenant",
                "scope_id": None,
                "revision": "rev-1",
                "action": "set",
                "changed_by": str(user.id),
            },
        )
        await consumer.handle(event)

        # The cache entry should be gone.
        assert cache.get(tenant.id, "tenant", None, "pos.max_discount_pct") is None

    @pytest.mark.asyncio
    async def test_security_key_stages_audit_outbox_event(
        self, db, app_sessions_on_test_connection
    ) -> None:
        from sqlalchemy import select

        from app.platform.platform.models import OutboxEvent

        cache.clear()
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)

        put(tenant.id, "tenant", None, "security.require_strong_passwords", True)

        consumer = SettingsConsumer.__new__(SettingsConsumer)
        consumer._bus = None  # type: ignore[assignment]
        consumer._running = False

        event = _make_event(
            "settings.changed",
            tenant.id,
            {
                "key": "security.require_strong_passwords",
                "scope": "tenant",
                "scope_id": None,
                "revision": "rev-2",
                "action": "set",
                "changed_by": str(user.id),
            },
        )
        await consumer.handle(event)

        # Cache invalidated.
        assert cache.get(tenant.id, "tenant", None, "security.require_strong_passwords") is None

        # A security.setting_changed outbox event was staged — query through
        # the patched session factory so we see the consumer's writes.
        # Filter on event_type inside the payload so we don't match the
        # security events that AuthService.register itself emits.
        factory = app_sessions_on_test_connection
        async with factory() as session:
            await bind_tenant(session, tenant.id)
            rows = (
                (
                    await session.execute(
                        select(OutboxEvent).where(
                            OutboxEvent.aggregate_type == "security",
                            OutboxEvent.payload["event_type"].astext == "security.setting_changed",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) >= 1
            row = rows[-1]
            assert row.payload["key"] == "security.require_strong_passwords"
            assert row.payload["action"] == "set"
            assert row.payload["changed_by"] == str(user.id)

    @pytest.mark.asyncio
    async def test_non_security_key_does_not_stage_audit(
        self, db, app_sessions_on_test_connection
    ) -> None:
        from sqlalchemy import select

        from app.platform.platform.models import OutboxEvent

        cache.clear()
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)

        consumer = SettingsConsumer.__new__(SettingsConsumer)
        consumer._bus = None  # type: ignore[assignment]
        consumer._running = False

        event = _make_event(
            "settings.changed",
            tenant.id,
            {
                "key": "pos.return_max_days",
                "scope": "tenant",
                "scope_id": None,
                "revision": "rev-3",
                "action": "set",
                "changed_by": str(user.id),
            },
        )
        await consumer.handle(event)

        # No security.setting_changed event should exist (filter on event_type
        # in the payload so we don't match AuthService.register's own security
        # events).
        factory = app_sessions_on_test_connection
        async with factory() as session:
            await bind_tenant(session, tenant.id)
            rows = (
                (
                    await session.execute(
                        select(OutboxEvent).where(
                            OutboxEvent.aggregate_type == "security",
                            OutboxEvent.payload["event_type"].astext == "security.setting_changed",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_ignores_non_settings_changed_events(self, db) -> None:
        cache.clear()
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)

        put(tenant.id, "tenant", None, "pos.max_discount_pct", 10.0)

        consumer = SettingsConsumer.__new__(SettingsConsumer)
        consumer._bus = None  # type: ignore[assignment]
        consumer._running = False

        # Use a registered event type that is NOT "settings.changed" —
        # "test.schema" is a harmless test-only type that build_envelope
        # accepts and the consumer must ignore.
        event = _make_event(
            "test.schema",
            tenant.id,
            {"key": "pos.max_discount_pct"},
        )
        await consumer.handle(event)

        # Cache should NOT be invalidated (event type mismatch).
        assert cache.get(tenant.id, "tenant", None, "pos.max_discount_pct") == 10.0
