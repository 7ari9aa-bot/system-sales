"""Contracts tests — the typed vocabulary binds the way the spec says.

Every rule here is a guarantee a downstream validator will lean on: facts
carry their birth certificate, periods carry maturity, findings carry
system-computed confidence, evidence packs declare independent
decompositions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.analytics.contracts import (
    AnalysisPeriod,
    AnswerDraft,
    Finding,
    MaturityPolicy,
    MaturityStatus,
    MetricFact,
    Relationship,
)


def _period(**overrides) -> AnalysisPeriod:
    base = dict(
        start=datetime(2026, 9, 1, tzinfo=UTC),
        end=datetime(2026, 9, 30, tzinfo=UTC),
        timezone="Africa/Cairo",
        attribution_basis="placed_at",
        maturity_policy=MaturityPolicy(kind="carrier_curve", settle_days=7),
        maturity_status=MaturityStatus.PARTIALLY_MATURE,
        data_as_of=datetime(2026, 10, 1, tzinfo=UTC),
    )
    return AnalysisPeriod(**{**base, **overrides})


def _fact(**overrides) -> MetricFact:
    base = dict(
        id="F1",
        metric="delivered_revenue",
        value=Decimal("123456.78"),
        unit="money",
        period=_period(),
        source="orders",
        computed_at=datetime(2026, 10, 1, tzinfo=UTC),
        data_as_of=datetime(2026, 10, 1, tzinfo=UTC),
        maturity_status=MaturityStatus.PARTIALLY_MATURE,
        relationship=Relationship.OBSERVED,
    )
    return MetricFact(**{**base, **overrides})


def test_fact_carries_its_birth_certificate():
    fact = _fact()
    assert fact.metric_version == "1" and fact.formula_version == "1"
    assert fact.relationship is Relationship.OBSERVED
    assert fact.period.maturity_status is MaturityStatus.PARTIALLY_MATURE


def test_period_rejects_bogus_maturity_ratio():
    with pytest.raises(ValidationError):
        _period(maturity_ratio=1.5)


def test_finding_evidence_is_mandatory():
    with pytest.raises(ValidationError):
        Finding(
            statement="x",
            type="FACT",
            relationship=Relationship.OBSERVED,
            evidence_refs=[],
        )


def test_answer_draft_placeholders_live_in_text_not_findings():
    draft = AnswerDraft(
        text="المبيعات {{F1:money}}",
        findings=[
            Finding(
                statement="الإيراد اتغير",
                type="FACT",
                relationship=Relationship.OBSERVED,
                evidence_refs=["F1"],
                confidence="MEDIUM",
            )
        ],
    )
    assert "{{F1:money}}" in draft.text
    assert draft.findings[0].confidence == "MEDIUM"


def test_metric_definition_is_an_execution_contract_not_a_dictionary():
    from app.modules.analytics.contracts import MetricDefinition

    definition = MetricDefinition(
        name="delivered_revenue",
        description="Collected-when-delivered revenue",
        semantic_type="money",
        value_definition="sum of delivered order totals",
        attribution_event="delivered",
        attribution_timestamp="delivered_at",
        lifecycle_filter=["delivered"],
        maturity_policy=MaturityPolicy(kind="carrier_curve", settle_days=7),
        dimensions_allowed=["product", "channel", "governorate"],
        source="orders",
        version="1",
    )
    assert definition.attribution_event == "delivered"
    assert definition.currency_policy == "single"
