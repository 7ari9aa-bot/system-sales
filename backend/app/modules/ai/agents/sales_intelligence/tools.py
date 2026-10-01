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
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.tools import ToolSpec, register_tool


def _resolve_window(days: int, *, reference: datetime | None = None) -> object:
    """§6.5 — the system resolves the period; the model only chooses length.
    The window ends at TODAY'S START (UTC v1): today is immature for
    delivered-based metrics by definition."""
    from app.modules.analytics.capabilities import _period_window

    return _period_window(reference or datetime.now(UTC), days=days)


def _context(tenant_id: uuid.UUID):
    from app.modules.analytics.capabilities import CapabilityContext
    from app.modules.analytics.semantic import StoreMetricProfile

    return CapabilityContext(
        tenant_id=tenant_id, profile=StoreMetricProfile()
    )


def _fact_payload(fact) -> dict:
    return {
        "id": fact.id,
        "metric": fact.metric,
        "value": str(fact.value),
        "unit": fact.unit,
        "period_start": fact.period.start.date().isoformat(),
        "period_end": fact.period.end.date().isoformat(),
        "maturity": fact.maturity_status.value,
    }


class SIGetMetricArgs(BaseModel):
    metric_name: str
    days: int = Field(default=30, ge=1, le=90)
    channel: str | None = None


async def _si_get_metric(
    session: AsyncSession, tenant_id: uuid.UUID, *, metric_name: str, days: int = 30,
    channel: str | None = None, context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, get_metric
    from app.modules.analytics.semantic import metric

    metric(metric_name)  # unknown metric fails loudly — never a guess
    store = EvidenceStore()
    result = await get_metric(
        session,
        _context(tenant_id),
        store,
        metric_name=metric_name,
        period=_resolve_window(days),
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
    session: AsyncSession, tenant_id: uuid.UUID, *, metric_name: str, days: int = 30,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, compare_periods
    from app.modules.analytics.semantic import metric

    metric(metric_name)
    store = EvidenceStore()
    result = await compare_periods(
        session, _context(tenant_id), store, metric_name=metric_name, days=days
    )
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "facts": [
            _fact_payload(store.facts[eid])
            for eid in result.evidence_ids
            if eid in store.facts
        ],
    }


class SIBreakdownArgs(BaseModel):
    metric_name: str
    dimension: str = "channel"
    days: int = Field(default=30, ge=1, le=90)


async def _si_breakdown(
    session: AsyncSession, tenant_id: uuid.UUID, *, metric_name: str,
    dimension: str = "channel", days: int = 30, context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, breakdown_metric

    store = EvidenceStore()
    result = await breakdown_metric(
        session, _context(tenant_id), store,
        metric_name=metric_name, dimension=dimension, days=days,
    )
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "limitations": result.limitations,
    }


class SIDriversArgs(BaseModel):
    days: int = Field(default=30, ge=1, le=90)


async def _si_analyze_drivers(
    session: AsyncSession, tenant_id: uuid.UUID, *, days: int = 30,
    context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import EvidenceStore, analyze_drivers

    store = EvidenceStore()
    result = await analyze_drivers(session, _context(tenant_id), store, days=days)
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "assumptions": [a.statement for a in result.assumptions],
        "facts": [
            _fact_payload(store.facts[eid])
            for eid in result.evidence_ids
            if eid in store.facts
        ],
    }


class SIExplainArgs(BaseModel):
    metric_name: str


async def _si_explain_metric(
    session: AsyncSession, tenant_id: uuid.UUID, *, metric_name: str,
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
    session: AsyncSession, tenant_id: uuid.UUID, *, context: dict | None = None,
) -> dict:
    from app.modules.analytics.capabilities import get_data_status

    result = get_data_status()
    return {
        "capability": result.capability,
        "status": result.status,
        "summary": result.summary,
        "warnings": result.data_quality.warnings,
    }


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
    ]
    from app.modules.ai.tools import get_tool

    for spec in specs:
        if get_tool(spec.name) is None:
            register_tool(spec)


register_si_tools()
