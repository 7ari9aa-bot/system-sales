"""Tests for extended auditing — source tracking and filtered search (§174).

Covers:
* Every history row records a ``source`` (api, preset, restore, …).
* The ``history`` method supports filtering by source, action,
  changed_by, and time range.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.settings.service import SettingsService


def _uuid_hex() -> str:
    return uuid.uuid4().hex[:8]


async def _create_tenant(db: AsyncSession, slug: str = "aud"):
    """Register a fresh tenant and return (user, tenant)."""
    from app.platform.identity.service import AuthService

    email = f"{slug}-{_uuid_hex()}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name=f"{slug} tenant",
        tenant_slug=f"{slug}-{_uuid_hex()}",
        email=email,
        password="strong-password-1",
        full_name=f"{slug} owner",
    )
    await db.flush()
    return user, tenant


async def _create_second_admin(db: AsyncSession, tenant, slug: str = "rev"):
    """Add a second admin (owner role) to an existing tenant."""
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.platform.identity.models import Role, TenantUser, User

    user = User(
        email=f"{slug}-{_uuid_hex()}@test.local",
        password_hash=hash_password("strong-password-1"),
        full_name="Reviewer",
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.code == "owner"))).scalar_one()
    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role_id=role.id, is_default=False))
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# Source tracking
# ---------------------------------------------------------------------------


class TestSourceTracking:
    pytestmark = pytest.mark.asyncio

    async def test_api_set_records_source_api(self, db) -> None:
        user, tenant = await _create_tenant(db, "api")
        svc = SettingsService(db, tenant.id)
        await svc.set("pos.max_discount_pct", 10.0, user_id=user.id)
        rows = await svc.history(key="pos.max_discount_pct")
        assert len(rows) >= 1
        assert rows[0].source == "api"

    async def test_preset_apply_records_source_preset(self, db) -> None:
        user, tenant = await _create_tenant(db, "preset")
        svc = SettingsService(db, tenant.id)
        await svc.apply_preset("physical_retail", user_id=user.id)
        rows = await svc.history(source="preset", limit=200)
        assert len(rows) > 0
        assert all(r.source == "preset" for r in rows)

    async def test_rollback_records_source_rollback(self, db) -> None:
        user, tenant = await _create_tenant(db, "rbk")
        svc = SettingsService(db, tenant.id)
        await svc.set("pos.max_discount_pct", 10.0, user_id=user.id)
        await svc.set("pos.max_discount_pct", 20.0, user_id=user.id)
        hist = await svc.history(key="pos.max_discount_pct")
        # hist[0] is newest (20.0), hist[1] is the original (10.0) — rollback to 10.0
        await svc.rollback(hist[1].id, user_id=user.id)
        rows = await svc.history(key="pos.max_discount_pct", source="rollback")
        assert len(rows) >= 1
        assert rows[0].source == "rollback"

    async def test_restore_records_source_restore(self, db) -> None:
        import asyncio

        user, tenant = await _create_tenant(db, "rst")
        svc = SettingsService(db, tenant.id)
        await svc.set("pos.max_discount_pct", 10.0, user_id=user.id)
        snapshot_time = datetime.now(UTC) + timedelta(seconds=1)
        await asyncio.sleep(2)  # ensure the next write is after the snapshot point
        await svc.set("pos.max_discount_pct", 20.0, user_id=user.id)
        await svc.restore_to_snapshot(snapshot_time, user_id=user.id, reason="test")
        rows = await svc.history(source="restore", limit=200)
        assert len(rows) >= 1
        assert all(r.source == "restore" for r in rows)

    async def test_change_request_records_source_change_request(self, db) -> None:
        submitter, tenant = await _create_tenant(db, "cr")
        reviewer = await _create_second_admin(db, tenant, "cr")
        svc = SettingsService(db, tenant.id)
        req = await svc.create_change_request(
            {"security.require_strong_passwords": False},
            user_id=submitter.id,
        )
        await svc.approve_change_request(req.id, reviewer_id=reviewer.id)
        rows = await svc.history(source="change_request")
        assert len(rows) >= 1
        assert all(r.source == "change_request" for r in rows)


# ---------------------------------------------------------------------------
# Filtered search
# ---------------------------------------------------------------------------


class TestFilteredSearch:
    pytestmark = pytest.mark.asyncio

    async def _seed(self, db) -> tuple:
        user, tenant = await _create_tenant(db, "seed")
        svc = SettingsService(db, tenant.id)
        await svc.set("pos.max_discount_pct", 10.0, user_id=user.id)
        await svc.set("pos.require_customer", True, user_id=user.id)
        await svc.apply_preset("physical_retail", user_id=user.id)
        return user, tenant

    async def test_filter_by_source(self, db) -> None:
        _, tenant = await self._seed(db)
        svc = SettingsService(db, tenant.id)
        api_rows = await svc.history(source="api")
        assert all(r.source == "api" for r in api_rows)
        preset_rows = await svc.history(source="preset")
        assert all(r.source == "preset" for r in preset_rows)
        assert len(api_rows) > 0
        assert len(preset_rows) > 0

    async def test_filter_by_key(self, db) -> None:
        _, tenant = await self._seed(db)
        svc = SettingsService(db, tenant.id)
        rows = await svc.history(key="pos.max_discount_pct")
        assert all(r.key == "pos.max_discount_pct" for r in rows)

    async def test_filter_by_action(self, db) -> None:
        _, tenant = await self._seed(db)
        svc = SettingsService(db, tenant.id)
        rows = await svc.history(action="set")
        assert all(r.action == "set" for r in rows)

    async def test_filter_by_changed_by(self, db) -> None:
        user, tenant = await self._seed(db)
        svc = SettingsService(db, tenant.id)
        rows = await svc.history(changed_by=user.id)
        assert all(r.changed_by == user.id for r in rows)

    async def test_filter_by_time_range(self, db) -> None:
        _, tenant = await self._seed(db)
        svc = SettingsService(db, tenant.id)
        now = datetime.now(UTC)
        rows = await svc.history(
            since=now - timedelta(hours=1),
            until=now + timedelta(seconds=10),
        )
        assert len(rows) > 0
        future = await svc.history(since=now + timedelta(hours=1))
        assert len(future) == 0
