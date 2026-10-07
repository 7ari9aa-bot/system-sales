"""Maturity, numbers, confidence, validators, coverage — the guarantee layer.

Each test pins one rule a merchant will rely on: an unmeasured period never
reads as final, digits belong to the system and not the model, hypotheses
never reach HIGH, temporal association never reads as cause, and a number
the renderer did not produce is a rejection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.analytics.confidence import compute_confidence
from app.modules.analytics.contracts import (
    AnswerDraft,
    Finding,
    MaturityStatus,
    Relationship,
)
from app.modules.analytics.coverage import missing_coverage
from app.modules.analytics.maturity import maturity_status
from app.modules.analytics.numbers import NumberPolicy, free_numerals, render_answer
from app.modules.analytics.validators import validate_finding, validate_response

# ------------------------------------------------------------- maturity ---


def test_maturity_three_states_from_the_ratio():
    assert maturity_status(0.99) is MaturityStatus.MATURE
    assert maturity_status(0.5) is MaturityStatus.PARTIALLY_MATURE
    assert maturity_status(0.2) is MaturityStatus.IMMATURE


def test_unknown_curve_degrades_down_never_up():
    assert maturity_status(None) is MaturityStatus.PARTIALLY_MATURE


def test_maturity_ratio_outside_unit_interval_fails():
    with pytest.raises(ValueError):
        maturity_status(1.2)


# -------------------------------------------------------------- numbers ---


def _fact(value: str, fact_id: str = "F1") -> object:
    from datetime import timedelta

    from app.modules.analytics.contracts import AnalysisPeriod, MetricFact

    now = datetime(2026, 10, 1, tzinfo=UTC)
    return MetricFact(
        id=fact_id,
        metric="delivered_revenue",
        value=Decimal(value),
        unit="money",
        period=AnalysisPeriod(
            start=now - timedelta(days=30),
            end=now,
            timezone="Africa/Cairo",
            attribution_basis="placed_at",
            maturity_policy={"kind": "immediate"},
            maturity_status=MaturityStatus.MATURE,
            data_as_of=now,
        ),
        source="orders",
        computed_at=now,
        data_as_of=now,
        maturity_status=MaturityStatus.MATURE,
    )


def test_render_money_placeholder():
    rendered, problems = render_answer("المبيعات {{F1:money}}", {"F1": _fact("123456.78")})
    assert problems == []
    assert "123,457 EGP" in rendered


def test_render_delta_pct_with_sign():
    rendered, problems = render_answer("التغير {{F1:delta_pct}}", {"F1": _fact("-12.4")})
    assert problems == []
    assert "−12.4%" in rendered


def test_unresolved_placeholder_is_a_problem_not_invented_number():
    rendered, problems = render_answer("المبيعات {{F9:money}}", {"F1": _fact("5")})
    assert "{{F9:money}}" in rendered  # the hole stays a hole
    assert any("unresolved placeholder" in p for p in problems)


def test_arabic_indic_script_policy():
    policy = NumberPolicy(digit_script="arabic_indic")
    rendered, _problems = render_answer("عدد {{F1:int}}", {"F1": _fact("1250")}, policy)
    assert "١,٢٥٠" in rendered


def test_free_numerals_found_after_render():
    # The renderer produced "123,457 EGP"; a stray "99" the model typed is
    # NOT part of any rendered number and must be caught.
    rendered, _problems = render_answer(
        "المبيعات {{F1:money}} وخصم 99 جنيه", {"F1": _fact("123456.78")}
    )
    assert "99" in free_numerals(rendered)
    assert free_numerals("أول أسبوعين تقريبا نص") == []


# ----------------------------------------------------------- confidence ---


def test_confidence_caps_table():
    base = dict(
        finding_type="FACT",
        relationship=Relationship.OBSERVED,
        maturity_status=MaturityStatus.MATURE,
        sample_size=500,
    )
    level, _reasons = compute_confidence(**base)
    assert level == "HIGH"

    level, reasons = compute_confidence(**{**base, "maturity_status": MaturityStatus.IMMATURE})
    assert level == "LOW" and any("IMMATURE" in r for r in reasons)

    level, reasons = compute_confidence(
        **{**base, "relationship": Relationship.TEMPORAL_ASSOCIATION}
    )
    assert level == "MEDIUM" and any("temporal" in r for r in reasons)

    level, _reasons = compute_confidence(**{**base, "sample_size": 5})
    assert level == "LOW"

    # Downgrades stack on top of caps.
    level, reasons = compute_confidence(
        **{
            **base,
            "maturity_status": MaturityStatus.PARTIALLY_MATURE,
            "data_stale": True,
        }
    )
    assert level == "LOW" and any("STALE" in r for r in reasons)


def test_hypothesis_is_never_high_even_on_perfect_data():
    level, reasons = compute_confidence(
        finding_type="HYPOTHESIS",
        relationship=Relationship.OBSERVED,
        maturity_status=MaturityStatus.MATURE,
        sample_size=1000,
    )
    assert level == "MEDIUM" and reasons


# ----------------------------------------------------------- validators ---


def _finding(**overrides) -> Finding:
    base = dict(
        statement="الإيراد انخفض",
        type="FACT",
        relationship=Relationship.OBSERVED,
        evidence_refs=["F1"],
        confidence="HIGH",
    )
    return Finding(**{**base, **overrides})


def test_causal_wording_requires_causal_relationship():
    finding = _finding(
        statement="نفاد المخزون سبب مباشر في الانخفاض",
        relationship=Relationship.TEMPORAL_ASSOCIATION,
    )
    problems = validate_finding(finding)
    assert any("CAUSAL" in p for p in problems)


def test_association_must_hedge():
    finding = _finding(
        statement="نفاد المخزون تزامن مع الانخفاض وقد يكون ساهم",
        relationship=Relationship.TEMPORAL_ASSOCIATION,
    )
    assert validate_finding(finding) == []


def test_hypothesis_phrasing_enforced():
    finding = _finding(
        statement="التغير بسبب الحملة",
        type="HYPOTHESIS",
        relationship=Relationship.CORRELATION,
        confidence="MEDIUM",
    )
    problems = validate_finding(finding)
    assert any("hypotheses" in p for p in problems)


def test_response_validator_catches_free_numbers_and_survivors():
    draft = AnswerDraft(text="x", findings=[])
    problems = validate_response(draft, "المبيعات 123,457 EGP وخصم {{F2:money}}")
    assert any("free number" in p for p in problems)
    assert any("unrendered placeholder" in p for p in problems)


def test_response_validator_blocks_high_confidence_hypothesis():
    draft = AnswerDraft(
        text="x",
        findings=[_finding(type="HYPOTHESIS", confidence="HIGH")],
    )
    problems = validate_response(draft, "نص بدون أرقام")
    assert any("HYPOTHESIS" in p for p in problems)


# ------------------------------------------------------------- coverage ---


def test_coverage_floor_per_family():
    verdict = missing_coverage(
        "change_explanation",
        {"period_maturity", "orders_aov_decomposition"},
    )
    assert not verdict.satisfied
    assert set(verdict.missing) == {"seasonality_check", "sample_size_check"}

    full = missing_coverage(
        "change_explanation",
        {"period_maturity", "orders_aov_decomposition", "seasonality_check", "sample_size_check"},
    )
    assert full.satisfied and full.missing == ()


def test_unknown_family_fails_closed():
    verdict = missing_coverage("telepathy", set())
    assert not verdict.satisfied and "no coverage profile" in verdict.missing[0]
