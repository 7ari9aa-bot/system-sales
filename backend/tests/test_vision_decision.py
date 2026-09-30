"""Vision Decision Engine tests (spec §12.2) — pure logic, no database.

The matrix pins the four factors' interaction, including the non-negotiable:
a failed or absent reranker is NEVER HIGH, whatever the scores look like.
"""

from __future__ import annotations

import uuid

from app.modules.ai.agents.customer.vision.decision import ScoredCandidate, decide
from app.modules.ai.agents.customer.vision.schemas import Candidate, Confidence
from app.modules.ai.agents.customer.vision.thresholds import VisionThresholds

_T = VisionThresholds.DEFAULT


def _candidate(rank: int) -> Candidate:
    return Candidate(
        product_id=uuid.uuid4(),
        product_title=f"Product {rank}",
        image_id=uuid.uuid4(),
        image_url=f"https://cdn.test/{rank}.png",
        retrieval_rank=rank,
    )


def _scored(score: float, rank: int) -> ScoredCandidate:
    return ScoredCandidate(candidate=_candidate(rank), score=score, embedding_rank=rank)


async def test_no_candidates_is_low():
    confidence, reason = decide([], reranker_ok=True)
    assert confidence is Confidence.LOW
    assert reason == "no_candidates"


async def test_reranker_down_is_never_high_even_with_a_perfect_score():
    # §12.2: the embedding top-k is a pre-filter, not a verifier — with the
    # reranker down the best it may say is MEDIUM, whatever the score is.
    confidence, reason = decide([_scored(0.99, 1), _scored(0.10, 2)], reranker_ok=False)
    assert confidence is Confidence.MEDIUM
    assert reason == "reranker_unavailable"


async def test_below_rerank_floor_is_low():
    confidence, reason = decide([_scored(_T.rerank_floor - 0.01, 1)], reranker_ok=True)
    assert confidence is Confidence.LOW
    assert reason == "below_rerank_floor"


async def test_high_requires_floor_gap_and_agreement():
    # Exactly at every floor: top-1 clears high_floor, beats top-2 by the
    # minimum gap, and sits inside the embedding's top-N — all three hold.
    confidence, reason = decide(
        [_scored(_T.high_floor, 1), _scored(_T.high_floor - _T.gap_min, 2)],
        reranker_ok=True,
    )
    assert confidence is Confidence.HIGH
    assert reason == "clear_match"


async def test_gap_failure_never_reaches_high():
    # Top-1 clears the floor but beats top-2 by LESS than the minimum gap:
    # the two best candidates are too close to call, whatever the score is.
    too_close = _T.gap_min - 0.01
    confidence, reason = decide(
        [_scored(_T.high_floor, 1), _scored(_T.high_floor - too_close, 2)],
        reranker_ok=True,
    )
    assert confidence is Confidence.MEDIUM
    assert reason == "close_alternatives"


async def test_high_blocked_when_winner_outside_embedding_top_n():
    # Strong score and a wide gap, but the embedding retriever ranked the
    # winner outside its top-N: the two retrievers disagree, so not HIGH.
    confidence, reason = decide(
        [_scored(_T.high_floor, _T.agreement_top_n + 1), _scored(0.10, 2)],
        reranker_ok=True,
    )
    assert confidence is Confidence.MEDIUM
    assert reason == "reranker_embedding_disagreement"


async def test_mid_score_without_close_second_stays_medium():
    # Above the rerank floor, below the high floor, no close second: the
    # honest reading is "unconfirmed match" — MEDIUM, not HIGH.
    mid = (_T.rerank_floor + _T.high_floor) / 2
    confidence, reason = decide([_scored(mid, 1), _scored(0.05, 2)], reranker_ok=True)
    assert confidence is Confidence.MEDIUM
    assert reason == "unconfirmed_match"


async def test_single_candidate_gap_is_the_full_score_width():
    # No top-2: the gap is the whole score, so floor + agreement decide.
    confidence, reason = decide([_scored(_T.high_floor, 1)], reranker_ok=True)
    assert confidence is Confidence.HIGH
    assert reason == "clear_match"

    confidence, reason = decide(
        [_scored(_T.high_floor, _T.agreement_top_n + 1)], reranker_ok=True
    )
    assert confidence is Confidence.MEDIUM
    assert reason == "reranker_embedding_disagreement"
