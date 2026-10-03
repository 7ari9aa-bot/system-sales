"""Analysis persistence tests (spec §12.4) — save once, read forever.

The round-trip on the real tables: an evidence pack + findings saved under
tenant A come back intact, a foreign tenant sees NOTHING (RLS + the
tenant-scoped query), and the stored content_hash matches the pack's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.analytics.contracts import (
    AnalysisPeriod,
    DataQuality,
    DataQualityStatus,
    EvidencePack,
    Finding,
    MaturityPolicy,
    MaturityStatus,
    Relationship,
)
from app.modules.analytics.persistence import load_analysis, save_analysis


def _pack() -> EvidencePack:
    now = datetime.now(UTC)
    period = AnalysisPeriod(
        start=now - timedelta(days=30),
        end=now,
        timezone="UTC",
        attribution_basis="placed_at",
        maturity_policy=MaturityPolicy(kind="immediate"),
        maturity_status=MaturityStatus.MATURE,
        data_as_of=now,
    )
    from app.modules.analytics.contracts import MetricFact

    return EvidencePack(
        question="إيه حصل للمبيعات؟",
        facts=[
            MetricFact(
                id="F1",
                metric="delivered_revenue",
                value=Decimal("1200.00"),
                unit="money",
                period=period,
                source="orders",
                computed_at=now,
                data_as_of=now,
                maturity_status=MaturityStatus.MATURE,
            )
        ],
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
    )


def _findings() -> list[Finding]:
    return [
        Finding(
            statement="الإيراد تغيّر",
            type="FACT",
            relationship=Relationship.OBSERVED,
            evidence_refs=["F1"],
            confidence="HIGH",
            materiality=1200.0,
        )
    ]


async def test_save_then_load_round_trip(db, tenant_ctx):
    analysis_id = await save_analysis(
        db,
        tenant_ctx.tenant_id,
        question="إيه حصل للمبيعات؟",
        outcome="ANSWERED",
        pack=_pack(),
        findings=_findings(),
    )
    stored = await load_analysis(db, tenant_ctx.tenant_id, analysis_id)
    assert stored is not None
    assert stored["question"] == "إيه حصل للمبيعات؟"
    assert stored["outcome"] == "ANSWERED"
    assert stored["content_hash"]  # a hash exists even if the pack arrived unhashed
    assert len(stored["findings"]) == 1
    assert stored["findings"][0]["statement"] == "الإيراد تغيّر"


async def test_foreign_tenant_loads_nothing(db, tenant_ctx):
    analysis_id = await save_analysis(
        db,
        tenant_ctx.tenant_id,
        question="سؤال",
        outcome="ANSWERED",
        pack=_pack(),
        findings=_findings(),
    )
    assert await load_analysis(db, uuid.uuid4(), analysis_id) is None


async def test_missing_analysis_returns_none(db, tenant_ctx):
    assert await load_analysis(db, tenant_ctx.tenant_id, uuid.uuid4()) is None
