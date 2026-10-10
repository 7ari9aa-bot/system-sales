"""Golden scenario runner (spec §17.2) — plant, compute, assert. No LLM.

Takes a seeded synthetic store, runs the REAL analytics path over it (the
same compiler/capabilities/drivers production uses), and checks the
manifest's expectations. This is Phase 2's gate: one end-to-end scenario
proves the analytics layer end-to-end without a model call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.capabilities import (
    CapabilityContext,
    EvidenceStore,
    analyze_drivers,
)
from app.modules.analytics.compiler import compute_fact
from app.modules.analytics.contracts import (
    AnalysisPeriod,
    MaturityPolicy,
    MaturityStatus,
)
from app.modules.analytics.engines import detect_anomalies
from app.modules.analytics.evaluation.synthetic import Scenario, SyntheticStore
from app.modules.analytics.semantic import StoreMetricProfile


@dataclass(slots=True)
class GoldenResult:
    scenario: Scenario
    passed: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)


def _windows(reference: datetime, days: int) -> tuple[AnalysisPeriod, AnalysisPeriod]:
    today_start = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    common = dict(
        timezone="UTC",
        attribution_basis="placed_at",
        maturity_policy=MaturityPolicy(kind="immediate"),
    )
    current = AnalysisPeriod(
        start=today_start - timedelta(days=days),
        end=today_start,
        maturity_status=MaturityStatus.MATURE,
        data_as_of=reference,
        **common,
    )
    previous = AnalysisPeriod(
        start=current.start - timedelta(days=days),
        end=current.start,
        maturity_status=MaturityStatus.MATURE,
        data_as_of=reference,
        **common,
    )
    return current, previous


async def evaluate_scenario(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    store: SyntheticStore,
) -> GoldenResult:
    """Run the real path over the seeded store and check the manifest."""
    checks: list[tuple[str, bool, str]] = []
    # The drivers run on a MONEY metric — an AOV over a count is meaningless.
    context = CapabilityContext(
        tenant_id=tenant_id,
        profile=StoreMetricProfile(primary_sales_metric="delivered_revenue"),
    )
    evidence = EvidenceStore()
    reference = store.reference
    current, previous = _windows(reference, days=30)

    current_revenue = await compute_fact(
        session, tenant_id, "delivered_revenue", current, fact_id="F0"
    )
    previous_revenue = await compute_fact(
        session, tenant_id, "delivered_revenue", previous, fact_id="F0"
    )
    orders_current = await compute_fact(session, tenant_id, "orders_placed", current, fact_id="F0")
    evidence.add_fact(current_revenue)
    evidence.add_fact(previous_revenue)
    evidence.add_fact(orders_current)

    if store.scenario is Scenario.AOV_DECLINE:
        result = await analyze_drivers(session, context, evidence, days=30, reference=reference)
        checks.append(
            (
                "aov driver dominates",
                abs(Decimal(result.summary["aov_contribution"]))
                >= abs(Decimal(result.summary["orders_contribution"])),
                result.summary,
            )
        )
        checks.append(
            (
                "revenue actually fell",
                Decimal(result.summary["total_delta"]) < 0,
                result.summary,
            )
        )

    if store.scenario is Scenario.ORDERS_DECLINE:
        result = await analyze_drivers(session, context, evidence, days=30, reference=reference)
        checks.append(
            (
                "orders driver dominates",
                abs(Decimal(result.summary["orders_contribution"]))
                >= abs(Decimal(result.summary["aov_contribution"])),
                result.summary,
            )
        )

    if store.scenario is Scenario.REFUND_SPIKE:
        refunds = await compute_fact(session, tenant_id, "refund_amount", current, fact_id="F0")
        delivered = await compute_fact(
            session, tenant_id, "delivered_revenue", current, fact_id="F0"
        )
        ratio = refunds.value / delivered.value if delivered.value else Decimal(0)
        checks.append(
            (
                "refunds eat a large share of the current window",
                ratio >= Decimal("0.15"),
                f"refunds={refunds.value} delivered={delivered.value} ratio={ratio:.2f}",
            )
        )

    if store.scenario is Scenario.REVENUE_SPIKE:
        series = {
            datetime.fromisoformat(order["placed_at"]).date(): Decimal(str(order["grand_total"]))
            for order in store.orders
        }
        daily: dict = {}
        for day, value in series.items():
            daily[day] = daily.get(day, Decimal(0)) + value
        anomalies = detect_anomalies(daily)
        expected = set(store.manifest.get("anomaly_days", []))
        found = {a.day.isoformat() for a in anomalies}
        checks.append(
            (
                "the planted spike is found (and deduped to one day)",
                found == expected,
                f"found={sorted(found)} expected={sorted(expected)}",
            )
        )

    if store.scenario is Scenario.IMMATURE_TAIL:
        # The tail itself (the last 3 days) must carry NO delivered revenue —
        # the orders exist, the deliveries have not happened yet.
        today_start = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        tail = AnalysisPeriod(
            start=today_start - timedelta(days=3),
            end=today_start,
            timezone="UTC",
            attribution_basis="delivered_at",
            maturity_policy=MaturityPolicy(kind="carrier_curve"),
            maturity_status=MaturityStatus.PARTIALLY_MATURE,
            data_as_of=reference,
        )
        # Delivered shipments belonging to orders PLACED in the tail — the
        # placed-window attribution is what immaturity withholds.
        from sqlalchemy import text as _text

        delivered_for_tail_orders = (
            await session.execute(
                _text(
                    "SELECT COUNT(*) FROM shipments s "
                    "JOIN orders o ON o.id = s.order_id "
                    "WHERE s.tenant_id = :tenant_id AND s.status = 'delivered' "
                    "AND COALESCE(o.placed_at, o.created_at) >= :start "
                    "AND COALESCE(o.placed_at, o.created_at) < :end"
                ),
                {
                    "tenant_id": str(tenant_id),
                    "start": tail.start,
                    "end": tail.end,
                },
            )
        ).scalar_one()
        checks.append(
            (
                "orders placed in the tail have NO delivered shipments yet",
                delivered_for_tail_orders == 0,
                f"tail_orders_delivered={delivered_for_tail_orders}",
            )
        )

    if store.scenario is Scenario.CHANNEL_SHIFT:
        from app.modules.analytics.compiler import compute_breakdown

        rows = await compute_breakdown(
            session, tenant_id, "orders_placed", current, dimension="channel"
        )
        by_channel = {key: count for key, count, _n in rows}
        retail = by_channel.get("retail", 0)
        web = by_channel.get("web", 0)
        checks.append(
            (
                "retail took a real share of the current window",
                retail > 0 and retail >= web // 4,
                f"by_channel={by_channel}",
            )
        )

    if store.scenario is Scenario.BASELINE:
        checks.append(
            (
                "flat store: revenue is stable across windows (±25%)",
                abs(current_revenue.value - previous_revenue.value)
                <= previous_revenue.value * Decimal("0.25"),
                f"current={current_revenue.value} previous={previous_revenue.value}",
            )
        )

    return GoldenResult(
        scenario=store.scenario,
        passed=all(ok for _name, ok, _detail in checks),
        checks=checks,
    )
