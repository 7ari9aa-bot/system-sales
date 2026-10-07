"""Sales Intelligence contracts (spec §4-15) — the typed vocabulary.

Pydantic v2 models defining the analytical truth boundary: what a metric IS
(MetricDefinition), what a computed number CARRIES (MetricFact — attribution
event, data_as_of, maturity, relationship), what evidence is (immutable,
content-hashed), and what a finding may CLAIM (type + relationship +
system-computed confidence). The LLM receives compact summaries and evidence
ids — never these structures' authority.

Analytics-layer rule: this file imports NOTHING from agents/ or any LLM
client — pure vocabulary, usable and testable without a model (§1.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class MaturityStatus(StrEnum):
    MATURE = "MATURE"
    PARTIALLY_MATURE = "PARTIALLY_MATURE"
    IMMATURE = "IMMATURE"


class Relationship(StrEnum):
    """§9.2 — how strongly the evidence supports the claim. The wording
    ladder enforces: temporal alignment alone may never read as cause."""

    OBSERVED = "OBSERVED"
    TEMPORAL_ASSOCIATION = "TEMPORAL_ASSOCIATION"
    CORRELATION = "CORRELATION"
    CAUSAL = "CAUSAL"


class DataQualityStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    IMMATURE = "IMMATURE"
    STALE = "STALE"
    INSUFFICIENT = "INSUFFICIENT"
    CONFLICTING = "CONFLICTING"


class MaturityPolicy(BaseModel):
    """How fast a metric settles to its final value for this store."""

    kind: Literal["immediate", "fast", "carrier_curve", "long_tail", "composite"]
    settle_days: int | None = None  # expected days until ~final


class FreshnessPolicy(BaseModel):
    max_age_hours: int = 26
    source: str = "primary_db"


class MetricDefinition(BaseModel):
    """§6.1 — the execution contract. The registry compiles to queries; it is
    a product decision, not a data dictionary."""

    name: str
    description: str
    semantic_type: Literal["count", "money", "ratio", "pct", "duration", "composite"]
    value_definition: str  # what is summed/counted, in words
    attribution_event: str  # lifecycle event that OWNS the number
    attribution_timestamp: str  # the column carrying that event's time
    lifecycle_filter: list[str] = Field(default_factory=list)
    maturity_policy: MaturityPolicy
    dimensions_allowed: list[str] = Field(default_factory=list)
    source: str
    null_behavior: str = "exclude"
    freshness_policy: FreshnessPolicy = Field(default_factory=FreshnessPolicy)
    timezone_policy: str = "store"
    currency_policy: str = "single"
    version: str = "1"
    lineage: list[str] = Field(default_factory=list)


class AnalysisPeriod(BaseModel):
    """§6.5 — a resolved period. Natural language NEVER resolves here: the
    system resolves it from the store calendar and the model receives it."""

    start: datetime
    end: datetime
    timezone: str
    attribution_basis: str  # e.g. "placed_at" / "delivered_at"
    maturity_policy: MaturityPolicy
    maturity_status: MaturityStatus
    maturity_ratio: float | None = Field(default=None, ge=0, le=1)
    data_as_of: datetime


class MetricFact(BaseModel):
    """§8.1 — one measured number. Every value in an answer must trace to
    one of these; the fact carries its own birth certificate."""

    id: str  # stable within a run: "F1", "F2", ...
    metric: str
    value: Decimal
    unit: Literal["count", "money", "pct", "ratio", "days"]
    period: AnalysisPeriod
    filters: dict = Field(default_factory=dict)
    source: str
    computed_at: datetime
    data_as_of: datetime
    maturity_status: MaturityStatus
    formula_version: str = "1"
    metric_version: str = "1"
    relationship: Relationship = Relationship.OBSERVED


class Assumption(BaseModel):
    key: str
    statement: str


class DataQuality(BaseModel):
    status: DataQualityStatus
    warnings: list[str] = Field(default_factory=list)


class Comparison(BaseModel):
    label: str
    left_fact_id: str
    right_fact_id: str
    delta: Decimal
    delta_pct: Decimal | None = None


class DimensionBreakdown(BaseModel):
    """§5.1 — ONE independent decomposition of the total delta. Two
    decompositions are never summed together; every pack says so."""

    dimension: str  # product | channel | governorate | carrier | ...
    entries: list[DimensionEntry]
    note: str = "independent decomposition — do not sum across dimensions"


class DimensionEntry(BaseModel):
    key: str
    label: str | None = None
    delta: Decimal  # this entity's revenue delta; Σ over entries == total Δ
    bucket: Literal["existing", "new", "discontinued"]


class DriverResult(BaseModel):
    kind: Literal["orders_vs_aov"]
    orders_contribution: Decimal
    aov_contribution: Decimal
    total_delta: Decimal  # == orders_contribution + aov_contribution (exact)


DimensionBreakdown.model_rebuild()


class AnomalyResult(BaseModel):
    key: str
    observed: Decimal
    baseline: Decimal
    residual_z: float
    minimum_volume_ok: bool
    seasonality_checked: bool


class EvidencePack(BaseModel):
    """§8.1 — the immutable, content-hashed analytical record of one run."""

    question: str
    scope: dict = Field(default_factory=dict)
    periods: list[AnalysisPeriod] = Field(default_factory=list)
    facts: list[MetricFact] = Field(default_factory=list)
    comparisons: list[Comparison] = Field(default_factory=list)
    dimensions: list[DimensionBreakdown] = Field(default_factory=list)
    drivers: list[DriverResult] = Field(default_factory=list)
    anomalies: list[AnomalyResult] = Field(default_factory=list)
    data_quality: DataQuality
    assumptions: list[Assumption] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    content_hash: str | None = None  # SHA-256 over the canonical form


class Finding(BaseModel):
    """§9.1 — confidence is SYSTEM-computed (§9.3); the model never fills it."""

    statement: str
    type: Literal["FACT", "DERIVED", "DRIVER", "INTERPRETATION", "HYPOTHESIS"]
    relationship: Relationship
    evidence_refs: list[str] = Field(min_length=1)
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    confidence_reasons: list[str] = Field(default_factory=list)
    materiality: float = 0.0
    coverage_satisfied: bool = False


class Recommendation(BaseModel):
    """A suggestion to REVIEW — never an action (§10.5: read-only agent)."""

    text: str
    based_on_evidence: list[str] = Field(min_length=1)


class AnswerDraft(BaseModel):
    """§10.1 — the model's structured draft. Measured numbers appear ONLY as
    placeholders bound to fact ids; the system renders and validates them."""

    text: str
    findings: list[Finding]
    recommendations: list[Recommendation] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    clarification: str | None = None


class CapabilityCost(BaseModel):
    """§4.1 — what an investigation cost the store's database."""

    rows_scanned: int = 0
    duration_ms: int = 0


class CapabilityResult(BaseModel):
    """§4.1 — every capability returns this shape. Status is honest:
    unsupported/no_data are VALID outcomes naming their reason."""

    capability: str
    status: Literal["ok", "partial", "unsupported", "no_data", "error"]
    evidence_ids: list[str] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    data_quality: DataQuality
    limitations: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    cost: CapabilityCost = Field(default_factory=CapabilityCost)


class Outcome(StrEnum):
    """§2.5 — terminal outcomes are VALID results, not failures."""

    ANSWERED = "ANSWERED"
    NO_CLEAR_EXPLANATION = "NO_CLEAR_EXPLANATION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    IMMATURE_DATA = "IMMATURE_DATA"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    UNSUPPORTED_ANALYSIS = "UNSUPPORTED_ANALYSIS"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class AnalysisRun(BaseModel):
    """§15 — the reproducibility record: every version that touched the
    answer, pinned. A run must be replayable from its snapshot."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    question: str
    status: str = "COMPLETED"
    started_at: datetime
    completed_at: datetime | None = None
    agent_version: str = "1"
    model: str
    provider: str
    prompt_version: str = "1"
    metric_registry_version: str = "1"
    formula_versions: dict[str, str] = Field(default_factory=dict)
    coverage_profile_version: str = "v1"
    confidence_ruleset_version: str = "v1"
    number_policy_version: str = "v1"
    timezone: str
    currency: str
    scope: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)
    data_cutoff: datetime | None = None
    data_as_of: datetime | None = None
    result: dict = Field(default_factory=dict)
    trace_id: str | None = None
