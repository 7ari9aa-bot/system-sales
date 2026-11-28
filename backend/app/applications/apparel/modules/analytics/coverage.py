"""Coverage requirements (spec §2.3) — a FLOOR per question family.

The agent chooses the path and the depth; the controller only guarantees
that the minimum evidence for the family EXISTS before the answer. Profiles
are versioned config data — bump the version when a family's floor changes,
and every run records which version judged it.
"""

from __future__ import annotations

from dataclasses import dataclass

PROFILES_VERSION = "v1"

#: family → the evidence types that MUST exist before the final answer.
COVERAGE_PROFILES: dict[str, tuple[str, ...]] = {
    "change_explanation": (
        "period_maturity",
        "orders_aov_decomposition",
        "seasonality_check",
        "sample_size_check",
    ),
    "period_comparison": (
        "period_normalization",
        "maturity",
        "deltas",
    ),
    "top_bottom_entities": (
        "metric_definition",
        "period",
        "minimum_volume",
    ),
    "anomaly": (
        "seasonal_baseline",
        "materiality",
        "dedupe",
    ),
}


@dataclass(frozen=True, slots=True)
class CoverageVerdict:
    family: str
    satisfied: bool
    missing: tuple[str, ...]


def missing_coverage(family: str, satisfied: set[str]) -> CoverageVerdict:
    """What the family's floor still needs; unknown families fail open? No —
    fail CLOSED: an unrecognized family has no defined floor, so the answer
    must carry an explicit limitation instead of passing silently."""
    required = COVERAGE_PROFILES.get(family)
    if required is None:
        return CoverageVerdict(
            family=family,
            satisfied=False,
            missing=("<unknown family — no coverage profile>",),
        )
    missing = tuple(item for item in required if item not in satisfied)
    return CoverageVerdict(family=family, satisfied=not missing, missing=missing)
