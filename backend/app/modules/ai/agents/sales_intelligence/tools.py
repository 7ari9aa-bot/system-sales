"""SI capabilities exposed as platform tools (spec §4).

The handlers adapt the analytics capabilities to the tool registry's
contract: (session, tenant_id, validated args) → JSON-safe dict. The
tenant comes from the platform; periods are resolved by the SYSTEM
(§6.5 — the model picks a window length, never dates); metric names are
validated against the registry and an unknown one fails the request
loudly. Each result embeds its MetricFact provenance so the orchestrator
can rebuild evidence without re-querying.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import text as _sql
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.tools import ToolSpec, register_tool
from app.modules.analytics.contracts import AnalysisPeriod


async def _resolve_window(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    days: int,
    *,
    reference: datetime | None = None,
) -> AnalysisPeriod:
    """§6.5 — the system resolves the period in the store's configured timezone (P1-19)."""
    from zoneinfo import ZoneInfo

    from app.modules.analytics.capabilities import _period_window
    from app.modules.analytics.service import resolve_report_timezone

    tz_str = await resolve_report_timezone(session, tenant_id)
    zone = ZoneInfo(str(tz_str))
    ref = reference or datetime.now(zone)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=zone)
    else:
        ref = ref.astimezone(zone)
    period = _period_window(ref, days=days)
    return AnalysisPeriod(
        start=period.start.astimezone(UTC),
        end=period.end.astimezone(UTC),
        timezone=str(tz_str),
        attribution_basis=period.attribution_basis,
        maturity_policy=period.maturity_policy,
        maturity_status=period.maturity_status,
        data_as_of=ref.astimezone(UTC),
    )


async def _context(session: AsyncSession, tenant_id: uuid.UUID):
    """P1-18: Loads the tenant's real StoreMetricProfile instead of a blank default."""
    from app.modules.analytics.capabilities import CapabilityContext
    from app.modules.analytics.semantic import load_store_metric_profile

    profile = await load_store_metric_profile(session, tenant_id)
    return CapabilityContext(tenant_id=tenant_id, profile=profile)


def _fact_payload(fact) -> dict:
    """P1-20: transfers complete provenance metadata through fact payload."""
    return {
        "id": fact.id,
        "metric": fact.metric,
        "value": str(fact.value),
        "unit": fact.unit,
        # P1-12: the split a fact belongs to is part of its meaning. Without
        # the filters, "shipments_total = 2" does not say whose two shipments
        # it is, and the model can attribute a bucket to the wrong carrier.
        "filters": fact.filters or {},
        "period_start": fact.period.start.isoformat(),
        "period_end": fact.period.end.isoformat(),
        "maturity": fact.maturity_status.value,
        "timezone": getattr(fact.period, "timezone", "UTC"),
        "source": getattr(fact, "source", "orders"),
        "attribution_basis": getattr(fact.period, "attribution_basis", "placed_at"),
        "maturity_policy": getattr(
            getattr(fact.period, "maturity_policy", None), "kind", "immediate"
        ),
        "data_as_of": fact.data_as_of.isoformat() if getattr(fact, "data_as_of", None) else None,
        "computed_at": fact.computed_at.isoformat() if getattr(fact, "computed_at", None) else None,
    }


def _typed_facts(store, period, source: str, numbers) -> list[dict]:
    """P1-12: register the numbers a tool computed as typed evidence.

    `numbers` is (metric_name, value, unit, filters) per measurement. Which
    numbers may become facts — not absent, not impossible — is the analytics
    store's rule, not this adapter's; the store owns the pack contract, so a
    tool cannot mint a line the pack would refuse. This only maps what the
    store accepted into the payload shape the model reads.
    """
    ids = store.register_numbers(period, source=source, numbers=numbers)
    return [_fact_payload(store.facts[fid]) for fid in ids]


class SIGetMetricArgs(BaseModel):
    metric_name: str
    days: int = Field(default=30, ge=1, le=90)
    channel: str | None = None
async def _si_get_metric(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    days: int = 30,
    channel: str | None = None,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, get_metric
    from app.modules.analytics.semantic import metric

    metric(metric_name)  # unknown metric fails loudly — never a guess
    store = EvidenceStore()
    ctx = await _context(session, tenant_id)
    period = await _resolve_window(session, tenant_id, days)
    result = await get_metric(
        session,
        ctx,
        store,
        metric_name=metric_name,
        period=period,
        channel=channel,
    )

    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "limitations": result.limitations,
        "facts": [_fact_payload(store.facts[eid]) for eid in result.evidence_ids],
    }


class SIComparePeriodsArgs(BaseModel):
    metric_name: str
    days: int = Field(default=30, ge=1, le=90)


async def _si_compare_periods(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, compare_periods
    from app.modules.analytics.semantic import metric

    metric(metric_name)
    store = EvidenceStore()
    ctx = await _context(session, tenant_id)
    result = await compare_periods(session, ctx, store, metric_name=metric_name, days=days)
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "facts": [
            _fact_payload(store.facts[eid]) for eid in result.evidence_ids if eid in store.facts
        ],
        "comparisons": [
            {
                "label": c.label,
                "left_fact_id": c.left_fact_id,
                "right_fact_id": c.right_fact_id,
                "delta": str(c.delta),
                "delta_pct": str(c.delta_pct) if c.delta_pct is not None else None,
            }
            for c in store.comparisons
        ],
    }


class SIBreakdownArgs(BaseModel):
    metric_name: str
    dimension: str = "channel"
    days: int = Field(default=30, ge=1, le=90)


async def _si_breakdown(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    dimension: str = "channel",
    days: int = 30,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, breakdown_metric

    store = EvidenceStore()
    ctx = await _context(session, tenant_id)
    result = await breakdown_metric(
        session,
        ctx,
        store,
        metric_name=metric_name,
        dimension=dimension,
        days=days,
    )
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "limitations": result.limitations,
        # P1-12: the split is a PRESENTATION of the typed facts below, not a
        # second copy of the truth. It used to read `store.dimensions`, a field
        # the evidence store never had — the tool raised AttributeError on every
        # call and the agent silently lost its only breakdown. Each bucket is
        # now a fact (value + sample size, filtered by this dimension), so the
        # model can quote a bucket only through evidence.
        "dimensions": [
            {
                "dimension": dimension,
                "entries": [
                    {"key": key, "label": key, "value": value}
                    for key, value in (result.summary.get("entries") or {}).items()
                ],
            }
        ],
        "facts": [
            _fact_payload(store.facts[eid]) for eid in result.evidence_ids if eid in store.facts
        ],
    }


class SIDriversArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)


async def _si_analyze_drivers(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, analyze_drivers

    store = EvidenceStore()
    ctx = await _context(session, tenant_id)
    result = await analyze_drivers(session, ctx, store, days=days)
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "assumptions": [a.statement for a in result.assumptions],
        "facts": [
            _fact_payload(store.facts[eid]) for eid in result.evidence_ids if eid in store.facts
        ],
        "drivers": [
            {
                "kind": d.kind,
                "orders_contribution": str(d.orders_contribution),
                "aov_contribution": str(d.aov_contribution),
                "total_delta": str(d.total_delta),
            }
            for d in store.drivers
        ],
    }


class SIExplainArgs(BaseModel):
    metric_name: str


async def _si_explain_metric(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    metric_name: str,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import explain_metric

    result = explain_metric(metric_name)
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
    }


class SIStatusArgs(BaseModel):
    pass


async def _si_data_status(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import get_data_status

    result = get_data_status()
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "warnings": result.data_quality.warnings,
    }


#: The SI tool names in one place — the configure script and the orchestrator
#: read this tuple instead of re-listing them.
SI_TOOLS: tuple[str, ...] = (
    "si_get_metric",
    "si_compare_periods",
    "si_breakdown",
    "si_analyze_drivers",
    "si_explain_metric",
    "si_data_status",
    "si_analyze_seasonality",
    "si_analyze_customers",
    "si_analyze_fulfillment",
)


def register_si_tools() -> None:
    """Idempotent registration into the platform registry."""
    specs = [
        ToolSpec(
            name="si_get_metric",
            description="One store metric (orders/revenue/refunds) for the last N days.",
            args_schema=SIGetMetricArgs,
            handler=_si_get_metric,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_compare_periods",
            description="Compare a metric: this window vs the preceding equal window.",
            args_schema=SIComparePeriodsArgs,
            handler=_si_compare_periods,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_breakdown",
            description="Split a metric by a dimension (channel).",
            args_schema=SIBreakdownArgs,
            handler=_si_breakdown,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_analyze_drivers",
            description="Decompose the revenue change: orders vs AOV (exact).",
            args_schema=SIDriversArgs,
            handler=_si_analyze_drivers,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_explain_metric",
            description="How a metric is defined, attributed, and versioned.",
            args_schema=SIExplainArgs,
            handler=_si_explain_metric,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_data_status",
            description="Data freshness/maturity status for the store.",
            args_schema=SIStatusArgs,
            handler=_si_data_status,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_analyze_seasonality",
            description="Does the weekday mix explain the change? Daily revenue shape.",
            args_schema=SISeasonalityArgs,
            handler=_si_analyze_seasonality,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_analyze_customers",
            description="New vs returning customers in the window.",
            args_schema=SICustomersArgs,
            handler=_si_analyze_customers,
            tags=["sales-intelligence"],
        ),
        ToolSpec(
            name="si_analyze_fulfillment",
            description="Carrier delivery/rejection rates (minimum volume applies).",
            args_schema=SIFulfillmentArgs,
            handler=_si_analyze_fulfillment,
            tags=["sales-intelligence"],
        ),
    ]
    from app.modules.ai.tools import get_tool

    for spec in specs:
        if get_tool(spec.name) is None:
            register_tool(spec)


class SISeasonalityArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)


async def _si_analyze_seasonality(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    """§5.3 v1 — reads the store's REAL daily revenue and checks whether
    the weekday mix explains the change."""
    from decimal import Decimal

    from app.modules.analytics.capabilities import EvidenceStore, analyze_seasonality

    current = await _resolve_window(session, tenant_id, days)
    previous_start = current.start - timedelta(days=days)

    rows = (
        await session.execute(
            _sql(
                "SELECT COALESCE(o.placed_at, o.created_at)::date AS day, "
                "SUM(o.grand_total) AS revenue "
                "FROM orders o WHERE o.tenant_id = :tenant_id "
                "AND o.deleted_at IS NULL "
                "AND COALESCE(o.placed_at, o.created_at) >= :start "
                "AND COALESCE(o.placed_at, o.created_at) < :end "
                "GROUP BY day ORDER BY day"
            ),
            {"tenant_id": str(tenant_id), "start": previous_start, "end": current.end},
        )
    ).all()
    daily = {r.day: Decimal(str(r.revenue)) for r in rows}
    split_point = current.start.date()
    daily_current = {d: v for d, v in daily.items() if d >= split_point}
    daily_previous = {d: v for d, v in daily.items() if d < split_point}
    season = analyze_seasonality(daily_current, daily_previous)
    # P1-12: the gap share and each weekday lift are MEASUREMENTS of this
    # store's orders, so they are registered as facts. A summary alone lets the
    # model quote a number the pack cannot trace — the answer looks grounded
    # and is not.
    store = EvidenceStore()
    facts = _typed_facts(
        store,
        current,
        "seasonality",
        [
            (
                "seasonality_unexplained_share",
                season.summary.get("unexplained_share"),
                "ratio",
                {},
            ),
            *(
                ("weekday_revenue_lift", lift, "ratio", {"weekday": name})
                for name, lift in (season.summary.get("weekday_profile") or {}).items()
            ),
        ],
    )
    return {
        "capability": season.capability,
        "status": season.status,
        "summary": season.summary,
        "limitations": season.limitations,
        "facts": facts,
    }


class SICustomersArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)


async def _si_analyze_customers(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    context: dict | None = None,
) -> dict:
    """§5.4 v1 — new vs returning from the store's real orders."""

    from app.modules.analytics.capabilities import EvidenceStore, analyze_customers

    current = await _resolve_window(session, tenant_id, days)
    rows = (
        await session.execute(
            _sql(
                "SELECT customer_id::text AS customer_id, "
                "COALESCE(placed_at, created_at) AS placed_at "
                "FROM orders o WHERE o.tenant_id = :tenant_id "
                "AND o.deleted_at IS NULL "
                "AND COALESCE(placed_at, created_at) >= :start "
                "AND COALESCE(placed_at, created_at) < :end + interval '60 days' "
                "ORDER BY COALESCE(placed_at, created_at) "
                "LIMIT 5000"
            ),
            {"tenant_id": str(tenant_id), "start": current.start, "end": current.end},
        )
    ).all()
    orders = [{"customer_id": r.customer_id, "placed_at": r.placed_at} for r in rows]
    result = analyze_customers(orders, window_start=current.start)
    # P1-12: the two counts are measurements of this window, so they are facts.
    store = EvidenceStore()
    facts = _typed_facts(
        store,
        current,
        "customers",
        [
            ("customers_new", result.summary.get("new"), "count", {}),
            ("customers_returning", result.summary.get("returning"), "count", {}),
        ],
    )
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "limitations": result.limitations,
        "facts": facts,
    }


class SIFulfillmentArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    minimum_volume: int = Field(default=10, ge=1, le=100)


async def _si_analyze_fulfillment(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    days: int = 30,
    minimum_volume: int = 10,
    context: dict | None = None,
) -> dict:
    """§5.7 v1 — carrier performance from the store's real shipments."""

    from app.modules.analytics.capabilities import EvidenceStore, analyze_fulfillment

    current = await _resolve_window(session, tenant_id, days)
    rows = (
        await session.execute(
            _sql(
                "SELECT s.carrier, s.status, s.shipped_at, s.delivered_at "
                "FROM shipments s WHERE s.tenant_id = :tenant_id "
                "AND COALESCE(s.shipped_at, s.created_at) >= :start "
                "AND COALESCE(s.shipped_at, s.created_at) < :end"
            ),
            {"tenant_id": str(tenant_id), "start": current.start, "end": current.end},
        )
    ).all()
    shipments = [
        {
            "carrier": r.carrier,
            "status": r.status,
            "shipped_at": r.shipped_at,
            "delivered_at": r.delivered_at,
        }
        for r in rows
    ]
    result = analyze_fulfillment(shipments, minimum_volume=minimum_volume)
    # P1-12: per-carrier performance is measured from this store's shipments,
    # so each number becomes a fact filtered by its carrier. A small-n carrier
    # is absent from `carriers` by the minimum-volume rule, and the pack says
    # so by not holding a fact for it — the model cannot quote what was
    # deliberately not measured.
    store = EvidenceStore()
    numbers: list = []
    for row in result.summary.get("carriers") or []:
        carrier = {"carrier": row.get("carrier")}
        numbers.extend(
            [
                ("shipments_total", row.get("total"), "count", carrier),
                ("shipments_delivered", row.get("delivered"), "count", carrier),
                ("shipments_rejected", row.get("rejected"), "count", carrier),
                ("shipments_in_flight", row.get("in_flight"), "count", carrier),
                ("avg_days_to_deliver", row.get("avg_days_to_deliver"), "days", carrier),
            ]
        )
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "limitations": result.limitations,
        "facts": _typed_facts(store, current, "fulfillment", numbers),
    }


register_si_tools()
