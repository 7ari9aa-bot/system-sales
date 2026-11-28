"""Behavioural tests for ``security.api_key_rotation_days`` wiring.

The setting controls how long a secret may live before the system flags it as
due for rotation.  These tests exercise the real functions in
``app.core.api_key_rotation`` — no source inspection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


class TestIsRotationDue:
    """Unit tests for the pure rotation-check logic (no DB needed)."""

    def test_zero_days_disables_rotation(self) -> None:
        from app.core.api_key_rotation import is_rotation_due

        now = datetime.now(UTC)
        assert is_rotation_due(now - timedelta(days=365), 0, now=now) is False

    def test_never_rotated_is_due(self) -> None:
        from app.core.api_key_rotation import is_rotation_due

        assert is_rotation_due(None, 90) is True

    def test_never_rotated_but_disabled_is_not_due(self) -> None:
        from app.core.api_key_rotation import is_rotation_due

        assert is_rotation_due(None, 0) is False

    def test_within_window_not_due(self) -> None:
        from app.core.api_key_rotation import is_rotation_due

        now = datetime.now(UTC)
        rotated = now - timedelta(days=30)
        assert is_rotation_due(rotated, 90, now=now) is False

    def test_past_window_is_due(self) -> None:
        from app.core.api_key_rotation import is_rotation_due

        now = datetime.now(UTC)
        rotated = now - timedelta(days=91)
        assert is_rotation_due(rotated, 90, now=now) is True

    def test_exactly_at_boundary_not_due(self) -> None:
        from app.core.api_key_rotation import is_rotation_due

        now = datetime.now(UTC)
        rotated = now - timedelta(days=90)
        # Exactly 90 days — not STRICTLY greater, so not due yet.
        assert is_rotation_due(rotated, 90, now=now) is False

    def test_naive_rotated_at_treated_as_utc(self) -> None:
        from app.core.api_key_rotation import is_rotation_due

        now = datetime.now(UTC)
        rotated_naive = (now - timedelta(days=100)).replace(tzinfo=None)
        assert is_rotation_due(rotated_naive, 90, now=now) is True


class TestResolveRotationDays:
    """Tests that the setting is actually read from the database."""

    @pytest.mark.asyncio
    async def test_default_when_no_override(self, db) -> None:
        from app.core.api_key_rotation import resolve_rotation_days
        from app.platform.identity.service import AuthService

        email = f"rot-{uuid_hex()}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Rot Tenant",
            tenant_slug=f"rot-{uuid_hex()}",
            email=email,
            password="strong-password-1",
            full_name="Rot Owner",
        )
        await db.flush()
        days = await resolve_rotation_days(db, tenant.id)
        assert days == 90  # registry default

    @pytest.mark.asyncio
    async def test_override_is_read(self, db) -> None:
        from app.core.api_key_rotation import resolve_rotation_days
        from app.platform.identity.service import AuthService
        from app.platform.settings.registry import Scope
        from app.platform.settings.service import SettingsService

        email = f"rot-{uuid_hex()}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Rot Tenant 2",
            tenant_slug=f"rot2-{uuid_hex()}",
            email=email,
            password="strong-password-1",
            full_name="Rot Owner 2",
        )
        await db.flush()
        svc = SettingsService(db, tenant.id)
        # Approval-gated (§172): the write a reviewer-approved change request performs is
        # `bypass_approval=True`. This test is about the READ path, not the gate.
        await svc.set(
            "security.api_key_rotation_days", 30, scope=Scope.TENANT, bypass_approval=True
        )
        await db.flush()
        days = await resolve_rotation_days(db, tenant.id)
        assert days == 30

    @pytest.mark.asyncio
    async def test_check_secret_rotation_respects_setting(self, db) -> None:
        from app.core.api_key_rotation import check_secret_rotation
        from app.platform.identity.service import AuthService
        from app.platform.settings.registry import Scope
        from app.platform.settings.service import SettingsService

        email = f"rot-{uuid_hex()}@test.local"
        user, tenant = await AuthService.register(
            db,
            tenant_name="Rot Tenant 3",
            tenant_slug=f"rot3-{uuid_hex()}",
            email=email,
            password="strong-password-1",
            full_name="Rot Owner 3",
        )
        await db.flush()
        now = datetime.now(UTC)

        # Default 90 days — 30 days old is not due.
        assert (
            await check_secret_rotation(db, tenant.id, rotated_at=now - timedelta(days=30)) is False
        )
        # 100 days old IS due.
        assert (
            await check_secret_rotation(db, tenant.id, rotated_at=now - timedelta(days=100)) is True
        )

        # Set to 0 → disabled.
        svc = SettingsService(db, tenant.id)
        await svc.set("security.api_key_rotation_days", 0, scope=Scope.TENANT, bypass_approval=True)
        await db.flush()
        assert (
            await check_secret_rotation(db, tenant.id, rotated_at=now - timedelta(days=365))
            is False
        )


def uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex[:8]
