"""Confidence engine (spec §9.3) — the SYSTEM scores confidence, never the LLM.

Explicit rules with hard caps first; calibrate later with eval + real
feedback. The ruleset is versioned and stored on every run (AnalysisRun).
The output is (level, reasons) — the reasons travel with the finding so a
downgrade is never a mystery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.modules.analytics.contracts import MaturityStatus, Relationship

Level = Literal["HIGH", "MEDIUM", "LOW"]
_ORDER: dict[Level, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_NAME = {v: k for k, v in _ORDER.items()}


@dataclass(frozen=True, slots=True)
class ConfidenceRuleset:
    version: str = "v1"
    minimum_sample: int = 30

    DEFAULT: ConfidenceRuleset | None = None  # set below


ConfidenceRuleset.DEFAULT = ConfidenceRuleset()


def _cap(level: Level, cap: Level, reasons: list[str], reason: str) -> Level:
    if _ORDER[level] > _ORDER[cap]:
        reasons.append(reason)
        return cap
    return level


def _downgrade(level: Level, reasons: list[str], reason: str) -> Level:
    lowered = _NAME[max(_ORDER[level] - 1, 0)]
    if lowered != level:
        reasons.append(reason)
    return lowered  # type: ignore[return-value]


def compute_confidence(
    *,
    finding_type: Literal["FACT", "DERIVED", "DRIVER", "INTERPRETATION", "HYPOTHESIS"],
    relationship: Relationship,
    maturity_status: MaturityStatus,
    sample_size: int,
    data_stale: bool = False,
    relies_on_reconstructed: bool = False,
    insufficient_baseline: bool = False,
    ruleset: ConfidenceRuleset | None = None,
) -> tuple[Level, list[str]]:
    """Start HIGH, then apply the caps and downgrades in §9.3's table.

    Order matters and is deliberate: the hard caps bound what the evidence
    CAN support; the downgrades then shave for quality problems. A HYPOTHESIS
    can never be HIGH — no cap ordering makes it one.
    """
    rules = ruleset or ConfidenceRuleset.DEFAULT
    reasons: list[str] = []
    level: Level = "HIGH"

    if sample_size < rules.minimum_sample:
        level = _cap(
            level,
            "LOW",
            reasons,
            f"sample below minimum ({sample_size} < {rules.minimum_sample})",
        )

    if maturity_status is MaturityStatus.PARTIALLY_MATURE:
        level = _cap(level, "MEDIUM", reasons, "period PARTIALLY_MATURE")
    elif maturity_status is MaturityStatus.IMMATURE:
        level = _cap(level, "LOW", reasons, "period IMMATURE")

    if relationship is Relationship.TEMPORAL_ASSOCIATION:
        level = _cap(level, "MEDIUM", reasons, "temporal association is not causation")

    if finding_type == "HYPOTHESIS":
        level = _cap(level, "MEDIUM", reasons, "hypotheses are never HIGH")

    if relies_on_reconstructed:
        level = _cap(level, "MEDIUM", reasons, "relies on reconstructed history")

    if data_stale:
        level = _downgrade(level, reasons, "data STALE — downgraded one level")

    if insufficient_baseline:
        level = _downgrade(level, reasons, "insufficient baseline history — downgraded one level")

    return level, reasons
