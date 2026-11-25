"""Tests for optimistic concurrency in SettingsService.set() (جولة 14, requirement 3).

The expected_history_id check happens AFTER the FOR UPDATE lock, so a stale
history id is correctly rejected with ConflictError. Also tests that
expected_history_id is supported in bulk_set and that resolve returns
latest_history_id.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio


async def test_stale_expected_history_id_raises_conflict(db: AsyncSession, tenant_ctx):
    """A stale expected_history_id is rejected with ConflictError (§81)."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    # Write a value
    await svc.set(
        "pos.return_max_days",
        14,
        user_id=tenant_ctx.user.id,
        permissions=None,
    )
    await db.flush()

    # Capture the history id
    history = await svc.history(key="pos.return_max_days")
    first_history_id = history[0].id

    # Write a new value (history advances)
    await svc.set(
        "pos.return_max_days",
        21,
        user_id=tenant_ctx.user.id,
        permissions=None,
    )
    await db.flush()

    # Now try to write with the OLD history id → 409
    with pytest.raises(ConflictError):
        await svc.set(
            "pos.return_max_days",
            30,
            user_id=tenant_ctx.user.id,
            permissions=None,
            expected_history_id=first_history_id,
        )


async def test_current_expected_history_id_succeeds(db: AsyncSession, tenant_ctx):
    """The latest expected_history_id allows the write to proceed."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(
        "pos.return_max_days",
        14,
        user_id=tenant_ctx.user.id,
        permissions=None,
    )
    await db.flush()

    history = await svc.history(key="pos.return_max_days")
    current_id = history[0].id

    # Write with the current history id — should succeed
    row = await svc.set(
        "pos.return_max_days",
        21,
        user_id=tenant_ctx.user.id,
        permissions=None,
        expected_history_id=current_id,
    )
    assert row.value.get("v") == 21


async def test_expected_history_id_in_bulk_set(db: AsyncSession, tenant_ctx):
    """bulk_set passes per-key expected_history_id to set()."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.bulk_set(
        {"pos.return_max_days": 14, "inventory.dead_stock_days": 30},
        user_id=tenant_ctx.user.id,
        permissions=None,
    )
    await db.flush()

    h1 = await svc.history(key="pos.return_max_days")
    h2 = await svc.history(key="inventory.dead_stock_days")
    expected_ids = {
        "pos.return_max_days": h1[0].id,
        "inventory.dead_stock_days": h2[0].id,
    }

    # Bulk set with correct expected ids — should succeed
    await svc.bulk_set(
        {"pos.return_max_days": 21, "inventory.dead_stock_days": 45},
        user_id=tenant_ctx.user.id,
        permissions=None,
        expected_history_ids=expected_ids,
    )
    await db.flush()

    r1 = await svc.resolve("pos.return_max_days")
    r2 = await svc.resolve("inventory.dead_stock_days")
    assert r1.value == 21
    assert r2.value == 45

    # Bulk set with stale expected id — should get 409
    with pytest.raises(ConflictError):
        await svc.bulk_set(
            {"pos.return_max_days": 30, "inventory.dead_stock_days": 60},
            user_id=tenant_ctx.user.id,
            permissions=None,
            expected_history_ids=expected_ids,
        )


async def test_latest_history_id_returned_in_resolve(db: AsyncSession, tenant_ctx):
    """resolve_many returns latest_history_id for each key."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(
        "pos.return_max_days",
        14,
        user_id=tenant_ctx.user.id,
        permissions=None,
    )
    await db.flush()

    resolved = await svc.resolve_many(["pos.return_max_days"])
    assert resolved["pos.return_max_days"].latest_history_id is not None

    # No history for a setting never written
    resolved2 = await svc.resolve_many(["inventory.dead_stock_days"])
    assert resolved2["inventory.dead_stock_days"].latest_history_id is None
