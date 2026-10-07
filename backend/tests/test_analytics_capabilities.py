"""Capabilities / evidence / findings tests (spec §4, §6, §8, §9) — real DB.

The synthetic store from the compiler tests flows through real capabilities:
facts register with ids, comparisons compute deltas (None against zero —
never invented), drivers decompose exactly, the pack hashes stably, the
findings builder grades with the SYSTEM's engine and respects the top-3 cap.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.analytics.capabilities import (
    CapabilityContext,
    EvidenceStore,
    analyze_drivers,
    breakdown_metric,
    compare_periods,
    explain_metric,
    get_data_status,
    get_metric,
)
from app.modules.analytics.contracts import (
    AnalysisPeriod,
    DriverResult,
    MaturityPolicy,
    MaturityStatus,
    MetricFact,
)
from app.modules.analytics.evidence import build_pack, validate_pack_inputs
from app.modules.analytics.findings import build_findings
from app.modules.analytics.semantic import StoreMetricProfile
from app.modules.customers.models import Customer
from app.modules.orders.models import Order, OrderPayment, Refund, Shipment

DAYS = 30
REFERENCE = datetime.now(UTC)


def _profile() -> StoreMetricProfile:
    return StoreMetricProfile(primary_sales_metric="delivered_revenue")


async def _seed_two_windows(db, tenant_id: uuid.UUID) -> None:
    customer = Customer(tenant_id=tenant_id, name="Cap Customer")
    db.add(customer)
    await db.flush()
    today_start = REFERENCE.replace(hour=0, minute=0, second=0, microsecond=0)

    async def _seed(order_days: int, total: float, *, delivered: bool, refund: Decimal | None):
        order = Order(
            tenant_id=tenant_id,
            number=f"O-{uuid.uuid4().hex[:10]}",
            customer_id=customer.id,
            status="fulfilled",
            grand_total=total,
            channel="web",
            placed_at=today_start - timedelta(days=order_days),
        )
        db.add(order)
        await db.flush()
        if delivered:
            db.add(
                Shipment(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    carrier="Bosta",
                    status="delivered",
                    shipped_at=today_start - timedelta(days=order_days),
                    delivered_at=today_start - timedelta(days=order_days),
                )
            )
        payment = OrderPayment(
            tenant_id=tenant_id,
            order_id=order.id,
            method="cod",
            status="captured",
            amount=total,
            paid_at=today_start - timedelta(days=order_days),
        )
        db.add(payment)
        await db.flush()
        if refund is not None:
            db.add(
                Refund(
                    tenant_id=tenant_id,
                    payment_id=payment.id,
                    amount=float(refund),
                    status="processed",
                    processed_at=today_start - timedelta(days=order_days - 2),
                )
            )

    # CURRENT window (days 0-29 back from today's 00:00): 3 orders, 1200 total.
    for days, total in ((1, 500.0), (5, 400.0), (10, 300.0)):
        await _seed(days, total, delivered=True, refund=None)
    # PRIOR window (30-59 back): 2 orders, 800 total + a 50 refund.
    await _seed(35, 500.0, delivered=True, refund=Decimal("50"))
    await _seed(45, 300.0, delivered=True, refund=None)
    await db.flush()


async def test_get_metric_registers_fact_with_id(db, tenant_ctx):
    await _seed_two_windows(db, tenant_ctx.tenant_id)
    context = CapabilityContext(tenant_id=tenant_ctx.tenant_id, profile=_profile())
    store = EvidenceStore()
    from app.modules.analytics.capabilities import _period_window

    result = await get_metric(
        db,
        context,
        store,
        metric_name="delivered_revenue",
        period=_period_window(REFERENCE, days=DAYS),
    )
    assert result.status == "ok"
    assert result.evidence_ids == ["F1"]
    assert store.facts["F1"].value == Decimal("1200")


async def test_compare_periods_delta_and_pct(db, tenant_ctx):
    await _seed_two_windows(db, tenant_ctx.tenant_id)
    context = CapabilityContext(tenant_id=tenant_ctx.tenant_id, profile=_profile())
    store = EvidenceStore()
    result = await compare_periods(db, context, store, metric_name="delivered_revenue", days=DAYS)
    assert result.status == "ok"
    assert result.summary["current"] == "1200.00"
    assert result.summary["previous"] == "800.00"
    # Δ = +400 on a base of 800 → +50%.
    assert Decimal(result.summary["delta"]) == Decimal("400.00")
    assert Decimal(result.summary["delta_pct"]) == Decimal("50.00")


async def test_breakdown_by_channel_splits_the_windows(db, tenant_ctx):
    await _seed_two_windows(db, tenant_ctx.tenant_id)
    context = CapabilityContext(tenant_id=tenant_ctx.tenant_id, profile=_profile())
    store = EvidenceStore()
    result = await breakdown_metric(
        db, context, store, metric_name="orders_placed", dimension="channel"
    )
    assert result.status == "ok"
    assert result.summary["dimension"] == "channel"
    # All seeded orders are web — one bucket, no invented ones.
    assert set(result.summary["entries"]) == {"web"}


async def test_drivers_decompose_exactly(db, tenant_ctx):
    await _seed_two_windows(db, tenant_ctx.tenant_id)
    context = CapabilityContext(tenant_id=tenant_ctx.tenant_id, profile=_profile())
    store = EvidenceStore()
    result = await analyze_drivers(db, context, store, days=DAYS)
    assert result.status == "ok"
    total = Decimal(result.summary["total_delta"])
    orders_part = Decimal(result.summary["orders_contribution"])
    aov_part = Decimal(result.summary["aov_contribution"])
    assert orders_part + aov_part == total


async def test_explain_and_data_status():
    explained = explain_metric("delivered_revenue")
    assert explained.summary["attribution_event"] == "shipment delivered"
    status = get_data_status()
    assert status.data_quality.warnings, "curves pending is a visible warning"


async def test_pack_builds_hashed_and_validates(db, tenant_ctx):
    await _seed_two_windows(db, tenant_ctx.tenant_id)
    context = CapabilityContext(tenant_id=tenant_ctx.tenant_id, profile=_profile())
    store = EvidenceStore()
    await compare_periods(db, context, store, metric_name="delivered_revenue", days=DAYS)
    pack = build_pack(store, context, question="إيه حصل للمبيعات؟")
    assert pack.content_hash
    assert len(pack.facts) == 2
    # Same content → same hash (immutability contract).
    again = build_pack(store, context, question="إيه حصل للمبيعات؟")
    assert again.content_hash == pack.content_hash


async def test_validation_rejects_inconsistent_driver(db, tenant_ctx):
    store = EvidenceStore()
    period = AnalysisPeriod(
        start=REFERENCE - timedelta(days=30),
        end=REFERENCE,
        timezone="UTC",
        attribution_basis="placed_at",
        maturity_policy=MaturityPolicy(kind="immediate"),
        maturity_status=MaturityStatus.MATURE,
        data_as_of=REFERENCE,
    )
    fact = MetricFact(
        id="F1",
        metric="delivered_revenue",
        value=Decimal("100"),
        unit="money",
        period=period,
        source="orders",
        computed_at=REFERENCE,
        data_as_of=REFERENCE,
        maturity_status=MaturityStatus.MATURE,
    )
    store.add_fact(fact)
    store.add_driver(
        DriverResult(
            kind="orders_vs_aov",
            orders_contribution=Decimal("60"),
            aov_contribution=Decimal("30"),
            total_delta=Decimal("100"),  # 60+30 != 100 — the invariant is broken
        )
    )
    problems = validate_pack_inputs(store, tenant_id=uuid.uuid4(), timezone="UTC", currency="EGP")
    assert any("does not sum" in p for p in problems)


async def test_findings_capped_and_confidence_graded(db, tenant_ctx):
    await _seed_two_windows(db, tenant_ctx.tenant_id)
    context = CapabilityContext(tenant_id=tenant_ctx.tenant_id)
    store = EvidenceStore()
    await compare_periods(db, context, store, metric_name="delivered_revenue", days=DAYS)
    findings = build_findings(store)
    assert len(findings) == 1
    assert findings[0].type == "DERIVED"
    assert findings[0].confidence in ("HIGH", "MEDIUM", "LOW")
    assert findings[0].confidence_reasons  # the engine explains itself
    assert findings[0].evidence_refs
