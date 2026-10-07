"""Corpus metrics tests (spec §21) — pure math on synthetic outcomes.

The numbers the acceptance table reads are computed HERE, so the math is
pinned on hand-built cases: hit rates, out-of-catalog honesty, the
confident-wrong rate, and the threshold proposal from score distributions.
"""

from __future__ import annotations

from app.modules.ai.agents.customer.evaluation.metrics import (
    CaseResult,
    confident_wrong_rate,
    hit_at_k,
    out_of_catalog_honesty,
    propose_thresholds,
)


def _hit(pid: str, score: float, second: tuple[str, float] | None = None) -> CaseResult:
    ranked = [pid] + ([second[0]] if second else [])
    scores = [score] + ([second[1]] if second else [])
    return CaseResult(label_product_id=pid, ranked_product_ids=ranked, scores=scores)


def _foreign(top_score: float | None, *, confident_wrong: bool = False) -> CaseResult:
    case = CaseResult(label_product_id=None)
    if top_score is not None:
        case = CaseResult(
            label_product_id=None,
            ranked_product_ids=["p-x"],
            scores=[top_score],
            confident_wrong=confident_wrong,
        )
    return case


def test_hit_at_k_counts_only_in_catalog_cases():
    cases = [
        _hit("p-1", 0.9),
        # label ranked SECOND: a top-1 miss that top-3 recovers
        CaseResult(
            label_product_id="p-2",
            ranked_product_ids=["p-3", "p-2"],
            scores=[0.9, 0.8],
        ),
        _foreign(0.2),  # out-of-catalog rows never dilute the accuracy
    ]
    assert hit_at_k(cases, 1) == 0.5
    assert hit_at_k(cases, 3) == 1.0
    assert hit_at_k([], 3) == 0.0


def test_out_of_catalog_honesty_uses_the_rerank_floor():
    cases = [
        _foreign(0.30),  # below the default floor 0.45 → honest
        _foreign(None),  # no candidates at all → honest
        _foreign(0.60),  # above the floor → NOT honest (presented a match)
    ]
    assert out_of_catalog_honesty(cases) == 2 / 3
    assert out_of_catalog_honesty([]) == 0.0


def test_confident_wrong_rate_is_the_governing_metric():
    cases = [_foreign(0.9, confident_wrong=True), _foreign(0.2)]
    assert confident_wrong_rate(cases) == 0.5
    assert confident_wrong_rate([_foreign(0.2)]) == 0.0
    assert confident_wrong_rate([]) == 0.0


def test_propose_thresholds_from_distributions():
    correct = [
        _hit(f"p-{i}", s, ("p-other", s - 0.30))
        for i, s in enumerate([0.90, 0.88, 0.86, 0.84, 0.82, 0.80, 0.78, 0.76, 0.74, 0.72])
    ]
    foreign = [_foreign(0.30), _foreign(0.25), _foreign(0.10)]
    proposed = propose_thresholds(correct + foreign)

    # The 10th percentile of the correct tops: between 0.72 and 0.74.
    assert 0.71 <= proposed["high_floor"] <= 0.74
    # Gaps are all 0.30 → the proposed gap_min is exactly that.
    assert proposed["gap_min"] == 0.3
    # The credibility line sits midway between the foreign ceiling and the
    # measured high floor.
    assert proposed["rerank_floor"] == round((0.30 + proposed["high_floor"]) / 2, 3)


def test_propose_thresholds_with_no_usable_data_is_safe():
    assert propose_thresholds([]) == {"high_floor": 0.0, "gap_min": 0.0, "rerank_floor": 0.0}
    only_foreign = [_foreign(0.5)]
    assert propose_thresholds(only_foreign)["high_floor"] == 0.0
