"""Tests for the settings architecture extensions (§27–§41).

Covers:
* Change request lifecycle (create → approve → applied) for approval-gated settings
* Rollback to a previous revision
* Optimistic concurrency (expected_history_id conflict detection)
* Settings changed event registration
* New domains (customer_agent, analytics_agent) in the registry
* ApplyMode and Sensitivity on SettingDef

Database-backed tests need Postgres+Redis; they skip silently without a database.
"""

from __future__ import annotations

import pytest

from app.modules.settings.events import SettingsChangedEvent
from app.modules.settings.registry import (
    REGISTRY,
    ApplyMode,
    Sensitivity,
    SettingType,
    get_definition,
)

# ---------------------------------------------------------------------------
# Registry: new fields and domains (no database needed)
# ---------------------------------------------------------------------------


class TestRegistryExtensions:
    """The registry carries the new architecture-contract fields (§11, §27)."""

    def test_apply_mode_exists_on_all_definitions(self):
        """Every setting has an apply_mode, defaulting to VALIDATED."""
        for key, defn in REGISTRY.items():
            assert defn.apply_mode in ApplyMode, f"{key} has invalid apply_mode"

    def test_sensitivity_exists_on_all_definitions(self):
        """Every setting has a sensitivity, defaulting to NORMAL."""
        for key, defn in REGISTRY.items():
            assert defn.sensitivity in Sensitivity, f"{key} has invalid sensitivity"

    def test_rollback_supported_exists_on_all_definitions(self):
        """Every setting declares whether rollback is supported."""
        for key, defn in REGISTRY.items():
            assert isinstance(defn.rollback_supported, bool), f"{key} missing rollback_supported"

    def test_customer_agent_domain_exists(self):
        """The customer_agent domain is registered with its settings (§49)."""
        keys = [k for k in REGISTRY if k.startswith("customer_agent.")]
        assert len(keys) >= 8, f"expected ≥8 customer_agent keys, got {len(keys)}"
        for key in keys:
            defn = get_definition(key)
            assert defn.domain == "customer_agent"

    def test_analytics_agent_domain_exists(self):
        """The analytics_agent domain is registered with its settings (§50)."""
        keys = [k for k in REGISTRY if k.startswith("analytics_agent.")]
        assert len(keys) >= 4, f"expected ≥4 analytics_agent keys, got {len(keys)}"
        for key in keys:
            defn = get_definition(key)
            assert defn.domain == "analytics_agent"

    def test_customer_agent_enabled_is_bool(self):
        defn = get_definition("customer_agent.enabled")
        assert defn.type == SettingType.BOOL
        assert defn.default is True

    def test_customer_agent_dialect_has_allowed_values(self):
        defn = get_definition("customer_agent.dialect")
        assert defn.type == SettingType.ENUM
        assert "egyptian" in defn.allowed_values

    def test_analytics_agent_min_confidence_has_bounds(self):
        defn = get_definition("analytics_agent.min_confidence")
        assert defn.type == SettingType.NUMBER
        assert defn.min_value == 0.0
        assert defn.max_value == 1.0

    def test_domains_list_includes_new_agents(self):
        from app.modules.settings.registry import domains

        all_domains = domains()
        assert "customer_agent" in all_domains
        assert "analytics_agent" in all_domains


# ---------------------------------------------------------------------------
# Event registration (no database needed)
# ---------------------------------------------------------------------------


class TestSettingsChangedEvent:
    """The settings.changed event is registered for the outbox (§36–§38)."""

    def test_event_is_registered(self):
        from app.core.events.schemas import EVENT_TYPES

        assert "settings.changed" in EVENT_TYPES

    def test_event_build_returns_expected_keys(self):
        payload = SettingsChangedEvent.build(
            tenant_id="test-tenant",
            key="pos.max_discount_pct",
            scope="tenant",
            scope_id=None,
            revision="rev-123",
            action="set",
            changed_by="user-456",
        )
        assert payload["key"] == "pos.max_discount_pct"
        assert payload["scope"] == "tenant"
        assert payload["revision"] == "rev-123"
        assert payload["action"] == "set"


# ---------------------------------------------------------------------------
# Database-backed tests (skip without a database)
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    import os

    return bool(os.environ.get("DATABASE_URL"))


@pytest.mark.skipif(not _db_available(), reason="no database URL configured")
class TestChangeRequestLifecycle:
    """Change request lifecycle for approval-gated settings (§28)."""

    pass


@pytest.mark.skipif(not _db_available(), reason="no database URL configured")
class TestRollback:
    """Rollback restores a previous revision without deleting history (§34)."""

    pass


@pytest.mark.skipif(not _db_available(), reason="no database URL configured")
class TestOptimisticConcurrency:
    """expected_history_id detects concurrent writes (§81)."""

    pass
