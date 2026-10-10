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

import hashlib
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
from app.modules.analytics.engines import (
    customer_split,
    fulfillment_by_carrier,
    seasonality_explains,
    weekday_profile,
)
from app.modules.analytics.semantic import (
    StoreMetricProfile,
    metric,
)
from app.modules.analytics.semantic import (
    load_store_metric_profile as load_store_metric_profile,
)


def _fact_identity(fact: MetricFact) -> str:
    """A content id: metric + unit + window + filters, digest-trimmed.

    P1-12 — every SI tool call builds its OWN store, and the run merges those
    stores into one pack. Positional ids ("F1", "F2") restarted inside each
    call, so the second call's "F1" silently replaced the first call's
    different measurement in the merged dict, and the model was shown two
    different facts under one name. A content key is unique per measurement.

    The VALUE is deliberately not part of the key: re-measuring the same
    window is the same fact (one entry, latest value), while a different
    window, channel filter or unit is a different fact. The charset is
    `[A-Za-z0-9_]` because `{{fact_id:format}}` placeholders are parsed with
    exactly that pattern (§10.1).
    """
    window = f"{fact.period.start:%Y%m%d%H}-{fact.period.end:%Y%m%d%H}"
    filters = "|".join(f"{k}={v}" for k, v in sorted((fact.filters or {}).items()))
    digest = hashlib.sha256(
        f"{fact.metric}|{fact.unit}|{window}|{filters}".encode()
    ).hexdigest()
    return f"{fact.metric}_{digest[:8]}"


@dataclass(slots=True)
class EvidenceStore:
    """The run's evidence registry: facts in, ids out (§3.5)."""

    facts: dict[str, MetricFact] = field(default_factory=dict)
    comparisons: dict[str, Comparison] = field(default_factory=dict)
    drivers: dict[str, DriverResult] = field(default_factory=dict)
    _seq: int = 0

    def add_fact(self, fact: MetricFact) -> str:
        """Register one measurement; explicit ids win, derived ones are keyed
        by content (see `_fact_identity`)."""
        if fact.id and fact.id not in ("F0", ""):
            fid = fact.id
        else:
            fid = _fact_identity(fact)
        registered = fact.model_copy(update={"id": fid})
        self.facts[fid] = registered
        return fid

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

    def register_numbers(
        self,
        period: AnalysisPeriod,
        *,
        source: str,
        numbers: list[tuple[str, object, str, dict]],
    ) -> list[str]:
        """P1-12: register the numbers a tool COMPUTED, as facts.

        Each entry is (metric, value, unit, filters). Two kinds are refused
        rather than registered: an absent measurement (None — the engine said
        "no baseline") and an impossible one (negative). Refusing here, in the
        module that owns the pack contract, is what keeps a summary number out
        of an answer that the pack cannot trace.
        """
        ids: list[str] = []
        for metric_name, value, unit, filters in numbers:
            if value is None:
                continue
            if Decimal(str(value)) < 0:
                continue
            ids.append(
                register_derived_fact(
                    self,
                    period,
                    metric_name=metric_name,
                    value=Decimal(str(value)),
                    unit=unit,
                    source=source,
                    filters=filters,
                )
            )
        return ids


def register_derived_fact(
    store: EvidenceStore,
    period: AnalysisPeriod,
    *,
    metric_name: str,
    value: Decimal | float | int | str,
    unit: str,
    source: str = "derived",
    filters: dict | None = None,
) -> str:
    """§8.1 — a number the answer may quote becomes a FACT, not a summary line.

    The engines (breakdown, seasonality, the customer split, carrier
    performance) compute real numbers that used to travel to the model as
    summary values only: the pack could not trace them, a placeholder had no
    fact to render, and a recompute-and-diff had nothing to compare. Registering
    them here gives each one the same birth certificate a compiler fact carries
    — the window it was measured over, its maturity, and where it came from.
    """
    now = datetime.now(UTC)
    fact = MetricFact(
        id="",
        metric=metric_name,
        value=Decimal(str(value)),
        unit=unit,
        period=period,
        filters=filters or {},
        source=source,
        computed_at=now,
        data_as_of=period.data_as_of or now,
        maturity_status=period.maturity_status,
    )
    return store.add_fact(fact)


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
            "delta_pct": str(comparison.delta_pct) if comparison.delta_pct is not None else None,
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
    summary = {key: str(value if is_money else count) for key, value, count in rows}
    status = "ok" if rows else "no_data"
    # P1-12: every bucket is a MEASUREMENT, so every bucket is a fact. Before
    # this the split existed only as summary text — the pack could not trace
    # "web = 900.00", a placeholder had nothing to render, and a recompute had
    # nothing to compare. The sample size rides beside the value for the same
    # reason (small-n splits are the §5.7 lie this layer exists to catch).
    evidence_ids: list[str] = []
    for key, value, count in rows:
        evidence_ids.append(
            register_derived_fact(
                store,
                period,
                metric_name=f"{metric_name}_by_{dimension}",
                value=value,
                unit="money" if is_money else "count",
                source=f"breakdown:{dimension}",
                filters={dimension: key},
            )
        )
        evidence_ids.append(
            register_derived_fact(
                store,
                period,
                metric_name=f"{metric_name}_sample_by_{dimension}",
                value=count,
                unit="count",
                source=f"breakdown:{dimension}",
                filters={dimension: key},
            )
        )
    return CapabilityResult(
        capability=f"breakdown_metric:{metric_name}:{dimension}",
        status=status,
        evidence_ids=evidence_ids,
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

    aov_now = _q(revenue_now.value / orders_now.value) if orders_now.value else Decimal("0")
    aov_prev = _q(revenue_prev.value / orders_prev.value) if orders_prev.value else Decimal("0")
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
                metric(n).name for n in ("orders_placed", "delivered_revenue", "collected_revenue")
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


def analyze_seasonality(
    daily_current: dict,
    daily_previous: dict,
) -> CapabilityResult:
    """§5.3 — is the change explained by the weekday mix? Plus the profile."""
    explained, gap = seasonality_explains(daily_current, daily_previous)
    return CapabilityResult(
        capability="analyze_seasonality",
        status="ok" if gap is not None else "no_data",
        evidence_ids=[],
        summary={
            "seasonality_explains_change": explained,
            "unexplained_share": gap,
            "weekday_profile": weekday_profile(daily_current),
        },
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        limitations=[
            "business calendar events (Ramadan/Eids) join in a later wave — "
            "v1 reads weekday shape only"
        ],
    )


def analyze_customers(orders: list[dict], *, window_start: datetime) -> CapabilityResult:
    """§5.4 — new vs returning in the window (identity v1: raw customer ids)."""
    split = customer_split(orders, window_start)
    total = split["new"] + split["returning"]
    return CapabilityResult(
        capability="analyze_customers",
        status="ok" if total else "no_data",
        evidence_ids=[],
        summary={
            "new": split["new"],
            "returning": split["returning"],
            "identity_quality": "raw customer ids — unification lands later",
        },
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        limitations=["identity resolution not applied — near-duplicate customers may split"],
    )


def analyze_fulfillment(shipments: list[dict], *, minimum_volume: int = 10) -> CapabilityResult:
    """§5.7 — carrier performance from real shipment statuses."""
    carriers = fulfillment_by_carrier(shipments, minimum_volume=minimum_volume)
    return CapabilityResult(
        capability="analyze_fulfillment",
        status="ok" if carriers else "no_data",
        evidence_ids=[],
        summary={
            "carriers": [
                {
                    "carrier": c.carrier,
                    "total": c.total,
                    "delivered": c.delivered,
                    "rejected": c.rejected,
                    "in_flight": c.in_flight,
                    "avg_days_to_deliver": c.avg_days_to_deliver,
                }
                for c in carriers
            ]
        },
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
        limitations=[f"carriers under the {minimum_volume}-shipment minimum are omitted"],
    )
