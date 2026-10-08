"""The SI agent orchestrator (spec §2.2, Phase 7 v1) — on the platform runner.

Runs a sales question through the platform AgentRunner with the SI tools
registered, then applies the DETERMINISTIC post-pass the spec demands:
facts rebuild from tool results, the answer's numbers are checked against
them, findings are graded by the engine — and when the answer cannot be
proven, the SAFE RESPONSE answers instead (§10.4).

v1 honesty: coverage runs as a deterministic post-CHECK with an explicit
limitation (not a between-rounds injection — that runner hook is the
recorded Gap Proposal); the regenerate-once policy likewise lands with the
loop-deepening wave. Neither shortcut can produce a wrong number — they
only narrow what is said.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.agents.sales_intelligence import (
    tools as _si_tools,  # noqa: F401 — registers the SI tools at import
)
from app.modules.ai.agents.sales_intelligence.response import (
    allowed_numbers_from_facts,
    safe_response,
    validate_answer,
)
from app.modules.analytics.capabilities import (
    CapabilityContext,
    EvidenceStore,
    load_store_metric_profile,
)
from app.modules.analytics.contracts import (
    AnalysisPeriod,
    Comparison,
    DataQuality,
    DataQualityStatus,
    DriverResult,
    EvidencePack,
    Finding,
    MaturityPolicy,
    MaturityStatus,
    MetricFact,
    Outcome,
)

logger = logging.getLogger(__name__)

SI_SYSTEM_PROMPT = (
    "أنت محلل مبيعات المتجر. عندك أدوات تحليل جاهزة — استخدمها للتحقيق "
    "قبل ما تجاوب، وكل رقم في إجابتك لازم يكون من نتيجة أداة. "
    "لو البيانات مش كفاية قول كده بصراحة. التوصيات اقتراحات مراجعة مش أفعال."
)


@dataclass(slots=True)
class AnalysisResult:
    """§12.2 — the agent boundary result (no HTTP/UI knowledge)."""

    outcome: Outcome
    answer: str
    findings: list[Finding] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    evidence_hash: str | None = None
    analysis_id: uuid.UUID | None = None
    saved_evidence_id: uuid.UUID | None = None
    tool_calls_made: list[dict] = field(default_factory=list)
    data_quality: DataQuality = field(
        default_factory=lambda: DataQuality(status=DataQualityStatus.COMPLETE)
    )
    guardrail_reason: str | None = None
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    agent_version: int = 1
    prompt_version: str | None = "1"


class AnalysisRequest(BaseModel):
    """§12.1 — AnalysisInput v1: one question, no session chain yet."""

    question: str = Field(min_length=1, max_length=2000)
    agent_id: uuid.UUID | None = None


class FindingOut(BaseModel):
    statement: str
    type: str
    relationship: str
    confidence: str
    confidence_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class FindingStoredOut(BaseModel):
    """A stored finding as the GET route returns it."""

    statement: str
    type: str
    relationship: str
    confidence: str
    confidence_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    materiality: str


class AnalysisStoredOut(BaseModel):
    """§12.4 — a stored analysis as the GET route returns it (typed: the
    AI contract refuses open bodies on the ai surface)."""

    analysis_id: uuid.UUID
    run_id: uuid.UUID | None = None
    question: str
    outcome: str
    content_hash: str
    model: str | None = None
    prompt_version: str | None = None
    created_at: str
    pack: EvidencePack
    findings: list[FindingStoredOut]


class AnalysisOut(BaseModel):
    """§12.2 — the rendered result the dashboard consumes."""

    analysis_id: uuid.UUID | None = None
    outcome: str
    answer: str
    findings: list[FindingOut]
    facts: list[dict]
    data_quality_status: str
    guardrail_reason: str | None = None


class DeepAnalysisQueuedOut(BaseModel):
    """§13 — the 202 body: what was queued and where to poll."""

    job_id: uuid.UUID
    analysis_id: uuid.UUID
    status: str


async def ensure_si_tools(session: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """Idempotently attach the six SI tools to the agent (§4.4). Read-only
    tools on the owner's own agent — no policy surface is bypassed."""
    from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS
    from app.modules.ai.models import AgentTool

    existing = {
        row.name
        for row in (
            await session.execute(
                select(AgentTool).where(
                    AgentTool.tenant_id == tenant_id,
                    AgentTool.agent_id == agent_id,
                    AgentTool.name.in_(SI_TOOLS),
                )
            )
        ).scalars()
    }
    for name in SI_TOOLS:
        if name in existing:
            continue
        session.add(AgentTool(tenant_id=tenant_id, agent_id=agent_id, name=name, policy={}))
    await session.flush()


def _rebuild_evidence(tool_calls_made: list[dict]) -> dict[str, list[dict]]:
    """Evidence payloads from every OK si_* tool result.
    Collects facts, comparisons, dimensions, and drivers."""
    facts: list[dict] = []
    comparisons: list[dict] = []
    dimensions: list[dict] = []
    drivers: list[dict] = []
    for call in tool_calls_made:
        if not str(call.get("name", "")).startswith("si_") or call.get("status") != "ok":
            continue
        res = call.get("result") or {}
        facts.extend(res.get("facts") or [])
        comparisons.extend(res.get("comparisons") or [])
        dimensions.extend(res.get("dimensions") or [])
        drivers.extend(res.get("drivers") or [])
    return {
        "facts": facts,
        "comparisons": comparisons,
        "dimensions": dimensions,
        "drivers": drivers,
    }


def _rebuild_facts(tool_calls_made: list[dict]) -> list[dict]:
    """MetricFact payloads from every OK si_* tool result."""
    return _rebuild_evidence(tool_calls_made)["facts"]


def _facts_to_contracts(
    payloads: list[dict], timezone: str = "Africa/Cairo"
) -> dict[str, MetricFact]:
    """Rebuild the run-scoped evidence needed for findings/coverage (P1-20).
    Rebuilds facts transferring provenance fields from tool payload."""
    facts: dict[str, MetricFact] = {}
    now = datetime.now(UTC)
    for payload in payloads:
        fact_tz = payload.get("timezone") or timezone
        data_as_of = (
            datetime.fromisoformat(payload["data_as_of"]).replace(tzinfo=UTC)
            if payload.get("data_as_of")
            else now
        )
        computed_at = (
            datetime.fromisoformat(payload["computed_at"]).replace(tzinfo=UTC)
            if payload.get("computed_at")
            else now
        )
        period = AnalysisPeriod(
            start=datetime.fromisoformat(payload["period_start"]).replace(tzinfo=UTC),
            end=datetime.fromisoformat(payload["period_end"]).replace(tzinfo=UTC),
            timezone=fact_tz,
            attribution_basis=payload.get("attribution_basis", "placed_at"),
            maturity_policy=MaturityPolicy(kind=payload.get("maturity_policy", "immediate")),
            maturity_status=MaturityStatus(payload["maturity"]),
            data_as_of=data_as_of,
        )
        facts[payload["id"]] = MetricFact(
            id=payload["id"],
            metric=payload["metric"],
            value=Decimal(str(payload["value"])),
            unit=payload.get("unit", "orders"),
            period=period,
            source=payload.get("source", "orders"),
            computed_at=computed_at,
            data_as_of=data_as_of,
            maturity_status=MaturityStatus(payload["maturity"]),
        )
    return facts


async def run_sales_analysis(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    agent_id: uuid.UUID,
    question: str,
    runner=None,
) -> AnalysisResult:
    """One sales question → an evidence-backed answer (or a safe one)."""
    from sqlalchemy import text as sa_text

    from app.modules.ai.gateway import AIGateway
    from app.modules.ai.runtime import AgentRunner

    # Load tenant settings (merchant timezone & currency)
    tenant_row = (
        await session.execute(
            sa_text(
                "SELECT COALESCE(timezone, 'Africa/Cairo'),"
                " COALESCE(currency, 'EGP')"
                " FROM tenants WHERE id = :tid"
            ),
            {"tid": str(tenant_id)},
        )
    ).first()
    merchant_tz = tenant_row[0] if tenant_row else "Africa/Cairo"
    merchant_currency = tenant_row[1] if tenant_row else "EGP"

    profile = await load_store_metric_profile(session, tenant_id)

    runner = runner or AgentRunner(gateway=AIGateway())
    analysis_id = uuid.uuid4()
    from app.modules.analytics.events import emit_analysis_event

    await emit_analysis_event(
        session,
        tenant_id,
        event_type="ai.analysis.started",
        analysis_id=analysis_id,
        run_id=None,
        payload={"question": question, "currency": merchant_currency},
    )
    result = await runner.run(
        session,
        tenant_id,
        agent_id=agent_id,
        user_message=question,
        system_prompt=SI_SYSTEM_PROMPT,
    )

    run_id = result.run_id
    evidence = _rebuild_evidence(result.tool_calls_made)
    payloads = evidence["facts"]
    allowed = allowed_numbers_from_facts(evidence)
    facts_contracts = _facts_to_contracts(payloads, timezone=merchant_tz)

    from app.modules.analytics.evidence import build_pack
    from app.modules.analytics.findings import build_findings

    store = (
        _store_from(
            facts_contracts,
            comparisons=evidence["comparisons"],
            dimensions=evidence["dimensions"],
            drivers=evidence["drivers"],
        )
        if facts_contracts
        else EvidenceStore()
    )
    findings = build_findings(store) if facts_contracts else []
    evidence_hash = None
    pack = None
    if facts_contracts:
        pack = build_pack(
            store,
            CapabilityContext(tenant_id=tenant_id, profile=profile),
            question=question,
        )
        evidence_hash = pack.content_hash

    # P1-22: Determine outcome and answer before durable save_analysis
    guardrail_reason: str | None = None
    safe_resp: bool = False
    if result.content:
        problems = validate_answer(result.content, allowed, findings)
        if problems:
            logger.warning("si.answer_rejected tenant=%s problems=%s", tenant_id, problems)
            outcome = Outcome.NO_CLEAR_EXPLANATION if findings else Outcome.INSUFFICIENT_DATA
            answer = safe_response(findings, {})
            guardrail_reason = "si_response_invalid"
            safe_resp = True
        else:
            outcome = Outcome.ANSWERED
            answer = result.content
    else:
        outcome = Outcome.NO_CLEAR_EXPLANATION if findings else Outcome.INSUFFICIENT_DATA
        answer = safe_response(findings, {})
        guardrail_reason = result.guardrail_reason

    saved_evidence_id = None
    model_name = getattr(result, "model", None) or "fast"
    provider_name = getattr(result, "provider", None) or "platform"
    agent_ver = getattr(result, "agent_version", 1)
    if pack is not None:
        from app.modules.analytics.persistence import save_analysis

        saved_evidence_id = await save_analysis(
            session,
            tenant_id,
            question=question,
            outcome=outcome.value,
            pack=pack,
            findings=findings,
            run_id=result.run_id,
            model=model_name,
            prompt_version=str(agent_ver),
        )

    await emit_analysis_event(
        session,
        tenant_id,
        event_type="ai.analysis.completed",
        analysis_id=analysis_id,
        run_id=run_id,
        payload={
            "outcome": outcome.value,
            "findings": len(findings),
            "safe_response": safe_resp,
        },
    )
    return AnalysisResult(
        outcome=outcome,
        answer=answer,
        findings=findings,
        facts=payloads,
        evidence_hash=evidence_hash,
        analysis_id=analysis_id,
        saved_evidence_id=saved_evidence_id,
        tool_calls_made=result.tool_calls_made,
        guardrail_reason=guardrail_reason,
        provider=provider_name,
        model=model_name,
        agent_version=agent_ver,
        prompt_version=str(agent_ver),
    )


def _store_from(
    facts: dict[str, MetricFact],
    *,
    comparisons: list[dict] | None = None,
    dimensions: list[dict] | None = None,
    drivers: list[dict] | None = None,
) -> EvidenceStore:
    """Wrap rebuilt evidence in the store shape the findings builder reads."""
    store = EvidenceStore()
    for fact_id, fact in facts.items():
        store.facts[fact_id] = fact

    for idx, c in enumerate(comparisons or []):
        left_id = c.get("left_fact_id", "")
        right_id = c.get("right_fact_id", "")
        if left_id in store.facts and right_id in store.facts:
            ref = f"C{idx + 1}"
            store.comparisons[ref] = Comparison(
                label=c.get("label", ""),
                left_fact_id=left_id,
                right_fact_id=right_id,
                delta=Decimal(str(c.get("delta", 0))),
                delta_pct=Decimal(str(c["delta_pct"])) if c.get("delta_pct") is not None else None,
            )

    for drv_idx, drv in enumerate(drivers or []):
        ord_contrib = Decimal(str(drv.get("orders_contribution", 0)))
        aov_contrib = Decimal(str(drv.get("aov_contribution", 0)))
        tot_delta = Decimal(str(drv.get("total_delta", 0)))
        if ord_contrib + aov_contrib == tot_delta:
            ref = f"D{drv_idx + 1}"
            store.drivers[ref] = DriverResult(
                kind=drv.get("kind", "orders_vs_aov"),
                orders_contribution=ord_contrib,
                aov_contribution=aov_contrib,
                total_delta=tot_delta,
            )

    return store
