"""Tests for advanced presets: composition (extends), dry-run preview, atomic apply.

Verifies:
* ``resolve_preset`` merges parent values with child overrides.
* ``preset_chain`` returns the inheritance chain root → child.
* A cycle in ``extends`` raises at resolution time.
* ``preview_preset`` shows the diff (changed vs unchanged) without writing.
* ``apply_preset`` writes all keys atomically and records an audit row.
* Existing flat ``PRESETS`` dict is backward-compatible.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401 — complete table registration
from app.core.db import bind_tenant
from app.platform.settings.presets import (
    PRESET_DEFS,
    PRESETS,
    preset_chain,
    resolve_preset,
)
from app.platform.settings.service import SettingsService

OWNER = {"settings:write", "settings:read"}


def _uuid_hex() -> str:
    return uuid.uuid4().hex[:8]


async def _create_tenant(db):
    from app.platform.identity.service import AuthService

    email = f"ap-{_uuid_hex()}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Advanced Preset Tenant",
        tenant_slug=f"ap-{_uuid_hex()}",
        email=email,
        password="strong-password-1",
        full_name="Preset Owner",
    )
    await db.flush()
    return user, tenant


# ------------------------------------------------------------------ composition


class TestPresetComposition:
    """Preset extends preset: parent values merged, child overrides."""

    def test_ecmerce_inherits_physical_retail_values(self) -> None:
        merged = resolve_preset("ecommerce")
        # From physical_retail (parent):
        assert merged["business.type"] == "retail"
        assert merged["pos.allow_hold_cart"] is True
        assert merged["print.paper_width"] == "80mm"
        # Overridden by ecommerce:
        assert merged["pos.require_customer"] is True
        assert merged["inventory.auto_reserve"] is True

    def test_enterprise_inherits_omnichannel_and_physical_retail(self) -> None:
        merged = resolve_preset("enterprise")
        # Root (physical_retail):
        assert merged["business.type"] == "retail"
        # Middle (omnichannel):
        assert merged["inventory.auto_reserve"] is True
        assert merged["orders.reserve_on"] == "create"
        # Leaf (enterprise):
        assert merged["pos.max_discount_pct"] == 10.0
        assert merged["purchasing.approval_required"] is True

    def test_apparel_ground_shop_inherits_physical_retail(self) -> None:
        merged = resolve_preset("apparel_ground_shop")
        # From parent:
        assert merged["pos.allow_hold_cart"] is True
        assert merged["pos.return_max_days"] == 30
        # Own:
        assert merged["business.vertical"] == "apparel"
        assert merged["capability.variant_matrix"] is True

    def test_preset_chain_is_root_to_child(self) -> None:
        assert preset_chain("enterprise") == [
            "physical_retail",
            "omnichannel",
            "enterprise",
        ]
        assert preset_chain("physical_retail") == ["physical_retail"]

    def test_flat_presets_dict_is_backward_compatible(self) -> None:
        """PRESETS[name] is the fully merged dict, same as resolve_preset(name)."""
        for name in PRESETS:
            assert PRESETS[name] == resolve_preset(name)

    def test_extends_field_is_set_on_composable_presets(self) -> None:
        assert PRESET_DEFS["ecommerce"].extends == "physical_retail"
        assert PRESET_DEFS["omnichannel"].extends == "physical_retail"
        assert PRESET_DEFS["enterprise"].extends == "omnichannel"
        assert PRESET_DEFS["apparel_ground_shop"].extends == "physical_retail"
        assert PRESET_DEFS["physical_retail"].extends is None

    def test_every_preset_key_is_a_real_registry_setting(self) -> None:
        from app.platform.settings.registry import REGISTRY

        for name, values in PRESETS.items():
            for key in values:
                assert key in REGISTRY, f"{name}: {key} not in registry"

    def test_resolving_unknown_preset_raises(self) -> None:
        with pytest.raises(KeyError):
            resolve_preset("nonexistent")

    def test_cycle_detection_raises(self) -> None:
        """A cycle in extends is a programming error caught at resolution."""
        from app.platform.settings.presets import _PRESET_DEFS, PresetDef, _resolve_preset_values

        # Temporarily add a cycle.
        _PRESET_DEFS["__a"] = PresetDef(name="__a", values={}, extends="__b")
        _PRESET_DEFS["__b"] = PresetDef(name="__b", values={}, extends="__a")
        try:
            with pytest.raises(ValueError, match="cycle"):
                _resolve_preset_values("__a")
        finally:
            del _PRESET_DEFS["__a"]
            del _PRESET_DEFS["__b"]


# ------------------------------------------------------------------ dry-run preview


class TestPresetPreview:
    """``preview_preset`` shows what would change without writing."""

    @pytest.mark.asyncio
    async def test_preview_shows_all_keys_as_changes_on_fresh_tenant(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        result = await svc.preview_preset("physical_retail")
        assert result["preset"] == "physical_retail"
        assert result["chain"] == ["physical_retail"]
        assert result["total_keys"] == len(PRESETS["physical_retail"])
        # On a fresh tenant every value is the registry default; a "change" is
        # a key whose default differs from the preset's target.  The rest are
        # "unchanged" because the default already matches the preset value.
        assert len(result["changes"]) + result["unchanged_count"] == result["total_keys"]
        # Each change has the required fields.
        if result["changes"]:
            ch = result["changes"][0]
            assert "key" in ch
            assert "current_value" in ch
            assert "target_value" in ch
            assert "current_scope" in ch
            assert "is_default" in ch

    @pytest.mark.asyncio
    async def test_preview_shows_unchanged_after_apply(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        # Apply the preset first.
        await svc.apply_preset("physical_retail", user_id=user.id, permissions=OWNER)
        await db.flush()
        # Preview again: everything should be unchanged.
        result = await svc.preview_preset("physical_retail")
        assert result["unchanged_count"] == result["total_keys"]
        assert len(result["changes"]) == 0

    @pytest.mark.asyncio
    async def test_preview_shows_partial_diff(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        # Apply physical_retail.
        await svc.apply_preset("physical_retail", user_id=user.id, permissions=OWNER)
        await db.flush()
        # Change one key.
        await svc.set("pos.return_max_days", 7, user_id=user.id, permissions=OWNER)
        await db.flush()
        # Preview: one key differs.
        result = await svc.preview_preset("physical_retail")
        changed_keys = [c["key"] for c in result["changes"]]
        assert "pos.return_max_days" in changed_keys
        # The changed entry shows current=7, target=30.
        ch = next(c for c in result["changes"] if c["key"] == "pos.return_max_days")
        assert ch["current_value"] == 7
        assert ch["target_value"] == 30

    @pytest.mark.asyncio
    async def test_preview_does_not_write(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        await svc.preview_preset("physical_retail")
        await db.flush()
        # No overrides should exist.
        overrides = await svc.list_overrides()
        assert len(overrides) == 0

    @pytest.mark.asyncio
    async def test_preview_composable_preset_shows_merged_keys(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        result = await svc.preview_preset("enterprise")
        # enterprise merges physical_retail + omnichannel + enterprise.
        assert result["chain"] == ["physical_retail", "omnichannel", "enterprise"]
        # The total keys include inherited ones.
        assert result["total_keys"] == len(PRESETS["enterprise"])


# ------------------------------------------------------------------ atomic apply + audit


class TestAtomicApplyWithAudit:
    """``apply_preset`` is all-or-nothing and writes an audit row."""

    @pytest.mark.asyncio
    async def test_apply_writes_all_keys(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        result = await svc.apply_preset("physical_retail", user_id=user.id, permissions=OWNER)
        rows = result["applied"]
        assert len(rows) + len(result["pending_approval"]) == len(PRESETS["physical_retail"])
        # Every key should now resolve to the preset value.
        for key, expected in PRESETS["physical_retail"].items():
            val = await svc.value(key)
            assert val == expected, f"{key}: {val} != {expected}"

    @pytest.mark.asyncio
    async def test_apply_records_history_with_preset_reason(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        await svc.apply_preset("physical_retail", user_id=user.id, permissions=OWNER)
        await db.flush()
        history = await svc.history(limit=100)
        assert len(history) > 0
        for row in history:
            assert row.change_reason == "preset:physical_retail"

    @pytest.mark.asyncio
    async def test_apply_writes_audit_log_row(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        await svc.apply_preset("physical_retail", user_id=user.id, permissions=OWNER)
        await db.flush()
        # Check the audit_logs table for the preset_applied action.

        row = (
            await db.execute(
                sa.text(
                    "SELECT action, resource_type, after "
                    "  FROM audit_logs "
                    " WHERE tenant_id = :tid "
                    "   AND action = 'settings.preset_applied' "
                    " LIMIT 1"
                ),
                {"tid": str(tenant.id)},
            )
        ).first()
        assert row is not None, "no settings.preset_applied audit row found"
        assert row[0] == "settings.preset_applied"
        assert row[1] == "tenant_settings"

    @pytest.mark.asyncio
    async def test_apply_composable_preset_merges_parent_values(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        result = await svc.apply_preset("enterprise", user_id=user.id, permissions=OWNER)
        rows = result["applied"]
        # enterprise merges physical_retail + omnichannel + enterprise.
        assert len(rows) + len(result["pending_approval"]) == len(PRESETS["enterprise"])
        # A key from the root parent (physical_retail):
        assert await svc.value("business.type") == "retail"
        # A key from the middle (omnichannel):
        assert await svc.value("inventory.auto_reserve") is True
        # A key from the leaf (enterprise):
        assert await svc.value("purchasing.approval_required") is True

    @pytest.mark.asyncio
    async def test_apply_unknown_preset_raises(self, db) -> None:
        user, tenant = await _create_tenant(db)
        await bind_tenant(db, tenant.id)
        svc = SettingsService(db, tenant.id)
        from app.core.errors import ValidationError

        with pytest.raises(ValidationError):
            await svc.apply_preset("nonexistent", user_id=user.id, permissions=OWNER)
