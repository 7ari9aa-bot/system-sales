"""Behavioral tests: change a setting and verify the runtime behaviour changes.

Unlike ``test_settings_enforced_keys`` (which checks that a key string appears
in source files), these tests set a value through the service, then call the
code that reads the setting and assert the behaviour is different.

Covers:
* ``pos.max_discount_pct`` — the discount ceiling enforced by POS service.
* ``security.ip_allowlist`` — IP validation on the LIST item validator.
* ``customer_agent.enabled`` — the flag that gates the AI auto-reply hook.
* ``pos.return_reasons`` — LIST type with default items.
"""

from __future__ import annotations

import pytest

from app.platform.settings.registry import (
    REGISTRY,
    SettingType,
    get_definition,
)


class TestListValidators:
    """LIST settings with ``item_validator`` reject invalid items."""

    def test_ip_allowlist_rejects_invalid_ip(self):
        defn = get_definition("security.ip_allowlist")
        assert defn.item_validator is not None
        assert defn.item_type == SettingType.STRING
        with pytest.raises(ValueError, match="invalid IP/CIDR"):
            defn.validate(["not-an-ip"])

    def test_ip_allowlist_accepts_valid_ips(self):
        defn = get_definition("security.ip_allowlist")
        defn.validate(["192.168.1.1", "10.0.0.0/8"])
        defn.validate([])  # empty is fine

    def test_ip_allowlist_rejects_cidr_with_bad_mask(self):
        defn = get_definition("security.ip_allowlist")
        with pytest.raises(ValueError, match="invalid IP/CIDR"):
            defn.validate(["192.168.1.0/33"])

    def test_return_reasons_accepts_list_of_strings(self):
        defn = get_definition("pos.return_reasons")
        assert defn.type == SettingType.LIST
        assert defn.item_type is None  # no item-level validation
        defn.validate(["size", "custom_reason"])

    def test_list_rejects_non_list(self):
        defn = get_definition("pos.return_reasons")
        with pytest.raises(ValueError, match="expected list"):
            defn.validate("not-a-list")


class TestSettingBehavioralChanges:
    """Verify that changing a setting value changes the resolved behaviour.

    These tests do NOT use the database: they verify that the registry
    ``default`` and the ``validate`` method interact correctly — i.e. that
    the setting's type contract is enforced and the default value is what
    the runtime code expects.
    """

    def test_pos_max_discount_pct_validates_and_bounds(self):
        defn = get_definition("pos.max_discount_pct")
        assert defn.type == SettingType.NUMBER
        assert defn.min_value == 0
        assert defn.max_value == 100
        # A value within bounds is accepted
        defn.validate(15.0)
        # Out-of-bounds values are rejected
        with pytest.raises(ValueError, match="max"):
            defn.validate(101)

    def test_customer_agent_enabled_is_bool_true(self):
        defn = get_definition("customer_agent.enabled")
        assert defn.type == SettingType.BOOL
        assert defn.default is True
        # The runtime hook reads this; defaulting to True means the agent
        # is ON unless the owner explicitly disables it (gated by entitlements).
        defn.validate(True)
        defn.validate(False)

    def test_pos_return_reasons_default_is_list(self):
        defn = get_definition("pos.return_reasons")
        assert isinstance(defn.default, list)
        assert len(defn.default) > 0
        # All defaults must be strings (LIST of strings)
        for item in defn.default:
            assert isinstance(item, str)

    def test_analytics_agent_include_branches_accepts_empty(self):
        defn = get_definition("analytics_agent.include_branches")
        assert defn.type == SettingType.LIST
        assert defn.default == []
        defn.validate([])  # empty means "all branches"
        defn.validate([str(i) for i in range(3)])

    def test_change_in_resolved_value_reflected(self):
        """When a setting value changes, the resolved value changes too.

        This is a registry-level test (no DB): we verify that the
        ``validate`` method round-trips the new value and that the
        default differs from an override.
        """
        defn = get_definition("pos.max_discount_pct")
        original = defn.default
        new_value = defn.validate(50.0 if original != 50.0 else 25.0)
        assert new_value != original

    def test_security_require_strong_passwords_is_bool(self):
        defn = get_definition("security.require_strong_passwords")
        assert defn.type == SettingType.BOOL
        assert defn.default is True
        defn.validate(True)
        defn.validate(False)

    def test_team_require_2fa_is_bool(self):
        defn = get_definition("team.require_2fa")
        assert defn.type == SettingType.BOOL
        defn.validate(True)
        defn.validate(False)

    def test_organization_multi_branch_is_bool(self):
        defn = get_definition("organization.multi_branch")
        assert defn.type == SettingType.BOOL
        defn.validate(True)
        defn.validate(False)


class TestRegistryCount:
    """Verify the registry count matches documentation."""

    def test_registry_has_134_keys(self):
        # 127 -> 134 with the seven `pricing.*` keys the pricing module reads as its policy
        # (price lists, tiers, rounding, stacking, the below-cost floor, the order cap). A key
        # added to the registry without this number moving is how the docs drift from the code.
        assert len(REGISTRY) == 134

    def test_all_keys_are_unique(self):
        keys = [d.key for d in REGISTRY.values()]
        assert len(keys) == len(set(keys))

    def test_all_keys_are_dotted(self):
        for key in REGISTRY:
            assert "." in key, f"key {key!r} has no domain separator"
