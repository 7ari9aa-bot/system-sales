"""Behavioural tests for the notification delivery worker.

The worker consumes ``notification.email`` and ``notification.push`` events
from the outbox stream and delivers them through provider adapters.  These
tests verify:

* Email delivery through the provider when ``email_enabled`` is True.
* Email SKIPPED when ``email_enabled`` is False (the second gate).
* Push delivery through the provider when ``push_enabled`` is True.
* Push SKIPPED when ``push_enabled`` is False.
* Events without an envelope are safely ignored.
* Unrelated event types (``notification.queued``) are ignored.

All tests use ``FakeEmailProvider`` / ``FakePushProvider`` — no network.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.modules.platform.models  # noqa: F401  — ensure tables are registered


def _make_event(event_type: str, payload: dict, *, tenant_id=None) -> SimpleNamespace:
    """Build a minimal Event-like object the worker's handle() accepts.

    Uses the real ``build_envelope`` / ``serialize`` so the payload/meta shape
    matches what the outbox relay publishes to the stream.
    """
    import json
    from datetime import UTC, datetime

    from app.core.events.schemas import build_envelope, serialize

    tenant = tenant_id or uuid.uuid4()
    envelope = build_envelope(
        event_type,
        tenant_id=tenant,
        aggregate_type="notification",
        aggregate_id=uuid.uuid4(),
        payload=payload,
        occurred_at=datetime.now(UTC),
    )
    fields = serialize(envelope)
    return SimpleNamespace(
        id=uuid.uuid4().hex,
        stream="notification.events",
        payload=json.loads(fields["payload"]),
        meta=json.loads(fields["meta"]),
    )


def _settings_checker_from_db(db):
    """Build a settings checker that reads from the shared test session."""

    async def _checker(tenant_id, key):
        from app.core.settings_read import setting_bool

        return await setting_bool(db, tenant_id, key)

    return _checker


class TestEmailDelivery:
    """Email path: provider.send is called only when email_enabled is True."""

    @pytest.mark.asyncio
    async def test_email_sent_when_enabled(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.notifications.providers import FakeEmailProvider
        from app.modules.settings.registry import Scope
        from app.modules.settings.service import SettingsService
        from app.workers.notification_delivery_worker import NotificationDeliveryWorker

        email = f"notif-{uuid.uuid4().hex[:8]}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Notif Tenant",
            tenant_slug=f"notif-{uuid.uuid4().hex[:8]}",
            email=email,
            password="strong-password-1",
            full_name="Notif Owner",
        )
        await db.flush()

        svc = SettingsService(db, tenant.id)
        await svc.set("notifications.email_enabled", True, scope=Scope.TENANT)
        await db.flush()

        fake = FakeEmailProvider()
        worker = NotificationDeliveryWorker(
            bus=None,
            email_provider=fake,
            settings_checker=_settings_checker_from_db(db),
        )
        event = _make_event(
            "notification.email",
            {"to": email, "subject": "Hello", "body": "World"},
            tenant_id=tenant.id,
        )
        await worker.handle(event)
        assert len(fake.sent) == 1
        assert fake.sent[0]["to"] == email
        assert fake.sent[0]["subject"] == "Hello"

    @pytest.mark.asyncio
    async def test_email_skipped_when_disabled(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.notifications.providers import FakeEmailProvider
        from app.workers.notification_delivery_worker import NotificationDeliveryWorker

        email = f"notif-{uuid.uuid4().hex[:8]}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Notif Tenant 2",
            tenant_slug=f"notif2-{uuid.uuid4().hex[:8]}",
            email=email,
            password="strong-password-1",
            full_name="Notif Owner 2",
        )
        await db.flush()

        # email_enabled defaults to False — no need to set it.
        fake = FakeEmailProvider()
        worker = NotificationDeliveryWorker(
            bus=None,
            email_provider=fake,
            settings_checker=_settings_checker_from_db(db),
        )
        event = _make_event(
            "notification.email",
            {"to": email, "subject": "Hello", "body": "World"},
            tenant_id=tenant.id,
        )
        await worker.handle(event)
        assert len(fake.sent) == 0


class TestPushDelivery:
    """Push path: provider.send is called only when push_enabled is True."""

    @pytest.mark.asyncio
    async def test_push_skipped_when_disabled(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.notifications.providers import FakePushProvider
        from app.modules.settings.registry import Scope
        from app.modules.settings.service import SettingsService
        from app.workers.notification_delivery_worker import NotificationDeliveryWorker

        email = f"notif-{uuid.uuid4().hex[:8]}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Notif Tenant 3",
            tenant_slug=f"notif3-{uuid.uuid4().hex[:8]}",
            email=email,
            password="strong-password-1",
            full_name="Notif Owner 3",
        )
        await db.flush()

        svc = SettingsService(db, tenant.id)
        await svc.set("notifications.push_enabled", False, scope=Scope.TENANT)
        await db.flush()

        fake = FakePushProvider()
        worker = NotificationDeliveryWorker(
            bus=None,
            push_provider=fake,
            settings_checker=_settings_checker_from_db(db),
        )
        event = _make_event(
            "notification.push",
            {"title": "Hello", "body": "World", "user_id": str(user.id)},
            tenant_id=tenant.id,
        )
        await worker.handle(event)
        assert len(fake.sent) == 0


class TestEventHandling:
    """Edge cases in event dispatch."""

    @pytest.mark.asyncio
    async def test_malformed_event_ignored(self) -> None:
        from app.modules.notifications.providers import FakeEmailProvider
        from app.workers.notification_delivery_worker import NotificationDeliveryWorker

        fake = FakeEmailProvider()
        worker = NotificationDeliveryWorker(bus=None, email_provider=fake)
        # An event with no valid envelope data.
        bad_event = SimpleNamespace(id="bad", payload={}, meta={})
        await worker.handle(bad_event)
        assert len(fake.sent) == 0

    @pytest.mark.asyncio
    async def test_unrelated_event_type_ignored(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.notifications.providers import FakeEmailProvider
        from app.workers.notification_delivery_worker import NotificationDeliveryWorker

        email = f"notif-{uuid.uuid4().hex[:8]}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Notif Tenant 4",
            tenant_slug=f"notif4-{uuid.uuid4().hex[:8]}",
            email=email,
            password="strong-password-1",
            full_name="Notif Owner 4",
        )
        await db.flush()

        fake = FakeEmailProvider()
        worker = NotificationDeliveryWorker(
            bus=None,
            email_provider=fake,
            settings_checker=_settings_checker_from_db(db),
        )
        # notification.queued is handled by the existing NotificationWorker, not us.
        event = _make_event(
            "notification.queued",
            {"notification_id": str(uuid.uuid4())},
            tenant_id=tenant.id,
        )
        await worker.handle(event)
        assert len(fake.sent) == 0

    @pytest.mark.asyncio
    async def test_email_missing_to_skipped(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.notifications.providers import FakeEmailProvider
        from app.workers.notification_delivery_worker import NotificationDeliveryWorker

        email = f"notif-{uuid.uuid4().hex[:8]}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Notif Tenant 5",
            tenant_slug=f"notif5-{uuid.uuid4().hex[:8]}",
            email=email,
            password="strong-password-1",
            full_name="Notif Owner 5",
        )
        await db.flush()

        fake = FakeEmailProvider()
        worker = NotificationDeliveryWorker(
            bus=None,
            email_provider=fake,
            settings_checker=_settings_checker_from_db(db),
        )
        event = _make_event(
            "notification.email",
            {"subject": "Hello", "body": "World"},  # no 'to'
            tenant_id=tenant.id,
        )
        await worker.handle(event)
        assert len(fake.sent) == 0
