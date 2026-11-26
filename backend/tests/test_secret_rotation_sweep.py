"""Behavioural tests for the secret rotation scheduler sweep.

The sweep (``secret_rotation_sweep``) is the scheduler job that calls
``due_secret_references`` and creates a notification per owner when a key
is past its rotation window.  These tests verify:

* The sweep creates notifications for owners when secrets are overdue.
* The sweep is a no-op when rotation is disabled (``api_key_rotation_days = 0``).
* The sweep is a no-op when no secrets are overdue.
* Notifications are deduped per day (same dedup key → one row, not many).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

import app.core.model_registry  # noqa: F401 — complete table registration (FK chains)
import app.modules.platform.models  # noqa: F401 — ensure tables registered


def _uuid_hex() -> str:
    return uuid.uuid4().hex[:8]


async def _create_secret_ref(
    db,
    tenant_id: uuid.UUID,
    *,
    provider: str = "openai",
    vault_key: str = "openai_api_key",
    rotated_at: datetime | None,
) -> uuid.UUID:
    """Insert a SecretReference row directly for the sweep to find."""
    from sqlalchemy import text

    ref_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO secret_references "
            "(id, tenant_id, scope, provider, vault_key, status, version, rotated_at) "
            "VALUES (:id, :tid, 'tenant', :provider, :vault_key, 'active', 1, :rotated_at)"
        ),
        {
            "id": ref_id,
            "tid": tenant_id,
            "provider": provider,
            "vault_key": vault_key,
            "rotated_at": rotated_at,
        },
    )
    return ref_id


class TestSecretRotationSweep:
    """The scheduler handler creates notifications when keys are overdue."""

    @pytest.mark.asyncio
    async def test_sweep_notifies_owners_when_overdue(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.notifications.models import Notification

        email = f"sweep-{_uuid_hex()}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Sweep Tenant",
            tenant_slug=f"sweep-{_uuid_hex()}",
            email=email,
            password="strong-password-1",
            full_name="Sweep Owner",
        )
        await db.flush()

        # Insert a secret that is 100 days old (default window = 90).
        await _create_secret_ref(db, tenant.id, rotated_at=datetime.now(UTC) - timedelta(days=100))
        await db.flush()

        from app.workers.scheduler_worker import _handle_secret_rotation_sweep

        result = await _handle_secret_rotation_sweep(db, tenant.id, {})
        await db.flush()

        assert result["due"] == 1
        assert result["notifications"] == 1

        # The notification should exist in the DB for the owner.
        from sqlalchemy import select

        notifs = (
            (
                await db.execute(
                    select(Notification).where(
                        Notification.tenant_id == tenant.id,
                        Notification.user_id == user.id,
                        Notification.kind == "security",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifs) == 1
        assert "openai" in notifs[0].body

    @pytest.mark.asyncio
    async def test_sweep_noop_when_rotation_disabled(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.settings.registry import Scope
        from app.modules.settings.service import SettingsService

        email = f"sweep-{_uuid_hex()}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Sweep Tenant 2",
            tenant_slug=f"sweep2-{_uuid_hex()}",
            email=email,
            password="strong-password-1",
            full_name="Sweep Owner 2",
        )
        await db.flush()

        # Disable rotation.
        svc = SettingsService(db, tenant.id)
        # security.* is APPROVAL_REQUIRED, so a plain set() opens an approval and writes nothing;
        # this test is about the sweep, so the value is written the way an approved change lands.
        await svc.set(
            "security.api_key_rotation_days", 0, scope=Scope.TENANT, bypass_approval=True
        )
        await db.flush()

        # Even an ancient secret should not be flagged.
        await _create_secret_ref(db, tenant.id, rotated_at=datetime.now(UTC) - timedelta(days=365))
        await db.flush()

        from app.workers.scheduler_worker import _handle_secret_rotation_sweep

        result = await _handle_secret_rotation_sweep(db, tenant.id, {})
        assert result["due"] == 0

    @pytest.mark.asyncio
    async def test_sweep_noop_when_no_overdue(self, db) -> None:
        from app.modules.identity.service import AuthService

        email = f"sweep-{_uuid_hex()}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Sweep Tenant 3",
            tenant_slug=f"sweep3-{_uuid_hex()}",
            email=email,
            password="strong-password-1",
            full_name="Sweep Owner 3",
        )
        await db.flush()

        # Fresh secret — 1 day old, well within the 90-day window.
        await _create_secret_ref(db, tenant.id, rotated_at=datetime.now(UTC) - timedelta(days=1))
        await db.flush()

        from app.workers.scheduler_worker import _handle_secret_rotation_sweep

        result = await _handle_secret_rotation_sweep(db, tenant.id, {})
        assert result["due"] == 0

    @pytest.mark.asyncio
    async def test_sweep_dedupes_per_day(self, db) -> None:
        from app.modules.identity.service import AuthService
        from app.modules.notifications.models import Notification

        email = f"sweep-{_uuid_hex()}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Sweep Tenant 4",
            tenant_slug=f"sweep4-{_uuid_hex()}",
            email=email,
            password="strong-password-1",
            full_name="Sweep Owner 4",
        )
        await db.flush()

        await _create_secret_ref(db, tenant.id, rotated_at=datetime.now(UTC) - timedelta(days=100))
        await db.flush()

        from app.workers.scheduler_worker import _handle_secret_rotation_sweep

        # Run the sweep twice — the dedup key carries the date, so the second
        # run must not create a duplicate notification.
        await _handle_secret_rotation_sweep(db, tenant.id, {})
        await db.flush()
        await _handle_secret_rotation_sweep(db, tenant.id, {})
        await db.flush()

        from sqlalchemy import select

        notifs = (
            (
                await db.execute(
                    select(Notification).where(
                        Notification.tenant_id == tenant.id,
                        Notification.user_id == user.id,
                        Notification.kind == "security",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifs) == 1
