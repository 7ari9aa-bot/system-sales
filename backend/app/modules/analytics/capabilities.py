"""Capabilities (spec §4) — the typed functions the agent may call.

Each capability wraps the compiler/engines and returns ONE shape
(CapabilityResult): honest status, evidence ids, a compact model-facing
summary, data quality, limitations, and cost. tenant_id arrives from the
run context as a parameter of these functions — it is NEVER the model's
argument. Capabilities are tools the agent may choose, not a workflow:
nothing here hard-codes an investigation sequence.

Evidence lives in ``evidence.py``'s store — capabilities register their
facts there and pass ids back, so the model sees summaries + ids only.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.compiler import compute_breakdown, compute_fact
from app.modules.analytics.contracts import (
    AnalysisPeriod,
    CapabilityCost,
    CapabilityResult,
    Comparison,
    DataQuality,
    DataQualityStatus,
    DriverResult,
    MaturityPolicy,
    MaturityStatus,
    MetricFact,
)
from app.modules.analytics.drivers import orders_vs_aov
from app.modules.analytics.semantic import StoreMetricProfile, metric


@dataclass(slots=True)
class EvidenceStore:
    """The run's evidence registry: facts in, ids out (§3.5)."""

    facts: dict[str, MetricFact] = field(default_factory=dict)
    comparisons: dict[str, Comparison] = field(default_factory=dict)
    drivers: dict[str, DriverResult] = field(default_factory=dict)
    _seq: int = 0

    def add_fact(self, fact: MetricFact) -> str:
        self._seq += 1
        registered = fact.model_copy(update={"id": f"F{self._seq}"})
        self.facts[registered.id] = registered
        return registered.id

    def add_comparison(self, comparison: Comparison) -> str:
        self._seq += 1
        ref = f"C{self._seq}"
        self.comparisons[ref] = comparison
        return ref

    def add_driver(self, driver: DriverResult) -> str:
        self._seq += 1
        ref = f"D{self._seq}"
        self.drivers[ref] = driver
        return ref

    def facts_by_id(self) -> dict[str, MetricFact]:
        return dict(self.facts)


def _q(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places))


def _delta_pct(before: Decimal, after: Decimal) -> Decimal | None:
    if before == 0:
        return None  # a percentage against zero is undefined — never invented
    return _q((after - before) / before * 100)


def _period_window(reference: datetime, *, days: int) -> AnalysisPeriod:
    """§6.5 — the system resolves periods, never the model. v1 resolves a
    trailing N-day window ending 'yesterday' in the store timezone (UTC v1):
    today is immature for delivered-based metrics by definition."""
    end = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    return AnalysisPeriod(
        start=start,
        end=end,
        timezone="UTC",
        attribution_basis="placed_at",
        maturity_policy=MaturityPolicy(kind="immediate"),
        maturity_status=MaturityStatus.PARTIALLY_MATURE,
        data_as_of=reference,
    )


@dataclass(slots=True)
class CapabilityContext:
    """Everything a capability needs that the model must not provide."""

    tenant_id: uuid.UUID
    profile: StoreMetricProfile = field(default_factory=StoreMetricProfile)


async def get_metric(
    session: AsyncSession,
    context: CapabilityContext,
    store: EvidenceStore,
    *,
    metric_name: str,
    period: AnalysisPeriod,
    channel: str | None = None,
) -> CapabilityResult:
    """One metric value for one period — the atomic investigative unit."""
    started = time.monotonic()
    metric(metric_name)  # unknown metric fails the request loudly
    fact = await compute_fact(
        session,
        context.tenant_id,
        metric_name,
        period,
        channel=channel,
        fact_id="F0",
    )
    fact_id = store.add_fact(fact)
    duration_ms = int((time.monotonic() - started) * 1000)
    status = "ok" if fact.value > 0 else "no_data"
    limitations = (
        [f"period {period.maturity_status.value.lower()} — numbers may still move"]
        if period.maturity_status is not MaturityStatus.MATURE
        else []
    )
    return CapabilityResult(
        capability=f"get_metric:{metric_name}",
        status=status,
        evidence_ids=[fact_id],
        summary={
            "value": str(fact.value),
            "unit": fact.unit,
            "period_start": period.start.date().isoformat(),
            "period_end": period.end.date().isoformat(),
        },
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        limitations=limitations,
        cost=CapabilityCost(
            rows_scanned=int(fact.value) if fact.unit == "count" else 0,
            duration_ms=duration_ms,
        ),
    )


async def compare_periods(
    session: AsyncSession,
    context: CapabilityContext,
    store: EvidenceStore,
    *,
    metric_name: str,
    days: int = 30,
) -> CapabilityResult:
    """This window vs the immediately preceding window of the SAME length."""
    started = time.monotonic()
    reference = datetime.now(UTC)
    current = _period_window(reference, days=days)
    previous = AnalysisPeriod(
        start=current.start - timedelta(days=days),
        end=current.start,
        timezone=current.timezone,
        attribution_basis=current.attribution_basis,
        maturity_policy=current.maturity_policy,
        maturity_status=MaturityStatus.MATURE,
        data_as_of=current.data_as_of,
    )
    current_fact = await compute_fact(
        session, context.tenant_id, metric_name, current, fact_id="F0"
    )
    previous_fact = await compute_fact(
        session, context.tenant_id, metric_name, previous, fact_id="F0"
    )
    current_id = store.add_fact(current_fact)
    previous_id = store.add_fact(previous_fact)
    comparison = Comparison(
        label=f"{metric_name}: last {days}d vs prior {days}d",
        left_fact_id=current_id,
        right_fact_id=previous_id,
        delta=_q(current_fact.value - previous_fact.value),
        delta_pct=_delta_pct(previous_fact.value, current_fact.value),
    )
    comparison_id = store.add_comparison(comparison)
    return CapabilityResult(
        capability=f"compare_periods:{metric_name}",
        status="ok",
        evidence_ids=[comparison_id, current_id, previous_id],
        summary={
            "current": str(current_fact.value),
            "previous": str(previous_fact.value),
            "delta": str(comparison.delta),
            "delta_pct": str(comparison.delta_pct)
            if comparison.delta_pct is not None
            else None,
        },
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        cost=CapabilityCost(duration_ms=int((time.monotonic() - started) * 1000)),
    )


async def breakdown_metric(
    session: AsyncSession,
    context: CapabilityContext,
    store: EvidenceStore,
    *,
    metric_name: str,
    dimension: str = "channel",
    days: int = 30,
) -> CapabilityResult:
    """One metric split by one dimension — an INDEPENDENT decomposition."""

    started = time.monotonic()
    period = _period_window(datetime.now(UTC), days=days)
    rows = await compute_breakdown(
        session, context.tenant_id, metric_name, period, dimension=dimension
    )
    is_money = metric(metric_name).semantic_type == "money"
    summary = {
        key: str(value if is_money else count) for key, value, count in rows
    }
    status = "ok" if rows else "no_data"
    return CapabilityResult(
        capability=f"breakdown_metric:{metric_name}:{dimension}",
        status=status,
        evidence_ids=[],
        summary={"dimension": dimension, "entries": summary},
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        limitations=["independent decomposition — never summed with other dimensions"],
        cost=CapabilityCost(duration_ms=int((time.monotonic() - started) * 1000)),
    )


async def analyze_drivers(
    session: AsyncSession,
    context: CapabilityContext,
    store: EvidenceStore,
    *,
    days: int = 30,
) -> CapabilityResult:
    """§5.1 — why did revenue move: orders vs AOV, midpoint, exact."""
    started = time.monotonic()
    reference = datetime.now(UTC)
    current = _period_window(reference, days=days)
    previous = AnalysisPeriod(
        start=current.start - timedelta(days=days),
        end=current.start,
        timezone=current.timezone,
        attribution_basis=current.attribution_basis,
        maturity_policy=current.maturity_policy,
        maturity_status=MaturityStatus.MATURE,
        data_as_of=current.data_as_of,
    )
    revenue_name = context.profile.primary_sales_metric

    orders_now = await compute_fact(
        session, context.tenant_id, "orders_placed", current, fact_id="F0"
    )
    orders_prev = await compute_fact(
        session, context.tenant_id, "orders_placed", previous, fact_id="F0"
    )
    revenue_now = await compute_fact(
        session, context.tenant_id, revenue_name, current, fact_id="F0"
    )
    revenue_prev = await compute_fact(
        session, context.tenant_id, revenue_name, previous, fact_id="F0"
    )
    for fact in (orders_now, orders_prev, revenue_now, revenue_prev):
        store.add_fact(fact)

    aov_now = (
        _q(revenue_now.value / orders_now.value)
        if orders_now.value
        else Decimal("0")
    )
    aov_prev = (
        _q(revenue_prev.value / orders_prev.value)
        if orders_prev.value
        else Decimal("0")
    )
    orders_part, aov_part, total = orders_vs_aov(
        orders_before=orders_prev.value,
        aov_before=aov_prev,
        orders_after=orders_now.value,
        aov_after=aov_now,
    )
    driver = DriverResult(
        kind="orders_vs_aov",
        orders_contribution=orders_part,
        aov_contribution=aov_part,
        total_delta=total,
    )
    driver_id = store.add_driver(driver)
    return CapabilityResult(
        capability="analyze_drivers",
        status="ok",
        evidence_ids=[driver_id],
        summary={
            "orders_contribution": str(orders_part),
            "aov_contribution": str(aov_part),
            "total_delta": str(total),
            "primary_metric": revenue_name,
        },
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        assumptions=[context.profile.as_assumption()],
        cost=CapabilityCost(duration_ms=int((time.monotonic() - started) * 1000)),
    )


def explain_metric(metric_name: str) -> CapabilityResult:
    """§4.2 — the definition, formula, version and lineage of one metric."""
    definition = metric(metric_name)  # unknown metric fails the request loudly
    return CapabilityResult(
        capability=f"explain_metric:{metric_name}",
        status="ok",
        evidence_ids=[],
        summary={
            "name": definition.name,
            "value_definition": definition.value_definition,
            "attribution_event": definition.attribution_event,
            "attribution_timestamp": definition.attribution_timestamp,
            "version": definition.version,
            "lineage": definition.lineage,
        },
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
    )


def get_data_status() -> CapabilityResult:
    """Freshness/maturity surface (§4.2) — v1: registry-level policies."""
    return CapabilityResult(
        capability="get_data_status",
        status="ok",
        evidence_ids=[],
        summary={
            "metrics": sorted(
                metric(n).name
                for n in ("orders_placed", "delivered_revenue", "collected_revenue")
            ),
            "maturity_curves": "not built yet — same-age comparisons pending history",
        },
        data_quality=DataQuality(
            status=DataQualityStatus.PARTIAL,
            warnings=["resolution curves pending order-status history accumulation"],
        ),
    )


def unknown_metric_metric_guard(metric_name: str) -> None:
    metric(metric_name)  # KeyError escapes loudly to the caller
