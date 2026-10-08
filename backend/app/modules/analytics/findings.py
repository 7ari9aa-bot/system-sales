"""Findings builder (spec §9) — facts become claims under guard.

The builder is deterministic: every claim cites evidence, the confidence
engine (not the model) grades it, and the causality validator has the final
word. Materiality ranks findings; the top-N cap (≤3 primary) lives here.
"""

from __future__ import annotations

from app.modules.analytics.capabilities import EvidenceStore
from app.modules.analytics.confidence import compute_confidence
from app.modules.analytics.contracts import (
    AnalysisPeriod,
    Finding,
    Relationship,
)
from app.modules.analytics.validators import validate_finding

PRIMARY_CAP = 3


def _fact_period(fact) -> AnalysisPeriod:
    return fact.period


def build_findings(
    store: EvidenceStore,
    *,
    maturity_status=None,
    sample_size: int | None = None,
    data_stale: bool | None = None,
) -> list[Finding]:
    """Comparisons become change findings; drivers become driver findings.

    P1-21: Computes actual sample size and data freshness from evidence facts
    rather than relying on hardcoded defaults.
    """
    if sample_size is None:
        counts = [
            int(f.value)
            for f in store.facts.values()
            if getattr(f, "unit", "") in ("orders", "count", "customers", "shipments")
            and getattr(f, "value", None) is not None
            and f.value > 0
        ]
        sample_size = max(counts) if counts else (len(store.facts) * 10 or 100)

    if data_stale is None:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        is_stale = False
        for f in store.facts.values():
            as_of = getattr(f, "data_as_of", None)
            if as_of and (now - as_of) > timedelta(hours=36):
                is_stale = True
                break
        data_stale = is_stale

    findings: list[Finding] = []

    for _ref, comparison in store.comparisons.items():
        if comparison.delta_pct is None:
            continue
        left = store.facts[comparison.left_fact_id]
        direction = "زاد" if comparison.delta > 0 else "انخفض"
        statement = (
            f"{comparison.label}: القيمة {direction} بمقدار {abs(comparison.delta_pct):.1f}%"
        )
        level, reasons = compute_confidence(
            finding_type="DERIVED",
            relationship=Relationship.OBSERVED,
            maturity_status=maturity_status or left.maturity_status,
            sample_size=sample_size,
            data_stale=data_stale,
        )
        finding = Finding(
            statement=statement,
            type="DERIVED",
            relationship=Relationship.OBSERVED,
            evidence_refs=[comparison.left_fact_id, comparison.right_fact_id],
            confidence=level,
            confidence_reasons=reasons,
            materiality=abs(float(comparison.delta)),
            coverage_satisfied=False,
        )
        if not validate_finding(finding):
            findings.append(finding)

    for ref, driver in store.drivers.items():
        dominant = (
            "عدد الطلبات"
            if abs(driver.orders_contribution) >= abs(driver.aov_contribution)
            else "متوسط قيمة الطلب"
        )
        statement = (
            f"التغير في {dominant} هو المكوّن الأكبر في تغير الإيراد "
            f"({driver.orders_contribution + driver.aov_contribution})"
        )
        level, reasons = compute_confidence(
            finding_type="DRIVER",
            relationship=Relationship.OBSERVED,
            maturity_status=maturity_status or next(iter(store.facts.values())).maturity_status,
            sample_size=sample_size,
            data_stale=data_stale,
        )
        finding = Finding(
            statement=statement,
            type="DRIVER",
            relationship=Relationship.OBSERVED,
            evidence_refs=[ref],
            confidence=level,
            confidence_reasons=reasons,
            materiality=abs(float(driver.total_delta)),
            coverage_satisfied=False,
        )
        if not validate_finding(finding):
            findings.append(finding)

    findings.sort(key=lambda f: -f.materiality)
    return findings[:PRIMARY_CAP]
