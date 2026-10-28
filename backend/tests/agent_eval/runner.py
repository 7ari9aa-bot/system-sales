"""Run one golden case through the REAL customer runtime and report what happened.

The only thing that varies between a CI run and a live evaluation is the model: the runner
takes a ``gateway`` and uses it as given. Everything else (the provisioned agent, the tool
registry and policy, argument validation, the fact ledger, grounding, guardrails, handover
writes) is production code reading the shop the case describes.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text

from app.modules.ai.agents.customer.turn import TurnInput, run_customer_turn
from app.modules.ai.core.provisioning import provision_canonical_agents
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent
from app.modules.ai.runtime import AgentRunner
from app.modules.customers.models import Customer
from tests.agent_eval.case_schema import Case
from tests.agent_eval.graders import CaseResult, Observed, canonical_number, grade, numerals
from tests.agent_eval.shop_builder import BuiltShop, build_shop

_NUM = r"\d+(?:\.\d+)?"


@dataclass
class TurnRecord:
    customer: str
    observed: Observed
    blocked_reason: str | None
    grounding: str


async def _tool_trace(db, run_id: uuid.UUID | None) -> tuple[tuple[str, ...], frozenset[str]]:
    """Names of tools that ran (in order) and every numeral their SUCCESSFUL results carried."""
    if run_id is None:
        return (), frozenset()
    rows = (
        await db.execute(
            text(
                "SELECT name, status, result FROM tool_calls WHERE run_id = :r ORDER BY created_at"
            ),
            {"r": run_id},
        )
    ).all()
    names = tuple(r[0] for r in rows)
    facts: set[str] = set()
    for _name, status, result in rows:
        if status == "ok" and result is not None:
            facts |= numerals(json.dumps(result, ensure_ascii=False, default=str))
    return names, frozenset(facts)


async def _apply_production_exit(db, tenant_id, conversation_id, outcome) -> None:
    """Do what ``ai.hooks`` does with a turn that has nothing sendable.

    ``run_customer_turn`` only DECIDES; the hook turns a withheld or empty reply into a
    handover (hooks.py, "no silence" rule). A harness that skipped this would record a blocked
    reply as "not handed over" and misreport a rule that production enforces.
    """
    from app.modules.ai.handover import request_human_takeover

    reason = note = None
    if outcome.blocked_reason == "empty_turn":
        return
    if outcome.blocked_reason is not None:
        reason = "guardrail" if outcome.blocked_reason.startswith("guardrail:") else "failure"
        note = outcome.blocked_reason
    elif not outcome.reply and not getattr(outcome, "handover_reason", None):
        reason, note = "failure", "turn produced no reply"
    if reason:
        await request_human_takeover(
            db,
            tenant_id,
            conversation_id=conversation_id,
            reason=reason,
            note=note,
            run_id=outcome.run_id,
        )


async def _handed_over(db, conversation_id: uuid.UUID, outcome) -> bool:
    if getattr(outcome, "handover_reason", None):
        return True
    count = (
        await db.execute(
            text("SELECT count(*) FROM ai_handovers WHERE conversation_id = :c"),
            {"c": conversation_id},
        )
    ).scalar_one()
    return count > 0


async def run_case(
    db, tenant_id: uuid.UUID, case: Case, *, gateway: AIGateway | None = None
) -> tuple[CaseResult, list[TurnRecord]]:
    await provision_canonical_agents(db, tenant_id)
    await db.flush()
    agent = (
        await db.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.kind == "customer")
        )
    ).scalar_one()
    built: BuiltShop = await build_shop(db, tenant_id, case.store)

    from app.modules.conversations.models import Conversation

    customer = Customer(tenant_id=tenant_id, name="عميل الشات")
    db.add(customer)
    await db.flush()
    conversation = Conversation(tenant_id=tenant_id, customer_id=customer.id, channel=case.channel)
    db.add(conversation)
    await db.flush()

    result = CaseResult(case_id=case.id, risk=case.risk)
    records: list[TurnRecord] = []
    for turn in case.turns:
        # the customer may quote an invoice number the case wrote; map it to the issued one
        body = turn.customer
        for written, issued in built.invoice_numbers.items():
            body = body.replace(written, issued)

        outcome = await run_customer_turn(
            db,
            TurnInput(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                agent_id=agent.id,
                customer_id=customer.id,
                inbound_message_id=uuid.uuid4(),
                body=body,
            ),
            runner=AgentRunner(gateway=gateway or AIGateway()),
        )
        await _apply_production_exit(db, tenant_id, conversation.id, outcome)
        tools, facts = await _tool_trace(db, outcome.run_id)
        observed = Observed(
            reply=outcome.reply or "",
            tools=tools,
            handed_over=await _handed_over(db, conversation.id, outcome),
            tool_numerals=facts,
            customer_numerals=frozenset(canonical_number(n) for n in _numbers_in(body)),
        )
        records.append(
            TurnRecord(turn.customer, observed, outcome.blocked_reason, outcome.grounding)
        )
        result.findings.extend(grade(turn.expect, observed))
    return result, records


def _numbers_in(text_: str) -> list[str]:
    import re

    return re.findall(_NUM, text_.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")))
