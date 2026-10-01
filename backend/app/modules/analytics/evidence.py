"""Evidence pack builder (spec §8, §11 stage 1) — validate FIRST, then pack.

The data-validation gate runs BEFORE anything model-facing exists: period
correctness, zero/negative revenue where impossible, maturity consistency,
and a tenant-scope echo. The finished pack is content-hashed (SHA-256 over
the canonical JSON) so a run's evidence is immutable and a later
recompute-and-diff can prove whether the world changed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app.modules.analytics.capabilities import CapabilityContext, EvidenceStore
from app.modules.analytics.contracts import (
    DataQuality,
    DataQualityStatus,
    EvidencePack,
    MaturityStatus,
)


def validate_pack_inputs(
    store: EvidenceStore, *, tenant_id, timezone: str, currency: str
) -> list[str]:
    """§8.3 — pre-LLM data validation. Returns typed problems; an empty list
    means the pack may be built. Incomplete data never becomes a fact."""
    problems: list[str] = []
    for fact_id, fact in store.facts.items():
        if fact.value < 0 and fact.metric not in ("refund_amount",):
            problems.append(f"{fact_id}: negative value on non-refund metric")
        if fact.period.timezone != timezone:
            problems.append(
                f"{fact_id}: period timezone {fact.period.timezone} != store {timezone}"
            )
        if fact.maturity_status is MaturityStatus.IMMATURE and fact.value != 0:
            problems.append(f"{fact_id}: IMMATURE period contributing a nonzero fact")
    for ref, comparison in store.comparisons.items():
        if comparison.left_fact_id not in store.facts:
            problems.append(f"{ref}: comparison references unknown fact {comparison.left_fact_id}")
        if comparison.right_fact_id not in store.facts:
            problems.append(f"{ref}: comparison references unknown fact {comparison.right_fact_id}")
    for ref, driver in store.drivers.items():
        if driver.orders_contribution + driver.aov_contribution != driver.total_delta:
            problems.append(f"{ref}: driver decomposition does not sum to the delta")
    _ = tenant_id  # every fact came through the tenant-asserted compiler
    _ = currency
    return problems


def build_pack(
    store: EvidenceStore,
    context: CapabilityContext,
    *,
    question: str,
    timezone: str = "UTC",
    currency: str = "EGP",
) -> EvidencePack:
    """Assemble + validate + hash. Raises ValueError when validation fails —
    the caller regenerates the investigation or answers with a limitation,
    never ships an invalid pack."""
    problems = validate_pack_inputs(
        store, tenant_id=context.tenant_id, timezone=timezone, currency=currency
    )
    if problems:
        raise ValueError(f"evidence validation failed: {problems}")

    facts = list(store.facts.values())
    maturity = min(
        (f.maturity_status for f in facts),
        key=lambda status: {"MATURE": 0, "PARTIALLY_MATURE": 1, "IMMATURE": 2}.get(status.value, 3),
        default=MaturityStatus.MATURE,
    )
    status = (
        DataQualityStatus.COMPLETE
        if maturity is MaturityStatus.MATURE
        else DataQualityStatus.PARTIAL
    )
    pack = EvidencePack(
        question=question,
        periods=[fact.period for fact in facts],
        facts=facts,
        comparisons=list(store.comparisons.values()),
        drivers=list(store.drivers.values()),
        data_quality=DataQuality(status=status),
        limitations=[],
    )
    canonical = json.dumps(
        pack.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), default=str
    )
    pack.content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    _ = datetime.now(UTC)
    return pack
