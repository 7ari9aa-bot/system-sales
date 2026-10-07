"""The `metric_definitions` TABLE must mirror the in-code registry (spec §167).

§167 made ``app/modules/platform/metrics.py`` the single source of truth for
canonical metric definitions, and ``GET /api/v1/platform/metrics`` answers from
the in-process ``MetricRegistry``. The ``metric_definitions`` TABLE is that
registry's tenant-visible AUDIT COPY, not a second source of truth: the rule is
"the registry is regenerated from code and pushed to rows", so a row that
disagrees with the registry for the same ``(name, version)`` is a BUG.

Before this work the table mirrored nothing:

* ``seed_definitions`` had ZERO callers on the provisioning path, so a freshly
  provisioned tenant had no ``metric_definitions`` row at all; and
* it was insert-only (``ON CONFLICT DO NOTHING``), so even if it ran, a
  definition whose text / SQL / unit / refund-treatment later changed could
  never reach an existing tenant.

The tests below pin both halves. The PURE / static cases run everywhere; the
DB-backed cases need ``DATABASE_URL_APP_ADMIN`` (they skip without it and are
proved in CI).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.modules.identity.bootstrap import seed_tenant_defaults
from app.modules.identity.models import Tenant
from app.modules.identity.service import AuthService
from app.modules.platform import metrics as metrics_mod
from app.modules.platform.metrics import (
    METRIC_DEFINITIONS,
    MetricRegistry,
    MetricSpec,
    build_seed_statement,
    missing_or_drifted,
    seed_definitions,
)
from app.modules.platform.models import MetricDefinition

TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")

# Columns that a row must carry identically to its registry spec for the row to
# count as "in sync". (name, version) is the identity, not a synced field.
SYNCED_FIELDS = (
    "definition",
    "source",
    "filters",
    "timezone_rule",
    "currency_rule",
    "refund_treatment",
)


def _spec(name: str = "revenue", **overrides: Any) -> MetricSpec:
    base = MetricRegistry.get(name)
    assert base is not None, f"{name} must be canonical"
    values = base.as_dict()
    values.update(overrides)
    return MetricSpec(**values)


def _row_for(spec: MetricSpec, **overrides: Any) -> dict[str, Any]:
    """The stored-row shape ``missing_or_drifted`` compares against."""
    row = {field: getattr(spec, field) for field in SYNCED_FIELDS}
    row.update(overrides)
    return row


# -------------------------------------------- static: the write converges ---
#
# These are the "runs everywhere" proofs that the present upsert is a CONVERGING
# (DO UPDATE) statement rather than the old insert-only (DO NOTHING) one. They
# fail against the old code, which had no such builder at all.


def test_build_seed_statement_converges_instead_of_skipping() -> None:
    """The conflict action must be DO UPDATE — a changed row is rewritten, not skipped."""
    stmt = build_seed_statement([{**_spec("revenue").as_dict(), "tenant_id": TENANT}])
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    upper = sql.upper()
    assert "ON CONFLICT" in upper, sql
    assert "DO UPDATE SET" in upper, (
        "seed write must CONVERGE an existing row; DO NOTHING leaves a stale "
        "definition in place forever"
    )
    assert "DO NOTHING" not in upper, "insert-only upsert can never propagate a change"


def test_build_seed_statement_targets_the_identity_key() -> None:
    """The conflict target is (tenant_id, name, version) — version is part of identity."""
    stmt = build_seed_statement([{**_spec("revenue").as_dict(), "tenant_id": TENANT}])
    sql = str(stmt.compile(dialect=postgresql.dialect())).upper()
    # The ON CONFLICT (...) inference columns are the unique key columns.
    conflict_clause = sql.split("ON CONFLICT", 1)[1].split("DO UPDATE", 1)[0]
    for column in ("TENANT_ID", "NAME", "VERSION"):
        assert column in conflict_clause, conflict_clause


# ------------------------------------------- pure: a drifted row gets pushed --


def test_pristine_tenant_is_missing_every_definition() -> None:
    """A provisioned-but-unseeded tenant (empty table) is missing ALL registry rows."""
    drifted = missing_or_drifted({}, METRIC_DEFINITIONS)
    assert {s.name for s in drifted} == set(MetricRegistry.names())


def test_in_sync_rows_are_not_rewritten() -> None:
    existing = {(s.name, s.version): _row_for(s) for s in METRIC_DEFINITIONS}
    assert missing_or_drifted(existing, METRIC_DEFINITIONS) == []


def test_a_changed_definition_reaches_an_existing_tenant() -> None:
    """THE core regression: a row whose text drifted from the registry must be re-written.

    The old insert-only ``ON CONFLICT DO NOTHING`` would have skipped this row and
    left the tenant measuring against a stale definition.
    """
    spec = _spec("revenue")
    stale = {(s.name, s.version): _row_for(s) for s in METRIC_DEFINITIONS}
    stale[("revenue", spec.version)] = _row_for(spec, definition="REVENUE IS NOW WRONG")

    drifted = missing_or_drifted(stale, METRIC_DEFINITIONS)
    assert any(s.name == "revenue" for s in drifted), (
        "a bumped/edited definition cannot reach a seeded tenant"
    )


@pytest.mark.parametrize(
    "field",
    SYNCED_FIELDS,
)
def test_any_synced_field_change_triggers_a_rewrite(field: str) -> None:
    spec = _spec("net_revenue")
    existing = {(s.name, s.version): _row_for(s) for s in METRIC_DEFINITIONS}
    existing[("net_revenue", spec.version)] = _row_for(spec, **{field: "__drifted__"})
    drifted = missing_or_drifted(existing, METRIC_DEFINITIONS)
    assert any(s.name == "net_revenue" for s in drifted), field


def test_a_bumped_version_is_a_new_row_not_an_overwrite() -> None:
    """Version is part of identity: v2 lands as a NEW row; the v1 history row stays."""
    spec = _spec("revenue", version=2)
    only_v1 = {("revenue", 1): _row_for(_spec("revenue", version=1))}
    drifted = missing_or_drifted(only_v1, [spec])
    assert drifted == [spec], "registry version 2 is a distinct row, not an update of v1"


def test_seed_definitions_source_no_longer_uses_do_nothing() -> None:
    """Guard the fix at the source level too: the module must not fall back to DO NOTHING."""
    import inspect

    src = inspect.getsource(metrics_mod)
    assert "on_conflict_do_nothing" not in src, (
        "insert-only seeding is the bug this work removes; the write must converge"
    )
    assert "on_conflict_do_update" in src


# ------------------------------------------------------- DB: provisioning -----
#
# These need a real PostgreSQL (DATABASE_URL_APP_ADMIN) and skip without it —
# they are proven in CI. The static/pure tests above run everywhere.


def _row_map(rows: list[MetricDefinition]) -> dict[tuple[str, int], dict[str, Any]]:
    return {
        (r.name, r.version): {field: getattr(r, field) for field in SYNCED_FIELDS} for r in rows
    }


async def test_provisioning_seeds_every_canonical_definition(db: AsyncSession, tenant_ctx) -> None:
    """A tenant that has been provisioned must have one row per registry metric."""
    _, tenant = await AuthService.register(
        db,
        tenant_name="Measured Co",
        tenant_slug=f"measured-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="secret-password",
        full_name="Measured Owner",
    )
    rows = (
        (await db.execute(select(MetricDefinition).where(MetricDefinition.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert {r.name for r in rows} == set(MetricRegistry.names())


async def test_every_seeded_row_equals_the_registry(db: AsyncSession, tenant_ctx) -> None:
    """THE single-source-of-truth guarantee: after seeding, table == registry."""
    _, tenant = await AuthService.register(
        db,
        tenant_name="Mirror Co",
        tenant_slug=f"mirror-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="secret-password",
        full_name="Mirror Owner",
    )
    await bind_tenant(db, tenant.id)
    rows = (
        (await db.execute(select(MetricDefinition).where(MetricDefinition.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    stored = _row_map(list(rows))
    for spec in METRIC_DEFINITIONS:
        assert stored[(spec.name, spec.version)] == {
            field: getattr(spec, field) for field in SYNCED_FIELDS
        }, f"{spec.name}: row disagrees with the registry (a bug)"


async def test_reseeding_converges_a_drifted_row(db: AsyncSession, tenant_ctx) -> None:
    """A row edited out from under the registry is restored on the next seed."""
    _, tenant = await AuthService.register(
        db,
        tenant_name="Drift Co",
        tenant_slug=f"drift-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="secret-password",
        full_name="Drift Owner",
    )
    await bind_tenant(db, tenant.id)
    row = (
        await db.execute(
            select(MetricDefinition).where(
                MetricDefinition.tenant_id == tenant.id,
                MetricDefinition.name == "revenue",
            )
        )
    ).scalar_one()
    row.definition = "CORRUPTED BY HAND"
    await db.flush()

    wrote = await seed_definitions(db, tenant.id)
    await db.flush()
    assert wrote >= 1, "the drifted row must be rewritten"

    await db.refresh(row)
    canonical = MetricRegistry.get("revenue")
    assert canonical is not None
    assert row.definition == canonical.definition


async def test_seed_is_idempotent_on_an_in_sync_tenant(db: AsyncSession, tenant_ctx) -> None:
    _, tenant = await AuthService.register(
        db,
        tenant_name="Twice Measured Co",
        tenant_slug=f"twice-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="secret-password",
        full_name="Twice Owner",
    )
    await bind_tenant(db, tenant.id)
    before = (
        (await db.execute(select(MetricDefinition).where(MetricDefinition.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(before) == len(METRIC_DEFINITIONS)

    # Re-running the provisioning seed writes nothing and adds no rows.
    again = await seed_definitions(db, tenant.id)
    await db.flush()
    assert again == 0, "an in-sync tenant must not be rewritten"
    after = (
        (await db.execute(select(MetricDefinition).where(MetricDefinition.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(after) == len(before)


async def test_seed_tenant_defaults_reports_metric_definitions(db: AsyncSession) -> None:
    """seed_tenant_defaults both seeds the definitions and reports it in its summary."""
    tenant = (await db.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if tenant is None:
        pytest.skip("no tenant available to seed against")
    await bind_tenant(db, tenant.id)
    created = await seed_tenant_defaults(db, tenant.id)
    assert "metric_definitions" in created
    rows = (
        (await db.execute(select(MetricDefinition).where(MetricDefinition.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert {r.name for r in rows} == set(MetricRegistry.names())
