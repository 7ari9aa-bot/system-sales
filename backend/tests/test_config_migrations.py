"""Behavioural tests for the config migration framework.

Verifies that:
* Migrations run and transform data (key rename, value transform).
* The runner is idempotent (re-running is a no-op).
* The migration log records what was applied.
* ``latest_version`` returns the highest migration id.
"""

from __future__ import annotations

import uuid

import pytest

import app.core.model_registry  # noqa: F401 — complete table registration
import app.modules.platform.models  # noqa: F401 — ensure tables registered
from app.core.db import bind_tenant
from app.modules.settings.config_migrations import (
    MIGRATIONS,
    ConfigMigration,
    _rename_key,
    _transform_value,
    latest_version,
    run_pending,
)
from app.modules.settings.models import SettingMigrationLog, TenantSetting


def _uuid_hex() -> str:
    return uuid.uuid4().hex[:8]


async def _create_tenant(db) -> tuple:
    """Register a fresh tenant and return (user, tenant)."""
    from app.modules.identity.service import AuthService

    email = f"cmig-{_uuid_hex()}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Config Migration Tenant",
        tenant_slug=f"cmig-{_uuid_hex()}",
        email=email,
        password="strong-password-1",
        full_name="Migration Owner",
    )
    await db.flush()
    return user, tenant


async def _insert_override(db, tenant_id, key, value, scope="tenant", scope_id=None):
    """Insert a tenant_settings override directly."""
    row = TenantSetting(
        tenant_id=tenant_id,
        key=key,
        scope=scope,
        scope_id=scope_id,
        value={"v": value},
    )
    db.add(row)
    await db.flush()
    return row


class TestConfigMigrationFramework:
    """The runner applies migrations idempotently and logs them."""

    @pytest.mark.asyncio
    async def test_rename_key_migration(self, db) -> None:
        from sqlalchemy import select

        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)

        # Insert an override with the old key.
        await _insert_override(db, tenant.id, "pos.discount_cap", 50)
        await db.flush()

        # Define a temporary migration that renames the key.
        test_migrations = [
            ConfigMigration(
                id="999_test_rename",
                description="Rename pos.discount_cap → pos.max_discount (test)",
                apply=lambda s, t: _rename_key(s, t, "pos.discount_cap", "pos.max_discount"),
            ),
        ]

        # Monkeypatch MIGRATIONS.
        original = list(MIGRATIONS)
        MIGRATIONS.clear()
        MIGRATIONS.extend(test_migrations)
        try:
            applied = await run_pending(db, tenant.id, applied_by=user.id)
            await db.flush()

            assert applied == ["999_test_rename"]

            # The override should now have the new key.
            rows = (
                (
                    await db.execute(
                        select(TenantSetting).where(
                            TenantSetting.tenant_id == tenant.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].key == "pos.max_discount"
            assert rows[0].value == {"v": 50}

            # The migration log should have one row.
            log_rows = (
                (
                    await db.execute(
                        select(SettingMigrationLog).where(
                            SettingMigrationLog.tenant_id == tenant.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(log_rows) == 1
            assert log_rows[0].migration_id == "999_test_rename"
        finally:
            MIGRATIONS.clear()
            MIGRATIONS.extend(original)

    @pytest.mark.asyncio
    async def test_transform_value_migration(self, db) -> None:
        from sqlalchemy import select

        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)

        await _insert_override(db, tenant.id, "pos.tax_rate", "14")
        await db.flush()

        # Define a migration that transforms the value from string to number.
        test_migrations = [
            ConfigMigration(
                id="998_test_transform",
                description="Convert pos.tax_rate from string to number (test)",
                apply=lambda s, t: _transform_value(
                    s, t, "pos.tax_rate", lambda v: float(v) if isinstance(v, str) else v
                ),
            ),
        ]

        original = list(MIGRATIONS)
        MIGRATIONS.clear()
        MIGRATIONS.extend(test_migrations)
        try:
            applied = await run_pending(db, tenant.id, applied_by=user.id)
            await db.flush()

            assert applied == ["998_test_transform"]

            rows = (
                (
                    await db.execute(
                        select(TenantSetting).where(
                            TenantSetting.tenant_id == tenant.id,
                            TenantSetting.key == "pos.tax_rate",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].value == {"v": 14.0}
        finally:
            MIGRATIONS.clear()
            MIGRATIONS.extend(original)

    @pytest.mark.asyncio
    async def test_idempotent_rerun_is_noop(self, db) -> None:
        from sqlalchemy import select

        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)

        await _insert_override(db, tenant.id, "pos.old_key", "hello")
        await db.flush()

        test_migrations = [
            ConfigMigration(
                id="997_test_idempotent",
                description="Rename pos.old_key → pos.new_key (test)",
                apply=lambda s, t: _rename_key(s, t, "pos.old_key", "pos.new_key"),
            ),
        ]

        original = list(MIGRATIONS)
        MIGRATIONS.clear()
        MIGRATIONS.extend(test_migrations)
        try:
            # First run — applies the migration.
            first = await run_pending(db, tenant.id, applied_by=user.id)
            await db.flush()
            assert first == ["997_test_idempotent"]

            # Second run — no-op, no new log rows.
            second = await run_pending(db, tenant.id, applied_by=user.id)
            await db.flush()
            assert second == []

            log_rows = (
                (
                    await db.execute(
                        select(SettingMigrationLog).where(
                            SettingMigrationLog.tenant_id == tenant.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(log_rows) == 1
        finally:
            MIGRATIONS.clear()
            MIGRATIONS.extend(original)

    @pytest.mark.asyncio
    async def test_latest_version(self, db) -> None:
        # With the default MIGRATIONS list (may be empty), latest_version
        # returns the last migration id or "0".
        if MIGRATIONS:
            assert latest_version() == MIGRATIONS[-1].id
        else:
            assert latest_version() == "0"

    @pytest.mark.asyncio
    async def test_empty_migrations_is_noop(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)

        original = list(MIGRATIONS)
        MIGRATIONS.clear()
        try:
            applied = await run_pending(db, tenant.id, applied_by=user.id)
            await db.flush()
            assert applied == []
        finally:
            MIGRATIONS.clear()
            MIGRATIONS.extend(original)
