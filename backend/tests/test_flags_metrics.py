"""Focused, DB-free tests for feature flags (§76) and the metric registry (§167).

Both services need a database for real work, so these tests drive the pure
decision logic with a tiny fake session: flag precedence, rollout determinism
and boundaries, registry integrity, proof the routes are mounted, and proof the
``metric_definitions`` TABLE is actually SERVED — §167's audit copy is only
worth its rows if a caller can read them back.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ValidationError
from app.main import create_app
from app.modules.platform.flags import FeatureFlagService
from app.modules.platform.metrics import (
    METRIC_DEFINITIONS,
    TZ_MERCHANT,
    MetricRegistry,
)
from app.modules.platform.models import FeatureFlag, MetricDefinition
from app.modules.platform.router import list_tenant_metric_definitions

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


@pytest.mark.parametrize("percent", [None, -5, 150, "100"])
async def test_a_stored_percent_the_write_paths_cannot_produce_fails_closed(percent: object) -> None:
    """Reading an invalid ``rollout_percent`` must be OFF, never widened.

    Fail-first: against the pre-fix evaluation, a corrupt ``150`` reached the
    ``percent >= ROLLOUT_MAX`` branch and answered True — a row nobody wrote
    through the validated write path silently widened its own rollout to
    "on for everyone". Only values the write path can produce (0-100) are
    honoured; everything else reads as off until an operator repairs the row.
    """
    session = _FakeSession(_flag(rollout_percent=percent))  # type: ignore[arg-type]
    assert await FeatureFlagService.is_enabled(session, TENANT, FEATURE) is False


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
        "/api/v1/platform/metrics/definitions",
    } <= paths


# ------------------------------------------------ metric_definitions TABLE --
#
# §167 makes ``metric_definitions`` the tenant-visible AUDIT COPY of the
# registry: ``seed_definitions`` pushes rows into it at provisioning and
# ``scripts/backfill_metric_definitions.py`` converges existing tenants. Both
# are WRITE halves. These tests pin the read half — a caller must be able to
# read the tenant's own rows back, and the answer must come FROM THE TABLE.


class _RowsResult:
    def __init__(self, rows: list[MetricDefinition]) -> None:
        self._rows = rows

    def scalars(self) -> _RowsResult:
        return self

    def all(self) -> list[MetricDefinition]:
        return list(self._rows)


class _RowsSession:
    """Answers every query with fixed rows and keeps the statements it was sent."""

    def __init__(self, rows: list[MetricDefinition]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def execute(self, stmt: object) -> _RowsResult:
        self.statements.append(stmt)
        return _RowsResult(self.rows)


def _definition(**overrides: object) -> MetricDefinition:
    values: dict[str, object] = {
        "tenant_id": TENANT,
        "name": "revenue",
        "definition": "gross captured money",
        "source": "orders",
        "filters": {"status": ["paid", "shipped"]},
        "timezone_rule": TZ_MERCHANT,
        "currency_rule": "presentment",
        "refund_treatment": "excluded",
        "version": 1,
    }
    values.update(overrides)
    return MetricDefinition(**values)


def _ctx(rows: list[MetricDefinition]) -> SimpleNamespace:
    return SimpleNamespace(session=_RowsSession(rows), tenant_id=TENANT)


async def test_tenant_definitions_route_serves_the_table_not_the_registry() -> None:
    """The response must carry what the ROW says, even where it disagrees.

    A route that answered from ``MetricRegistry`` would satisfy every other test
    in this file while leaving the table unread — which is exactly the defect
    this pins. The row's text is deliberately absent from the registry.
    """
    marker = "TEXT THAT EXISTS ONLY IN THIS TENANT'S ROW"
    payload = await list_tenant_metric_definitions(_ctx([_definition(definition=marker)]))

    assert json.dumps(MetricRegistry.definitions()).count(marker) == 0
    items = payload["items"]
    assert [item["definition"] for item in items] == [marker]
    assert items[0]["name"] == "revenue"
    assert items[0]["version"] == 1


async def test_tenant_definitions_route_scopes_the_read_to_the_caller_tenant() -> None:
    """No cross-tenant leak: the SELECT's WHERE carries the caller's tenant id.

    Asserted against the WHERE clause and its bound params, not the whole
    statement — ``tenant_id`` is a column of the table, so it appears in the
    column list of even a fully unfiltered SELECT.
    """
    session = _RowsSession([_definition()])
    await list_tenant_metric_definitions(SimpleNamespace(session=session, tenant_id=TENANT))

    assert len(session.statements) == 1
    compiled = session.statements[0].compile()
    sql = str(compiled)
    where = sql.split("WHERE", 1)
    assert len(where) == 2, "the definitions read has no WHERE clause"
    assert "tenant_id" in where[1], "the definitions read is not tenant-filtered"
    assert compiled.params["tenant_id_1"] == TENANT


async def test_tenant_definitions_route_reports_history_newest_version_first() -> None:
    """``(name, version)`` is the row identity: v1 stays as audit history.

    Two halves, because only one of them is testable without PostgreSQL. The
    ORDER BY is what puts v2 before v1 in production — the fake session cannot
    sort, so it is pinned as SQL. The handler then must not re-sort or filter
    the superseded version away, which the payload order does prove.
    """
    session = _RowsSession([])
    await list_tenant_metric_definitions(
        SimpleNamespace(session=session, tenant_id=TENANT)
    )
    sql = str(session.statements[0].compile())
    order_by = sql.split("ORDER BY", 1)
    assert len(order_by) == 2, "the definitions read has no ORDER BY"
    assert "metric_definitions.name" in order_by[1]
    assert "version DESC" in order_by[1], "versions are not newest-first"

    payload = await list_tenant_metric_definitions(
        _ctx([
            _definition(version=2, definition="current rule"),
            _definition(version=1, definition="retired rule"),
        ])
    )

    assert [item["version"] for item in payload["items"]] == [2, 1]


async def test_tenant_definitions_route_names_missing_and_drifted_rows() -> None:
    """A tenant that was never backfilled must be VISIBLE, not silently short.

    ``missing``: the registry has it, this tenant has no row for that version.
    ``drifted``: the row exists but no longer mirrors the registry it names.
    """
    drifted = next(spec for spec in METRIC_DEFINITIONS if spec.name == "revenue")
    rows = [
        _definition(
            name=drifted.name,
            version=drifted.version,
            definition="an OLD definition the registry no longer carries",
        )
    ]
    payload = await list_tenant_metric_definitions(_ctx(rows))

    assert payload["drifted"] == [drifted.name]
    assert set(payload["missing"]) == {
        spec.name for spec in METRIC_DEFINITIONS if spec.name != drifted.name
    }


async def test_converged_tenant_reports_no_gap_and_no_invented_rows() -> None:
    """After a seed, every registry entry has an exact-mirroring row."""
    rows = [
        _definition(
            name=spec.name,
            version=spec.version,
            definition=spec.definition,
            source=spec.source,
            filters=spec.filters,
            timezone_rule=spec.timezone_rule,
            currency_rule=spec.currency_rule,
            refund_treatment=spec.refund_treatment,
        )
        for spec in METRIC_DEFINITIONS
    ]
    payload = await list_tenant_metric_definitions(_ctx(rows))

    assert payload["missing"] == []
    assert payload["drifted"] == []
    assert len(payload["items"]) == len(METRIC_DEFINITIONS)


async def test_empty_tenant_is_an_empty_answer_not_an_error() -> None:
    """A tenant with no rows yet reads as empty — never a 500."""
    payload = await list_tenant_metric_definitions(_ctx([]))

    assert payload["items"] == []
    assert set(payload["missing"]) == {spec.name for spec in METRIC_DEFINITIONS}
    assert payload["drifted"] == []
