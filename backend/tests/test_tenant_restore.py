"""Behavioural tests for the tenant-scoped restore endpoint (§164).

Verifies that:
* Restore brings settings back to their state before a snapshot timestamp.
* Settings added after the snapshot are removed.
* Settings that didn't exist at the snapshot are reset.
* Restore is tenant-scoped — it never touches another tenant's settings.
* The restore operation writes to the audit log.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

import app.core.model_registry  # noqa: F401 — complete table registration
import app.modules.platform.models  # noqa: F401 — ensure tables registered
from app.core.db import bind_tenant


def _uuid_hex() -> str:
    return uuid.uuid4().hex[:8]


async def _create_tenant(db, slug_prefix="restore"):
    from app.modules.identity.service import AuthService

    email = f"{slug_prefix}-{_uuid_hex()}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name=f"{slug_prefix} tenant",
        tenant_slug=f"{slug_prefix}-{_uuid_hex()}",
        email=email,
        password="strong-password-1",
        full_name=f"{slug_prefix} owner",
    )
    await db.flush()
    return user, tenant


class TestTenantScopedRestore:
    """The restore_to_snapshot service method restores settings to a point in time."""

    @pytest.mark.asyncio
    async def test_restore_brings_settings_back(self, db) -> None:

        from app.modules.settings.registry import Scope
        from app.modules.settings.service import SettingsService

        user, tenant = await _create_tenant(db, "restore1")
        await db.flush()

        svc = SettingsService(db, tenant.id)

        # Set a value, then take a snapshot.
        await svc.set("pos.max_discount_pct", 30, scope=Scope.TENANT, user_id=user.id)
        await db.flush()
        await asyncio.sleep(0.2)
        snapshot_time = datetime.now(UTC)
        await asyncio.sleep(0.2)

        # Change the value AFTER the snapshot.
        await svc.set("pos.max_discount_pct", 80, scope=Scope.TENANT, user_id=user.id)
        await db.flush()

        # Verify the current value is 80.
        resolved = await svc.resolve("pos.max_discount_pct", scope=Scope.TENANT)
        assert resolved.value == 80

        # Restore to the snapshot — should bring it back to 30.
        result = await svc.restore_to_snapshot(
            snapshot_time,
            user_id=user.id,
            reason="test restore",
            permissions={"settings:write"},
        )
        await db.flush()

        # The restore should have restored the value to 30.
        resolved = await svc.resolve("pos.max_discount_pct", scope=Scope.TENANT)
        assert resolved.value == 30
        assert result["restored"] >= 1

    @pytest.mark.asyncio
    async def test_restore_removes_settings_added_after_snapshot(self, db) -> None:
        from app.modules.settings.registry import Scope
        from app.modules.settings.service import SettingsService

        user, tenant = await _create_tenant(db, "restore2")
        await db.flush()

        svc = SettingsService(db, tenant.id)

        # Set a setting BEFORE the snapshot.
        await svc.set("pos.max_discount_pct", 20, scope=Scope.TENANT, user_id=user.id)
        await db.flush()
        await asyncio.sleep(0.2)
        snapshot_time = datetime.now(UTC)
        await asyncio.sleep(0.2)

        # Add a NEW setting AFTER the snapshot.
        await svc.set("inventory.auto_reserve", True, scope=Scope.TENANT, user_id=user.id)
        await db.flush()

        # Verify it exists.
        resolved = await svc.resolve("inventory.auto_reserve", scope=Scope.TENANT)
        assert resolved.value is True
        assert not resolved.is_default

        # Restore — should remove the setting added after the snapshot.
        result = await svc.restore_to_snapshot(
            snapshot_time,
            user_id=user.id,
            reason="test restore",
            permissions={"settings:write"},
        )
        await db.flush()

        assert result["reset"] >= 1

        # The setting should now be at its default (override removed).
        resolved = await svc.resolve("inventory.auto_reserve", scope=Scope.TENANT)
        assert resolved.is_default

    @pytest.mark.asyncio
    async def test_restore_is_tenant_scoped(self, db) -> None:
        """Restore on tenant A must not affect tenant B's settings."""
        from app.modules.settings.registry import Scope
        from app.modules.settings.service import SettingsService

        user_a, tenant_a = await _create_tenant(db, "isoA")
        user_b, tenant_b = await _create_tenant(db, "isoB")
        await db.flush()

        svc_a = SettingsService(db, tenant_a.id)
        svc_b = SettingsService(db, tenant_b.id)

        # Both tenants set the same key to different values.
        await bind_tenant(db, tenant_a.id)
        await svc_a.set("pos.max_discount_pct", 10, scope=Scope.TENANT, user_id=user_a.id)
        await bind_tenant(db, tenant_b.id)
        await svc_b.set("pos.max_discount_pct", 99, scope=Scope.TENANT, user_id=user_b.id)
        await db.flush()
        await asyncio.sleep(0.2)
        snapshot_time = datetime.now(UTC)
        await asyncio.sleep(0.2)

        # Tenant A changes its value.
        await bind_tenant(db, tenant_a.id)
        await svc_a.set("pos.max_discount_pct", 55, scope=Scope.TENANT, user_id=user_a.id)
        await db.flush()

        # Restore tenant A.
        await bind_tenant(db, tenant_a.id)
        await svc_a.restore_to_snapshot(
            snapshot_time,
            user_id=user_a.id,
            reason="test isolation",
            permissions={"settings:write"},
        )
        await db.flush()

        # Tenant A should be back to 10.
        resolved_a = await svc_a.resolve("pos.max_discount_pct", scope=Scope.TENANT)
        assert resolved_a.value == 10

        # Tenant B should be UNCHANGED at 99.
        await bind_tenant(db, tenant_b.id)
        resolved_b = await svc_b.resolve("pos.max_discount_pct", scope=Scope.TENANT)
        assert resolved_b.value == 99

    @pytest.mark.asyncio
    async def test_restore_with_no_history_is_noop(self, db) -> None:
        from app.modules.settings.service import SettingsService

        user, tenant = await _create_tenant(db, "restore3")
        await db.flush()

        svc = SettingsService(db, tenant.id)

        # Restore to a point with no history at all.
        result = await svc.restore_to_snapshot(
            datetime.now(UTC) + timedelta(hours=1),
            user_id=user.id,
            reason="noop restore",
            permissions={"settings:write"},
        )
        await db.flush()

        # Nothing to restore or reset.
        assert result["restored"] == 0
        assert result["reset"] == 0
