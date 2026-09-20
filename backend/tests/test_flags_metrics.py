"""Focused, DB-free tests for feature flags (§76) and the metric registry (§167).

Both services need a database for real work, so these tests drive the pure
decision logic with a tiny fake session: flag precedence, rollout determinism
and boundaries, registry integrity, and proof the routes are mounted.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ValidationError
from app.main import create_app
from app.modules.platform.flags import FeatureFlagService
from app.modules.platform.metrics import METRIC_DEFINITIONS, TZ_MERCHANT, MetricRegistry
from app.modules.platform.models import FeatureFlag

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
FEATURE = "voice.enabled"
REQUIRED_METRICS = {
    "revenue",
    "orders_count",
    "aov",
    "refunded_amount",
    "net_revenue",
    "first_response_time",
    "resolution_time",
    "ai_resolution_rate",
    "conversion_rate",
    "roas",
}


class _FakeResult:
    def __init__(self, row: FeatureFlag | None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> FeatureFlag | None:
        return self._row


class _FakeSession:
    """Returns one fixed row for any query — enough to drive the decision fn."""

    def __init__(self, row: FeatureFlag | None = None) -> None:
        self.row = row

    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult(self.row)


def _flag(**overrides: object) -> FeatureFlag:
    values: dict[str, object] = {
        "tenant_id": TENANT,
        "feature": FEATURE,
        "enabled": True,
        "rollout_percent": 100,
    }
    values.update(overrides)
    return FeatureFlag(**values)


# ------------------------------------------------------------ precedence ----


async def test_absent_flag_returns_default_never_raises() -> None:
    session = _FakeSession(row=None)
    assert await FeatureFlagService.is_enabled(session, TENANT, FEATURE) is False
    assert await FeatureFlagService.is_enabled(session, TENANT, FEATURE, default=True) is True


async def test_disabled_row_is_false_even_at_full_rollout() -> None:
    session = _FakeSession(_flag(enabled=False, rollout_percent=100))
    assert await FeatureFlagService.is_enabled(session, TENANT, FEATURE) is False


async def test_workspace_scoped_row_only_matches_its_workspace() -> None:
    workspace_id = uuid.uuid4()
    session = _FakeSession(_flag(workspace_id=workspace_id))
    assert (
        await FeatureFlagService.is_enabled(session, TENANT, FEATURE, workspace_id=workspace_id)
        is True
    )
    assert (
        await FeatureFlagService.is_enabled(session, TENANT, FEATURE, workspace_id=uuid.uuid4())
        is False
    )
    # No workspace context -> a workspace-scoped row does not apply.
    assert await FeatureFlagService.is_enabled(session, TENANT, FEATURE) is False


async def test_role_scoped_row_only_matches_its_role() -> None:
    session = _FakeSession(_flag(role_code="manager"))
    assert (
        await FeatureFlagService.is_enabled(session, TENANT, FEATURE, role_code="manager") is True
    )
    assert (
        await FeatureFlagService.is_enabled(session, TENANT, FEATURE, role_code="staff") is False
    )
    assert await FeatureFlagService.is_enabled(session, TENANT, FEATURE) is False


async def test_precedence_order_is_absent_disabled_scope_then_rollout() -> None:
    # 1. absent -> default
    absent = await FeatureFlagService.is_enabled(
        _FakeSession(None), TENANT, FEATURE, default=True
    )
    assert absent is True
    # 2. disabled beats a matching scope and a 100% rollout
    disabled = _FakeSession(_flag(enabled=False, role_code="manager", rollout_percent=100))
    assert (
        await FeatureFlagService.is_enabled(disabled, TENANT, FEATURE, role_code="manager") is False
    )
    # 3/4. a scope mismatch beats a 100% rollout
    mismatched = _FakeSession(_flag(workspace_id=uuid.uuid4(), rollout_percent=100))
    assert await FeatureFlagService.is_enabled(mismatched, TENANT, FEATURE) is False
    # 5. everything matches at 100% -> on
    workspace_id = uuid.uuid4()
    matched = _FakeSession(
        _flag(workspace_id=workspace_id, role_code="manager", rollout_percent=100)
    )
    assert (
        await FeatureFlagService.is_enabled(
            matched, TENANT, FEATURE, workspace_id=workspace_id, role_code="manager"
        )
        is True
    )


# ---------------------------------------------------------- rollout rules ---


@pytest.mark.parametrize(("percent", "expected"), [(0, False), (100, True)])
async def test_rollout_boundaries(percent: int, expected: bool) -> None:
    session = _FakeSession(_flag(rollout_percent=percent))
    result = await FeatureFlagService.is_enabled(session, TENANT, FEATURE, stable_key="user-1")
    assert result is expected


async def test_rollout_is_deterministic_for_a_stable_key() -> None:
    """The same key must not flip between requests — repeat it many times."""
    session = _FakeSession(_flag(rollout_percent=37))
    first = await FeatureFlagService.is_enabled(session, TENANT, FEATURE, stable_key="user-42")
    for _ in range(50):
        again = await FeatureFlagService.is_enabled(session, TENANT, FEATURE, stable_key="user-42")
        assert again is first


async def test_missing_stable_key_falls_back_to_tenant_level_bucketing() -> None:
    session = _FakeSession(_flag(rollout_percent=37))
    answers = {
        await FeatureFlagService.is_enabled(session, TENANT, FEATURE) for _ in range(20)
    }
    assert len(answers) == 1  # one stable, tenant-wide decision
    explicit = await FeatureFlagService.is_enabled(session, TENANT, FEATURE, stable_key="")
    assert answers == {explicit}


@pytest.mark.parametrize("percent", [-1, 101])
async def test_set_flag_rejects_out_of_range_percent_before_touching_db(percent: int) -> None:
    with pytest.raises(ValidationError):
        await FeatureFlagService.set_flag(
            None,  # type: ignore[arg-type] — raises before the session is used
            TENANT,
            FEATURE,
            enabled=True,
            rollout_percent=percent,
        )


# ------------------------------------------------------ metric registry -----


def test_metric_registry_has_no_duplicate_names() -> None:
    names = [spec.name for spec in METRIC_DEFINITIONS]
    assert len(names) == len(set(names))
    assert names == MetricRegistry.names()


def test_metric_registry_covers_the_required_metrics() -> None:
    assert REQUIRED_METRICS <= set(MetricRegistry.names())


def test_every_metric_declares_timezone_refund_treatment_and_source() -> None:
    for entry in MetricRegistry.definitions():
        name = entry["name"]
        assert entry["timezone_rule"] == TZ_MERCHANT, name  # merchant zone, never UTC
        assert entry["refund_treatment"], name
        assert entry["currency_rule"], name
        assert entry["definition"], name
        assert entry["source"], name
        assert isinstance(entry["filters"], dict), name
        assert entry["version"] >= 1, name


def test_revenue_is_gross_and_net_revenue_subtracts_refunds() -> None:
    gross = MetricRegistry.get("revenue")
    net = MetricRegistry.get("net_revenue")
    assert gross is not None and net is not None
    assert gross.refund_treatment == "excluded"
    assert net.refund_treatment == "subtracted"
    assert "refund" in gross.definition.lower()
    assert "refund" in net.definition.lower()


def test_platform_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {
        "/api/v1/platform/flags",
        "/api/v1/platform/flags/{feature}",
        "/api/v1/platform/flags/{feature}/check",
        "/api/v1/platform/metrics",
    } <= paths
