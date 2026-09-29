"""Vision Decision Engine thresholds (spec §12.2).

The numbers below are INITIAL placeholders, not calibrated values — spec
§12.2 and §23.7 require them to be measured on the labelled image corpus
(200-500 real photos, including out-of-catalog images that must yield "not
found") before production traffic. The dataclass exists so calibration is a
config change, not a code change; the corpus run lands them in one commit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VisionThresholds:
    """Factors 1-3 of §12.2 (absolute score, top1-top2 gap, embedding-rerank
    agreement). Factor 4 (attribute consistency) joins when the indexer's
    product_attributes land."""

    # Top-1 rerank score must clear this for HIGH at all.
    high_floor: float = 0.62
    # Top-1 must beat top-2 by at least this margin for HIGH.
    gap_min: float = 0.04
    # Below this, no candidate is credible enough to even discuss.
    rerank_floor: float = 0.45
    # Candidates within this band of top-1 read as "close alternatives".
    medium_band: float = 0.10
    # Embedding agreement: the reranked winner must sit in the embedding's
    # top-N for the two retrievers to count as agreeing.
    agreement_top_n: int = 3

    DEFAULT: "VisionThresholds" = None  # set below; frozen dataclass singleton


VisionThresholds.DEFAULT = VisionThresholds()
