"""P1-12 — the SI agent's numbers are typed evidence, with provenance.

Three claims this file closes:

* **Run-unique evidence ids.** Every SI tool call builds its own
  ``EvidenceStore`` and the run merges those stores into one pack keyed by id.
  Positional ids ("F1") restarted per call, so the second call's fact silently
  replaced the first's — evidence disappeared from the published pack.
* **Summaries are not evidence.** A number the answer may quote has to exist in
  the pack as a fact. The breakdown tool was worse: it read ``store.dimensions``,
  a field the store never had, so every breakdown call raised inside the runtime.
* **Alias is not provenance.** "fast" is a knob. The stored analysis must say
  which provider answered and which concrete model stood behind the alias.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.agents.sales_intelligence.agent import (
    AnalysisStoredOut,
    _facts_to_contracts,
)
from app.modules.ai.agents.sales_intelligence.tools import (
    _si_analyze_customers,
    _si_analyze_fulfillment,
    _si_analyze_seasonality,
    _si_breakdown,
    _typed_facts,
)
from app.modules.analytics.capabilities import (
    CapabilityContext,
    EvidenceStore,
    register_derived_fact,
)
from app.modules.analytics.contracts import (
    AnalysisPeriod,
    DataQuality,
    DataQualityStatus,
    MaturityPolicy,
    MaturityStatus,
    MetricFact,
)
from app.modules.analytics.evidence import build_pack, validate_pack_inputs
from app.modules.analytics.persistence import load_analysis, save_analysis
from app.modules.customers.models import Customer
from app.modules.orders.models import Order, Shipment

# Same shape as the placeholder parser in analytics/numbers.py.
_PLACEHOLDER_ID_RE = re.compile(r"[A-Za-z0-9_]+")

NOW = datetime.now(UTC)


def _period(*, days: int = 30, timezone: str = "UTC") -> AnalysisPeriod:
    return AnalysisPeriod(
        start=NOW - timedelta(days=days),
        end=NOW,
        timezone=timezone,
        attribution_basis="placed_at",
        maturity_policy=MaturityPolicy(kind="immediate"),
        maturity_status=MaturityStatus.PARTIALLY_MATURE,
        data_as_of=NOW,
    )


def _fact(metric: str, value: str, period: AnalysisPeriod, **kwargs) -> MetricFact:
    return MetricFact(
        id=kwargs.get("id", ""),
        metric=metric,
        value=Decimal(value),
        unit=kwargs.get("unit", "money"),
        period=period,
        filters=kwargs.get("filters", {}),
        source=kwargs.get("source", "orders"),
        computed_at=NOW,
        data_as_of=period.data_as_of,
        maturity_status=period.maturity_status,
    )


# ------------------------------------------------------ run-unique ids ----


def test_two_tool_stores_do_not_collide_when_merged() -> None:
    """The regression: positional ids made one call overwrite another."""
    period = _period()
    store_a = EvidenceStore()
    store_b = EvidenceStore()
    id_a = store_a.add_fact(_fact("delivered_revenue", "1200.00", period))
    id_b = store_b.add_fact(_fact("orders_placed", "34", period))
    merged = {id_a: "a", id_b: "b"}
    assert len(merged) == 2, "two different measurements collided under one id"


def test_id_is_stable_per_measurement_and_changes_with_the_window() -> None:
    store = EvidenceStore()
    first = store.add_fact(_fact("delivered_revenue", "1200.00", _period(days=30)))
    second = store.add_fact(_fact("delivered_revenue", "1250.00", _period(days=30)))
    assert first == second, "the same window and metric is one fact, not two"
    assert store.facts[first].value == Decimal("1250.00")
    other_window = store.add_fact(_fact("delivered_revenue", "900.00", _period(days=7)))
    assert other_window != first


def test_filters_make_a_bucket_its_own_fact() -> None:
    store = EvidenceStore()
    period = _period()
    web = store.add_fact(_fact("orders_placed", "20", period, filters={"channel": "web"}))
    whatsapp = store.add_fact(_fact("orders_placed", "14", period, filters={"channel": "whatsapp"}))
    assert web != whatsapp
    assert store.facts[web].filters == {"channel": "web"}


def test_ids_fit_the_placeholder_charset() -> None:
    """`{{fact_id:format}}` parses [A-Za-z0-9_] — a colon or hyphen in an id
    would make the fact unquotable, which is worse than having no id."""
    store = EvidenceStore()
    fid = store.add_fact(_fact("delivered_revenue", "5", _period(), filters={"channel": "web"}))
    assert _PLACEHOLDER_ID_RE.fullmatch(fid), fid


def test_explicit_ids_still_win() -> None:
    """The compiler passes named ids (F0 handling stays as spec'd); only
    unnamed measurements get a content key."""
    store = EvidenceStore()
    assert store.add_fact(_fact("x", "1", _period(), id="F7")) == "F7"
    # "F0" is the compiler's "no id yet" marker, so it is keyed by content.
    auto = store.add_fact(_fact("delivered_revenue", "1", _period(), id="F0"))
    assert auto != "F0"


# ---------------------------------------------------- typed derived numbers --


def test_register_derived_fact_carries_the_window_provenance() -> None:
    period = _period(timezone="Africa/Cairo")
    store = EvidenceStore()
    fid = register_derived_fact(
        store,
        period,
        metric_name="customers_new",
        value=12,
        unit="count",
        source="customers",
    )
    fact = store.facts[fid]
    assert fact.maturity_status is period.maturity_status
    assert fact.data_as_of == period.data_as_of
    assert fact.period.timezone == "Africa/Cairo"


def test_typed_facts_skips_absent_and_impossible_numbers() -> None:
    store = EvidenceStore()
    payloads = _typed_facts(
        store,
        _period(),
        "fulfillment",
        [
            ("shipments_total", 10, "count", {"carrier": "Bosta"}),
            ("shipments_total", 0, "count", {"carrier": "Falabela"}),
            ("avg_days_to_deliver", None, "days", {"carrier": "unknown"}),
            ("avg_days_to_deliver", -1, "days", {"carrier": "clock-skew"}),
        ],
    )
    # None and a negative median are not measurements the pack may hold; a
    # zero count IS (the carrier shipped nothing — that is a fact).
    assert len(payloads) == 2
    assert all(_fact_charset_ok(p["id"]) for p in payloads)
    assert not any("clock-skew" in str(p["filters"]) for p in payloads)
    assert not any(p["metric"] == "avg_days_to_deliver" for p in payloads)
    assert len(store.facts) == 2, "a skipped number must not leave a fact behind"


def _fact_charset_ok(fid: str) -> bool:
    return bool(_PLACEHOLDER_ID_RE.fullmatch(str(fid)))


def test_negative_refund_buckets_still_validate() -> None:
    """The refund exemption follows the measure, not one literal name: a
    refund split by channel is legitimately negative."""
    store = EvidenceStore()
    period = _period()
    store.add_fact(_fact("refund_amount_by_channel", "-50.00", period, filters={"channel": "web"}))
    problems = validate_pack_inputs(store, tenant_id=uuid.uuid4(), timezone="UTC", currency="EGP")
    assert problems == []
    with pytest.raises(ValueError):
        build_pack(
            _negative_store("delivered_revenue_by_channel"),
            CapabilityContext(tenant_id=uuid.uuid4()),
            question="س",
        )


def _negative_store(metric: str) -> EvidenceStore:
    store = EvidenceStore()
    store.add_fact(_fact(metric, "-50.00", _period()))
    return store


# ------------------------------------------------------------- the SI tools ----


async def _seed_store(db: AsyncSession, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    """Two customers, four orders across two channels, and delivered shipments."""
    ids = []
    for name in ("Amina", "Youssef"):
        customer = Customer(tenant_id=tenant_id, name=name)
        db.add(customer)
        await db.flush()
        ids.append(customer.id)
    day = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    for index, (customer_id, channel) in enumerate(
        [
            (ids[0], "web"),
            (ids[0], "whatsapp"),
            (ids[1], "web"),
            (ids[1], "web"),
        ]
    ):
        order = Order(
            tenant_id=tenant_id,
            number=f"P1-12-{index}-{uuid.uuid4().hex[:6]}",
            customer_id=customer_id,
            status="fulfilled",
            grand_total=100.0,
            channel=channel,
            placed_at=day - timedelta(days=index + 2),
        )
        db.add(order)
        await db.flush()
        db.add(
            Shipment(
                tenant_id=tenant_id,
                order_id=order.id,
                carrier="Bosta",
                status="delivered",
                shipped_at=day - timedelta(days=index + 2),
                delivered_at=day - timedelta(days=index + 1),
            )
        )
    await db.flush()
    return ids


async def test_si_breakdown_produces_typed_evidence_for_every_bucket(db, tenant_ctx) -> None:
    """Before P1-12 this call raised AttributeError (`store.dimensions` did not
    exist) and the buckets existed only as summary text."""
    tenant_id = tenant_ctx.tenant_id
    await _seed_store(db, tenant_id)

    out = await _si_breakdown(
        db, tenant_id, metric_name="orders_placed", dimension="channel", days=30
    )

    assert out["status"] == "ok"
    facts = out["facts"]
    assert facts, "a breakdown with no typed facts cannot be cited"
    buckets = {
        fact["filters"]["channel"]
        for fact in facts
        if not fact["metric"].endswith("_sample_by_channel")
    }
    assert buckets == {"web", "whatsapp"}
    # Each bucket also carries its own sample size — the small-n guard.
    assert any(f["metric"].endswith("_sample_by_channel") for f in facts)


async def test_si_customers_and_fulfillment_and_seasonality_emit_facts(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    await _seed_store(db, tenant_id)

    customers = await _si_analyze_customers(db, tenant_id, days=30)
    metrics = {f["metric"] for f in customers["facts"]}
    assert metrics == {"customers_new", "customers_returning"}

    fulfillment = await _si_analyze_fulfillment(db, tenant_id, days=30, minimum_volume=1)
    per_carrier = {f["filters"]["carrier"] for f in fulfillment["facts"]}
    assert per_carrier == {"Bosta"}
    assert {f["metric"] for f in fulfillment["facts"]} >= {
        "shipments_total",
        "shipments_delivered",
        "avg_days_to_deliver",
    }

    seasonality = await _si_analyze_seasonality(db, tenant_id, days=30)
    if seasonality["summary"].get("unexplained_share") is not None:
        assert {f["metric"] for f in seasonality["facts"]} & {
            "seasonality_unexplained_share",
            "weekday_revenue_lift",
        }


async def test_merged_facts_keep_their_filters_through_the_pack(db, tenant_ctx) -> None:
    """The pack is rebuilt from tool payloads; a fact that loses its filters
    stops saying which bucket it measured."""
    tenant_id = tenant_ctx.tenant_id
    await _seed_store(db, tenant_id)
    out = await _si_breakdown(
        db, tenant_id, metric_name="orders_placed", dimension="channel", days=30
    )

    contracts = _facts_to_contracts(out["facts"], timezone="UTC")
    assert len(contracts) == len(out["facts"]), "rebuild collided facts"
    web = [f for f in contracts.values() if f.filters.get("channel") == "web"]
    assert web, "the bucket filter did not survive the rebuild"


# ---------------------------------------------------------------- provenance ----


def _pack_stub() -> object:
    from app.modules.analytics.contracts import EvidencePack

    store = EvidenceStore()
    fid = store.add_fact(_fact("delivered_revenue", "1200.00", _period()))
    return EvidencePack(
        question="ليه المبيعات زادت؟",
        facts=[store.facts[fid]],
        data_quality=DataQuality(status=DataQualityStatus.COMPLETE),
    )


async def test_saved_analysis_records_provider_and_concrete_model(db, tenant_ctx) -> None:
    """§12.4 provenance: the alias alone cannot attribute an answer."""
    analysis_id = await save_analysis(
        db,
        tenant_ctx.tenant_id,
        question="ليه المبيعات زادت؟",
        outcome="ANSWERED",
        pack=_pack_stub(),
        findings=[],
        model="fast",
        provider="openai_compatible",
        model_version="gpt-4o-mini-2024",
        prompt_version="7",
    )

    stored = await load_analysis(db, tenant_ctx.tenant_id, analysis_id)
    assert stored["provider"] == "openai_compatible"
    assert stored["model_version"] == "gpt-4o-mini-2024"
    assert stored["model"] == "fast"


async def test_provenance_is_null_when_nobody_recorded_it(db, tenant_ctx) -> None:
    analysis_id = await save_analysis(
        db,
        tenant_ctx.tenant_id,
        question="ليه المبيعات زادت؟",
        outcome="ANSWERED",
        pack=_pack_stub(),
        findings=[],
    )
    stored = await load_analysis(db, tenant_ctx.tenant_id, analysis_id)
    assert stored["provider"] is None
    assert stored["model_version"] is None


def test_the_stored_surface_exposes_provenance() -> None:
    """§12.4: the GET route cannot report what its schema does not carry."""
    fields = set(AnalysisStoredOut.model_fields)
    assert {"model", "provider", "model_version", "prompt_version"} <= fields


def test_the_pack_is_validated_in_the_window_its_facts_were_measured_in() -> None:
    """A merchant-zone fact is not a timezone problem, and used to be one.

    The pack was validated as UTC while every SI fact carries the merchant's
    zone, so a tenant that set one failed validation AFTER the model call was
    already paid for — the answer was computed and then thrown away.
    """
    period = _period(timezone="Africa/Cairo")
    store = EvidenceStore()
    fact_id = store.add_fact(_fact("delivered_revenue", "1200.00", period))
    context = CapabilityContext(tenant_id=uuid.uuid4())

    with pytest.raises(ValueError, match="timezone"):
        build_pack(store, context, question="إيه حصل؟", timezone="UTC")

    pack = build_pack(store, context, question="إيه حصل؟", timezone="Africa/Cairo", currency="EGP")
    assert pack.facts[0].id == fact_id
    assert pack.content_hash
