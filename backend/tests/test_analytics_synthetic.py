"""Synthetic store + golden runner tests (spec §17.1-§17.2) — Phase 2's gate.

Each planted scenario flows through the REAL analytics path (compiler →
capabilities → drivers → engines) against a seeded real database, and the
manifest's truth is asserted. Determinism is pinned: the same seed rebuilds
the identical store. No LLM anywhere (§17.2's "golden scenarios, no model").
"""

from __future__ import annotations

import pytest

from app.modules.analytics.evaluation.golden import evaluate_scenario
from app.modules.analytics.evaluation.synthetic import Scenario, generate_store

# The seeding lives in the operator harness (scripts/run_golden_eval.py) so
# the eval script and this matrix plant data through one code path.
from scripts.run_golden_eval import seed_store


def test_generation_is_deterministic_under_a_seed():
    first = generate_store(Scenario.BASELINE, seed=42)
    second = generate_store(Scenario.BASELINE, seed=42)
    assert [o["placed_at"] for o in first.orders] == [
        o["placed_at"] for o in second.orders
    ]
    assert [o["grand_total"] for o in first.orders] == [
        o["grand_total"] for o in second.orders
    ]


@pytest.mark.parametrize(
    "scenario",
    [
        Scenario.BASELINE,
        Scenario.AOV_DECLINE,
        Scenario.ORDERS_DECLINE,
        Scenario.REVENUE_SPIKE,
        Scenario.REFUND_SPIKE,
        Scenario.IMMATURE_TAIL,
        Scenario.CHANNEL_SHIFT,
    ],
)
async def test_golden_scenario_passes_end_to_end(db, tenant_ctx, scenario):
    store = generate_store(scenario, seed=42)
    await seed_store(db, tenant_ctx.tenant_id, store)

    result = await evaluate_scenario(db, tenant_ctx.tenant_id, store)
    failures = [c for c in result.checks if not c[1]]
    assert result.passed, f"{scenario.value}: {failures}"
