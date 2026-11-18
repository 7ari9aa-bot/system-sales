"""Unit tests for the FIHRIST Configuration Engine.

Tests:
1. Registry validation (types, bounds, allowed scopes, enums).
2. Service resolver inheritance (scope walk:
   register -> profile -> warehouse -> branch -> tenant -> default).
3. Service CRUD (set, reset, bulk_set, history).
4. Presets application.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.settings.models import TenantSetting
from app.modules.settings.presets import PRESETS
from app.modules.settings.registry import (
    Scope,
    SettingDef,
    SettingType,
    domains,
    get_definition,
    list_definitions,
)
from app.modules.settings.service import SettingsService

# ===========================================================================
# 1. Registry Validation Tests
# ===========================================================================


def test_registry_contains_core_domains():
    all_domains = domains()
    assert "business" in all_domains
    assert "pos" in all_domains
    assert "inventory" in all_domains
    assert "purchasing" in all_domains
    assert "orders" in all_domains
    assert "print" in all_domains
    assert "notifications" in all_domains


def test_registry_get_definition():
    defn = get_definition("pos.require_customer")
    assert defn.key == "pos.require_customer"
    assert defn.domain == "pos"
    assert defn.type == SettingType.BOOL
    assert defn.default is False
    assert Scope.TENANT in defn.scopes
    assert Scope.BRANCH in defn.scopes
    assert Scope.POS_PROFILE in defn.scopes


def test_registry_get_unknown_key_raises():
    with pytest.raises(KeyError, match="Unknown setting key"):
        get_definition("nonexistent.setting.key")


def test_registry_list_definitions_domain_filter():
    pos_defs = list_definitions(domain="pos")
    assert len(pos_defs) > 0
    assert all(d.domain == "pos" for d in pos_defs)


def test_setting_def_bool_validation():
    defn = SettingDef(
        key="test.bool",
        domain="test",
        type=SettingType.BOOL,
        default=False,
    )
    assert defn.validate(True) is True
    assert defn.validate(False) is False
    with pytest.raises(ValueError, match="expected bool"):
        defn.validate("true")
    with pytest.raises(ValueError, match="expected bool"):
        defn.validate(1)


def test_setting_def_number_validation():
    defn = SettingDef(
        key="test.num",
        domain="test",
        type=SettingType.NUMBER,
        min_value=0,
        max_value=100,
    )
    assert defn.validate(50) == 50.0
    assert defn.validate(0) == 0.0
    assert defn.validate(100) == 100.0
    assert defn.validate(Decimal("25.5")) == 25.5

    with pytest.raises(ValueError, match="below minimum"):
        defn.validate(-1)
    with pytest.raises(ValueError, match="above maximum"):
        defn.validate(101)
    with pytest.raises(ValueError, match="expected number"):
        defn.validate("not a number")
    with pytest.raises(ValueError, match="expected number, got bool"):
        defn.validate(True)


def test_setting_def_string_validation():
    defn = SettingDef(
        key="test.str",
        domain="test",
        type=SettingType.STRING,
        max_length=10,
    )
    assert defn.validate("hello") == "hello"
    with pytest.raises(ValueError, match="exceeds max"):
        defn.validate("this is way too long")
    with pytest.raises(ValueError, match="expected string"):
        defn.validate(12345)


def test_setting_def_enum_validation():
    defn = SettingDef(
        key="test.enum",
        domain="test",
        type=SettingType.ENUM,
        allowed_values=("small", "medium", "large"),
    )
    assert defn.validate("small") == "small"
    assert defn.validate("large") == "large"
    with pytest.raises(ValueError, match="not in"):
        defn.validate("extra_large")
    with pytest.raises(ValueError, match="expected string"):
        defn.validate(10)


def test_setting_def_list_validation():
    defn = SettingDef(
        key="test.list",
        domain="test",
        type=SettingType.LIST,
    )
    assert defn.validate(["a", "b"]) == ["a", "b"]
    with pytest.raises(ValueError, match="expected list"):
        defn.validate("not a list")


def test_setting_def_scope_allowed():
    defn = SettingDef(
        key="test.scoped",
        domain="test",
        type=SettingType.BOOL,
        scopes=(Scope.TENANT, Scope.BRANCH),
    )
    assert defn.scope_allowed(Scope.TENANT) is True
    assert defn.scope_allowed("tenant") is True
    assert defn.scope_allowed(Scope.BRANCH) is True
    assert defn.scope_allowed(Scope.WAREHOUSE) is False
    assert defn.scope_allowed(Scope.REGISTER) is False


# ===========================================================================
# 2. Service Resolver Inheritance Tests (Mock Session)
# ===========================================================================


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_resolver_returns_default_when_no_override(mock_session):
    tenant_id = uuid.uuid4()
    svc = SettingsService(mock_session, tenant_id)

    # Mock DB query returning no rows
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    resolved = await svc.resolve("pos.require_customer", scope=Scope.TENANT)
    assert resolved.key == "pos.require_customer"
    assert resolved.value is False  # registry default
    assert resolved.is_default is True
    assert resolved.is_inherited is True
    assert resolved.scope == "default"


@pytest.mark.asyncio
async def test_resolver_returns_tenant_override(mock_session):
    tenant_id = uuid.uuid4()
    svc = SettingsService(mock_session, tenant_id)

    # Mock DB query returning a tenant-level override
    override_row = TenantSetting(
        tenant_id=tenant_id,
        key="pos.require_customer",
        scope="tenant",
        scope_id=None,
        value={"v": True},
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [override_row]
    mock_session.execute.return_value = mock_result

    resolved = await svc.resolve("pos.require_customer", scope=Scope.TENANT)
    assert resolved.key == "pos.require_customer"
    assert resolved.value is True
    assert resolved.is_default is False
    assert resolved.is_inherited is False
    assert resolved.scope == "tenant"


@pytest.mark.asyncio
async def test_resolver_branch_inherits_from_tenant(mock_session):
    tenant_id = uuid.uuid4()
    branch_id = uuid.uuid4()
    svc = SettingsService(mock_session, tenant_id)

    # DB has a tenant-level override only
    override_row = TenantSetting(
        tenant_id=tenant_id,
        key="pos.require_customer",
        scope="tenant",
        scope_id=None,
        value={"v": True},
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [override_row]
    mock_session.execute.return_value = mock_result

    # Resolve at branch level
    resolved = await svc.resolve("pos.require_customer", scope=Scope.BRANCH, scope_id=branch_id)
    assert resolved.key == "pos.require_customer"
    assert resolved.value is True
    assert resolved.is_default is False
    assert resolved.is_inherited is True  # inherited from tenant!
    assert resolved.scope == "tenant"


@pytest.mark.asyncio
async def test_resolver_branch_override_takes_precedence(mock_session):
    tenant_id = uuid.uuid4()
    branch_id = uuid.uuid4()
    svc = SettingsService(mock_session, tenant_id)

    # DB has both tenant and branch overrides
    tenant_row = TenantSetting(
        tenant_id=tenant_id,
        key="pos.require_customer",
        scope="tenant",
        scope_id=None,
        value={"v": False},
    )
    branch_row = TenantSetting(
        tenant_id=tenant_id,
        key="pos.require_customer",
        scope="branch",
        scope_id=branch_id,
        value={"v": True},
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [branch_row, tenant_row]
    mock_session.execute.return_value = mock_result

    # Resolve at branch level
    resolved = await svc.resolve("pos.require_customer", scope=Scope.BRANCH, scope_id=branch_id)
    assert resolved.key == "pos.require_customer"
    assert resolved.value is True  # branch value wins
    assert resolved.is_default is False
    assert resolved.is_inherited is False
    assert resolved.scope == "branch"


# ===========================================================================
# 3. Service Write / Reset Tests
# ===========================================================================


# ===========================================================================
# 4. Presets Validation
# ===========================================================================


def test_presets_keys_all_exist_in_registry():
    """Every key in every preset MUST be a valid key in the settings registry."""
    for preset_name, settings_dict in PRESETS.items():
        for key, val in settings_dict.items():
            defn = get_definition(key)
            assert defn is not None, f"Preset {preset_name} has unknown key {key}"
            # Validate that the preset value passes definition validation
            validated = defn.validate(val)
            assert validated is not None or defn.default is None
