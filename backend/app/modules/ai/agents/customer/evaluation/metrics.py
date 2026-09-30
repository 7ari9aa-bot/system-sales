"""Corpus metrics (spec §21) — how the vision stack is JUDGED.

Pure math over labelled pipeline outcomes. The M1 acceptance is this table:
top-1/top-3 with and without the reranker, and out-of-catalog honesty — an
image of nothing we sell must come back unconfident, never a committed
guess. ``propose_thresholds`` turns the observed score distributions into
the measured numbers that will REPLACE the placeholders in
vision/thresholds.py — the corpus run decides, the code change is a commit
that records it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.ai.agents.customer.vision.thresholds import VisionThresholds


@dataclass(slots=True)
class CaseResult:
    """One labelled corpus image through the pipeline.

    ``label_product_id`` None means an out-of-catalog image. The ranked ids
    follow the FINAL order (rerank order when the reranker ran, embedding
    order otherwise) with ``scores`` aligned to them (empty when the
    reranker did not run).
    """

    label_product_id: str | None
    ranked_product_ids: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    # Out-of-catalog AND the engine committed anyway (HIGH) — the one rate
    # this whole stack exists to hold at ~0.
    confident_wrong: bool = False


def hit_at_k(cases: list[CaseResult], k: int) -> float:
    """Top-k accuracy over IN-CATALOG cases; labelled-None rows excluded."""
    relevant = [c for c in cases if c.label_product_id is not None]
    if not relevant:
        return 0.0
    hits = sum(
        1 for c in relevant if c.label_product_id in c.ranked_product_ids[:k]
    )
    return hits / len(relevant)


def out_of_catalog_honesty(
    cases: list[CaseResult], thresholds: VisionThresholds | None = None
) -> float:
    """Share of out-of-catalog images the engine did NOT confidently match.

    Honest means: no candidates at all, or a top score under the rerank
    floor (the engine's own "below this nothing is credible" line).
    """
    t = thresholds or VisionThresholds.DEFAULT
    foreign = [c for c in cases if c.label_product_id is None]
    if not foreign:
        return 0.0
    honest = 0
    for case in foreign:
        top = case.scores[0] if case.scores else 0.0
        if not case.ranked_product_ids or top < t.rerank_floor:
            honest += 1
    return honest / len(foreign)


def confident_wrong_rate(cases: list[CaseResult]) -> float:
    """The governing metric: out-of-catalog images read as HIGH — held at ~0."""
    foreign = [c for c in cases if c.label_product_id is None]
    if not foreign:
        return 0.0
    return sum(1 for c in foreign if c.confident_wrong) / len(foreign)


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated quantile over an ASC-sorted list; 0.0 when empty."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def propose_thresholds(cases: list[CaseResult]) -> dict[str, float]:
    """Measured §12.2 factors from the corpus.

    * ``high_floor``: the 10th percentile of CORRECT top-1 scores — most
      true matches clear it, so anything below is honestly not a HIGH.
    * ``gap_min``: the 10th percentile of the correct top1−top2 gaps.
    * ``rerank_floor``: the midpoint between the strongest foreign image
      and the weakest correct match — the credibility line between the two
      populations. When the foreign ceiling sits ABOVE the correct floor,
      the floor wins the middle honestly: matches there demote to MEDIUM
      rather than risk a confident wrong.
    """
    correct = [
        c
        for c in cases
        if c.label_product_id is not None
        and c.ranked_product_ids
        and c.ranked_product_ids[0] == c.label_product_id
    ]
    correct_tops = sorted(c.scores[0] for c in correct if c.scores)
    correct_gaps = sorted(
        c.scores[0] - c.scores[1] for c in correct if len(c.scores) > 1
    )
    foreign_tops = sorted(
        (
            c.scores[0]
            for c in cases
            if c.label_product_id is None and c.scores
        ),
        reverse=True,
    )

    high_floor = max(_quantile(correct_tops, 0.10), 0.0)
    gap_min = max(_quantile(correct_gaps, 0.10), 0.0)
    foreign_ceiling = foreign_tops[0] if foreign_tops else 0.0
    rerank_floor = (foreign_ceiling + high_floor) / 2 if correct_tops else 0.0
    return {
        "high_floor": round(high_floor, 3),
        "gap_min": round(gap_min, 3),
        "rerank_floor": round(max(rerank_floor, 0.0), 3),
    }
