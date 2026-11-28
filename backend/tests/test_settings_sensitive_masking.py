"""Tests for settings:read_sensitive masking (جولة 14, requirement 1).

A Manager (settings:read but NOT settings:read_sensitive) must see the value
of SENSITIVE settings masked as ``"******"`` in the read, history, and
override endpoints. An Owner (who has settings:read_sensitive) sees the real
value.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.settings.registry import Sensitivity, get_definition
from app.platform.settings.service import SettingsService

pytestmark = pytest.mark.asyncio


async def test_manager_sees_sensitive_value_masked_in_resolve(db: AsyncSession, tenant_ctx):
    """Manager without settings:read_sensitive sees masked value for SENSITIVE settings."""
    defn = get_definition("team.require_2fa")
    assert defn.sensitivity is Sensitivity.SENSITIVE

    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(
        "team.require_2fa",
        True,
        user_id=tenant_ctx.user.id,
        permissions=None,  # internal caller
        bypass_approval=True,
    )
    await db.flush()

    resolved = await svc.resolve("team.require_2fa")
    from app.platform.settings.router import _mask_if_sensitive

    masked = _mask_if_sensitive(defn, resolved.value, can_read_sensitive=False)
    assert masked == "******"

    unmasked = _mask_if_sensitive(defn, resolved.value, can_read_sensitive=True)
    assert unmasked is True


async def test_manager_sees_sensitive_value_masked_in_history(db: AsyncSession, tenant_ctx):
    """Manager sees masked values in settings history for SENSITIVE settings."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(
        "team.require_2fa",
        True,
        user_id=tenant_ctx.user.id,
        permissions=None,
        bypass_approval=True,
    )
    await db.flush()

    rows = await svc.history(key="team.require_2fa")
    assert len(rows) >= 1
    defn = get_definition("team.require_2fa")
    from app.platform.settings.router import _mask_if_sensitive

    for r in rows:
        if r.new_value:
            raw_new = r.new_value.get("v") if isinstance(r.new_value, dict) else r.new_value
            masked_new = _mask_if_sensitive(defn, raw_new, can_read_sensitive=False)
            assert masked_new == "******"
            unmasked_new = _mask_if_sensitive(defn, raw_new, can_read_sensitive=True)
            assert unmasked_new == raw_new


async def test_manager_sees_sensitive_value_masked_in_overrides(db: AsyncSession, tenant_ctx):
    """Manager sees masked values in override listing for SENSITIVE settings."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(
        "team.require_2fa",
        True,
        user_id=tenant_ctx.user.id,
        permissions=None,
        bypass_approval=True,
    )
    await db.flush()

    rows = await svc.list_overrides()
    sensitive_rows = [r for r in rows if r.key == "team.require_2fa"]
    assert len(sensitive_rows) == 1
    defn = get_definition("team.require_2fa")
    from app.platform.settings.router import _mask_if_sensitive

    raw = sensitive_rows[0].value.get("v")
    masked = _mask_if_sensitive(defn, raw, can_read_sensitive=False)
    assert masked == "******"
    unmasked = _mask_if_sensitive(defn, raw, can_read_sensitive=True)
    assert unmasked is True


async def test_non_sensitive_settings_are_not_masked(db: AsyncSession, tenant_ctx):
    """NORMAL settings are never masked, regardless of permission."""
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set(
        "pos.return_max_days",
        14,
        user_id=tenant_ctx.user.id,
        permissions=None,
    )
    await db.flush()

    resolved = await svc.resolve("pos.return_max_days")
    defn = get_definition("pos.return_max_days")
    assert defn.sensitivity is Sensitivity.NORMAL
    from app.platform.settings.router import _mask_if_sensitive

    val = _mask_if_sensitive(defn, resolved.value, can_read_sensitive=False)
    assert val == 14
