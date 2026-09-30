"""Vision Decision Engine (spec §12.2) — confidence from the four factors.

Pure logic, no I/O: the pipeline hands it the reranked candidates (score
descending, caller-order indexes already mapped back by reranker.py) plus
each candidate's embedding rank, and gets back one Confidence plus a short
reason. Non-negotiable (§12.2): a failed or absent reranker means NEVER HIGH
— the embedding top-k is a pre-filter, not a verifier, so its order alone
must not read as a confident match.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.ai.agents.customer.vision.schemas import Candidate, Confidence
from app.modules.ai.agents.customer.vision.thresholds import VisionThresholds


@dataclass(slots=True)
class ScoredCandidate:
    """One candidate with its rerank score and its 1-based embedding rank."""

    candidate: Candidate
    score: float
    embedding_rank: int


def decide(
    scored: list[ScoredCandidate],
    *,
    reranker_ok: bool,
    thresholds: VisionThresholds | None = None,
) -> tuple[Confidence, str]:
    """(confidence, reason) for one image match.

    ``scored`` must be ordered best-first (RerankerProvider enforces that).
    ``embedding_rank`` is the candidate's position in the retrieval order,
    1-based — the agreement factor reads it, never the score.
    """
    t = thresholds or VisionThresholds.DEFAULT
    if not scored:
        return Confidence.LOW, "no_candidates"
    top = scored[0]
    if not reranker_ok:
        # §12.2: HIGH requires a live reranker. With it down, the embedding
        # pre-filter is all we have — present with uncertainty, never HIGH.
        return Confidence.MEDIUM, "reranker_unavailable"
    if top.score < t.rerank_floor:
        return Confidence.LOW, "below_rerank_floor"

    top2 = scored[1].score if len(scored) > 1 else None
    gap = top.score - top2 if top2 is not None else top.score
    agrees = top.embedding_rank <= t.agreement_top_n

    if top.score >= t.high_floor and gap >= t.gap_min and agrees:
        return Confidence.HIGH, "clear_match"
    if top2 is not None and (top.score - top2) <= t.medium_band:
        return Confidence.MEDIUM, "close_alternatives"
    if top.score >= t.high_floor:
        # A rerank score the embedding retriever does not back: the two
        # retrievers disagree, so the match is presentable but not clean.
        return Confidence.MEDIUM, "reranker_embedding_disagreement"
    return Confidence.MEDIUM, "unconfirmed_match"
