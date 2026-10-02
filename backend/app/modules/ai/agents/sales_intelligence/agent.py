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
    tools as _si_tools,  # noqa: F401 — registers the SI tools
)
from app.modules.ai.agents.sales_intelligence.response import (
    allowed_numbers_from_facts,
    safe_response,
    validate_answer,
)
from app.modules.analytics.capabilities import CapabilityContext, EvidenceStore
from app.modules.analytics.contracts import (
    AnalysisPeriod,
    DataQuality,
    DataQualityStatus,
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

SI_TOOLS = (
    "si_get_metric",
    "si_compare_periods",
    "si_breakdown",
    "si_analyze_drivers",
    "si_explain_metric",
    "si_data_status",
)


@dataclass(slots=True)
class AnalysisResult:
    """§12.2 — the agent boundary result (no HTTP/UI knowledge)."""

    outcome: Outcome
    answer: str
    findings: list[Finding] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    evidence_hash: str | None = None
    tool_calls_made: list[dict] = field(default_factory=list)
    data_quality: DataQuality = field(
        default_factory=lambda: DataQuality(status=DataQualityStatus.COMPLETE)
    )
    guardrail_reason: str | None = None


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


class AnalysisOut(BaseModel):
    """§12.2 — the rendered result the dashboard consumes."""

    outcome: str
    answer: str
    findings: list[FindingOut]
    facts: list[dict]
    data_quality_status: str
    guardrail_reason: str | None = None


async def ensure_si_tools(
    session: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
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
        session.add(
            AgentTool(tenant_id=tenant_id, agent_id=agent_id, name=name, policy={})
        )
    await session.flush()


def _rebuild_facts(tool_calls_made: list[dict]) -> list[dict]:
    """MetricFact payloads from every OK si_* tool result. Facts are safe to
    show the model — they are true, tenant-scoped, provenance-stamped data."""
    payloads: list[dict] = []
    for call in tool_calls_made:
        if not str(call.get("name", "")).startswith("si_") or call.get("status") != "ok":
            continue
        payloads.extend((call.get("result") or {}).get("facts") or [])
    return payloads


def _facts_to_contracts(payloads: list[dict]) -> dict[str, MetricFact]:
    """Rebuild the run-scoped evidence needed for findings/coverage. v1 keeps
    the reconstruction minimal: facts only — comparisons/drivers stay in the
    tool summaries the model already quoted."""
    facts: dict[str, MetricFact] = {}
    now = datetime.now(UTC)
    for payload in payloads:
        period = AnalysisPeriod(
            start=datetime.fromisoformat(payload["period_start"]).replace(tzinfo=UTC),
            end=datetime.fromisoformat(payload["period_end"]).replace(tzinfo=UTC),
            timezone="UTC",
            attribution_basis="placed_at",
            maturity_policy=MaturityPolicy(kind="immediate"),
            maturity_status=MaturityStatus(payload["maturity"]),
            data_as_of=now,
        )
        facts[payload["id"]] = MetricFact(
            id=payload["id"],
            metric=payload["metric"],
            value=Decimal(payload["value"]),
            unit=payload["unit"],
            period=period,
            source="orders",
            computed_at=now,
            data_as_of=now,
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
    from app.modules.ai.gateway import AIGateway
    from app.modules.ai.runtime import AgentRunner

    runner = runner or AgentRunner(gateway=AIGateway())
    result = await runner.run(
        session,
        tenant_id,
        agent_id=agent_id,
        user_message=question,
        system_prompt=SI_SYSTEM_PROMPT,
    )

    payloads = _rebuild_facts(result.tool_calls_made)
    allowed = allowed_numbers_from_facts(payloads)
    facts_contracts = _facts_to_contracts(payloads)

    from app.modules.analytics.evidence import build_pack
    from app.modules.analytics.findings import build_findings

    findings = build_findings(
        _store_from(facts_contracts),
    ) if facts_contracts else []
    evidence_hash = (
        build_pack(
            _store_from(facts_contracts),
            CapabilityContext(tenant_id=tenant_id),
            question=question,
        ).content_hash
        if facts_contracts
        else None
    )

    if result.content:
        problems = validate_answer(result.content, allowed, findings)
        if problems:
            logger.warning(
                "si.answer_rejected tenant=%s problems=%s", tenant_id, problems
            )
            return AnalysisResult(
                outcome=Outcome.ANSWERED,
                answer=safe_response(findings, {}),
                findings=findings,
                facts=payloads,
                evidence_hash=evidence_hash,
                tool_calls_made=result.tool_calls_made,
                guardrail_reason="si_response_invalid",
            )
        return AnalysisResult(
            outcome=Outcome.ANSWERED,
            answer=result.content,
            findings=findings,
            facts=payloads,
            evidence_hash=evidence_hash,
            tool_calls_made=result.tool_calls_made,
        )

    # No proven answer: findings still answer deterministically (§10.4).
    return AnalysisResult(
        outcome=Outcome.NO_CLEAR_EXPLANATION
        if findings
        else Outcome.INSUFFICIENT_DATA,
        answer=safe_response(findings, {}),
        findings=findings,
        facts=payloads,
        evidence_hash=evidence_hash,
        tool_calls_made=result.tool_calls_made,
        guardrail_reason=result.guardrail_reason,
    )


def _store_from(facts: dict[str, object]) -> EvidenceStore:
    """Wrap rebuilt facts in the store shape the findings builder reads."""
    store = EvidenceStore()
    for fact_id, fact in facts.items():
        store.facts[fact_id] = fact  # type: ignore[assignment]
    return store

