"""Between-rounds coverage for the SI agent — gap detection + regenerate-once.

The deterministic post-pass (``validate_answer`` / ``safe_response``) proves
the answer's numbers; it cannot make the answer ADDRESS the question. When
the first draft skips dimensions the question asked for AND the evidence
supports, ONE corrective regeneration runs through the gateway (reserve/
settle like any model call, tools disabled — the correction reuses the
evidence the tools already gathered). The regenerated text must then pass
the SAME gates as a first draft: the analytics output guardrail, the
free-number validation, and a coverage re-check. Failing any of them keeps
the ORIGINAL draft — the orchestrator's existing validation/safe-response
path then applies unchanged. Neither step can produce a wrong number; they
only narrow what is said.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.agents.sales_intelligence.response import validate_answer
from app.modules.analytics.contracts import Finding

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Dimension:
    """One question dimension the coverage gate knows how to see.

    ``terms`` trigger on the question AND count as addressed when they
    reappear in the answer (the vocabulary the merchant used is the
    vocabulary the answer must use back). ``evidence_terms`` decide whether
    the gathered evidence can support the dimension at all — a dimension the
    tools found nothing for is NOT a gap: the system prompt already lets the
    model say "the data is not enough" honestly, and demanding coverage
    without evidence is how a gate starts manufacturing numbers.
    """

    name: str
    label_ar: str
    terms: tuple[str, ...]
    evidence_terms: tuple[str, ...]


_DIMENSIONS: tuple[_Dimension, ...] = (
    _Dimension(
        name="sales",
        label_ar="المبيعات",
        terms=("مبيعات", "بيع", "إيراد", "ايراد", "revenue", "sales"),
        evidence_terms=("sales", "revenue", "gmv", "aov", "grand_total", "orders"),
    ),
    _Dimension(
        name="orders",
        label_ar="الطلبات",
        terms=("طلب", "طلبات", "order"),
        evidence_terms=("order",),
    ),
    _Dimension(
        name="profit",
        label_ar="المكسب",
        terms=("مكسب", "ربح", "أرباح", "ارباح", "profit"),
        evidence_terms=("profit", "margin", "net", "مكسب", "ربح"),
    ),
    _Dimension(
        name="customers",
        label_ar="العملاء",
        terms=("عميل", "عملاء", "زباين", "customer"),
        evidence_terms=("customer", "new_vs", "returning", "عملاء"),
    ),
    _Dimension(
        name="fulfillment",
        label_ar="الشحن والتسليم",
        terms=("شحن", "توصيل", "تسليم", "مرتجع", "رفض", "fulfillment", "delivery", "carrier"),
        evidence_terms=("fulfillment", "carrier", "delivery", "rejection", "rejected", "شحن"),
    ),
    _Dimension(
        name="products",
        label_ar="المنتجات",
        terms=("منتج", "أصناف", "اصناف", "صنف", "product"),
        evidence_terms=("product", "variant", "sku", "top_", "منتج"),
    ),
    _Dimension(
        name="drivers",
        label_ar="أسباب التغيّر",
        terms=("ليه", "السبب", "سبب", "أسباب", "اسباب", "driver"),
        evidence_terms=("driver", "contribution", "orders_vs_aov", "delta"),
    ),
    _Dimension(
        name="trend",
        label_ar="المقارنة الزمنية",
        terms=(
            "مقارنة",
            "مقارنه",
            "الفرق",
            "نمو",
            "تغير",
            "تغيّر",
            "trend",
            "الشهر اللي فات",
            "الموسم اللي فات",
        ),
        evidence_terms=("comparison", "delta_pct", "previous", "trend", "weekday"),
    ),
    _Dimension(
        name="channels",
        label_ar="قنوات البيع",
        terms=("قناة", "قنوات", "channel"),
        evidence_terms=("channel", "platform"),
    ),
)

_LABELS_AR: dict[str, str] = {d.name: d.label_ar for d in _DIMENSIONS}


def _mentions(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _evidence_text(evidence: dict | None) -> str:
    """The whole evidence pack as one lowercase string for term matching."""
    if not evidence:
        return ""
    try:
        return json.dumps(evidence, ensure_ascii=False, default=str).lower()
    except (TypeError, ValueError):  # non-serializable payloads → no support claimed
        return ""


def coverage_gaps(question: str, content: str | None, evidence: dict | None) -> list[str]:
    """Dimension names the question asked for, the evidence supports, and the
    answer does not address — in ``_DIMENSIONS`` declaration order.

    A dimension is a gap only when ALL three hold: the question asks about
    it, the evidence carries data for it, and the answer never mentions it.
    """
    q = (question or "").lower()
    a = (content or "").lower()
    ev = _evidence_text(evidence)
    gaps: list[str] = []
    for dim in _DIMENSIONS:
        if not _mentions(q, dim.terms):
            continue  # not asked → never a gap
        if _mentions(a, dim.terms):
            continue  # addressed
        if not _mentions(ev, dim.evidence_terms):
            continue  # unsupported → the model may honestly say "not enough data"
        gaps.append(dim.name)
    return gaps


def build_corrective_instruction(gaps: list[str]) -> str:
    """The between-rounds corrective instruction (SI system-prompt voice).

    Names the missing dimensions and demands an evidence-backed rewrite —
    never new numbers: every digit must still come from a tool result, and
    an honest "not enough data" stays allowed.
    """
    labels = "، ".join(_LABELS_AR.get(gap, gap) for gap in gaps)
    return (
        f"إجابتك السابقة ما غطّتش نقطة مهمة في السؤال: {labels}. "
        "أعد صياغة الإجابة كاملة تغطي كل النقاط دي من الأدلة اللي الأدوات جمعتها بالفعل. "
        "كل رقم في إجابتك لازم يكون من نتيجة أداة — ممنوع تختلق رقم جديد أو تقرب رقم من دماغك. "
        "لو البيانات مش كفاية لنقطة منها قول كده بصراحة."
    )


async def regenerate_on_coverage_gap(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    agent_id: uuid.UUID,
    run_id: uuid.UUID | None,
    question: str,
    history: list[dict[str, str]] | None,
    draft: str | None,
    evidence: dict,
    allowed_numbers: set[str],
    findings: list[Finding],
    tool_calls_made: list[dict],
) -> tuple[str | None, dict | None, tuple[int, int] | None]:
    """At most ONE corrective regeneration when the first draft misses coverage.

    Returns ``(replacement_content, note, regen_tokens)``:

    * ``(None, None, None)`` — no gaps (or the runner already withheld the
      draft, which its own guardrail handles): the orchestrator proceeds
      unchanged;
    * ``(None, note, tokens)`` — gaps were found, the regeneration ran (or
      tried) and did not produce a provably better answer; the ORIGINAL
      draft is kept, ``note`` records what happened, and ``tokens`` is the
      ``(tokens_in, tokens_out)`` the provider billed for the attempt
      (None when it never reached the provider);
    * ``(text, note, tokens)`` — the regenerated answer passed the analytics
      output guardrail, the free-number validation and a coverage re-check.

    The call goes through the gateway like any model call (budget reserve/
    settle included) and reuses the gathered evidence only — ``tools=None``.
    """
    if not draft or not draft.strip():
        # The runner already withheld the draft (guardrail/empty): the
        # orchestrator's existing safe path applies, and regeneration cannot
        # correct what the model never said.
        return None, None, None
    gaps = coverage_gaps(question, draft, evidence)
    if not gaps:
        return None, None, None
    note: dict = {"attempted": True, "succeeded": False, "gaps": list(gaps)}

    from app.modules.ai.gateway import AIGateway
    from app.modules.ai.guardrails import analytics_guardrail
    from app.modules.ai.models import Agent
    from app.modules.ai.runtime import AgentRunner

    agent = await session.get(Agent, agent_id)
    if agent is None:
        logger.warning("si.coverage_regen_no_agent run=%s agent=%s", run_id, agent_id)
        return None, note, None

    messages: list[dict[str, str]] = [
        {"role": "system", "content": AgentRunner._resolve_system_prompt(agent)}
    ]
    messages.extend(history or [])
    messages.append({"role": "assistant", "content": draft})
    messages.append({"role": "user", "content": build_corrective_instruction(gaps)})
    try:
        chat = await AIGateway().chat(
            session,
            tenant_id,
            alias=AgentRunner._alias_for(agent),
            messages=messages,
            tools=None,  # the correction reuses the gathered evidence only
            temperature=float(agent.temperature),
            max_tokens=agent.max_output_tokens,
            agent_id=agent_id,
            run_id=run_id,
        )
    except Exception:  # containment — a failed regen keeps the original draft
        logger.warning("si.coverage_regen_failed run=%s", run_id, exc_info=True)
        return None, note, None

    # The provider billed this call whether or not the regen survives the
    # gates — the caller must fold these tokens into the run's usage record
    # or the monthly cap never sees them (the exact leak class the metering
    # fix closed for the main loop).
    regen_tokens = (chat.tokens_in, chat.tokens_out)
    candidate = chat.content
    if not candidate or not candidate.strip():
        return None, note, regen_tokens
    # The regen output re-enters through the SAME gates as a first draft.
    verdict = analytics_guardrail().evaluate(candidate, {"tool_results": tool_calls_made})
    if verdict.decision != "allow":
        logger.warning("si.coverage_regen_blocked run=%s reason=%s", run_id, verdict.reason)
        return None, note, regen_tokens
    if validate_answer(candidate, allowed_numbers, findings):
        return None, note, regen_tokens
    if coverage_gaps(question, candidate, evidence):
        return None, note, regen_tokens
    note["succeeded"] = True
    return candidate, note, regen_tokens
