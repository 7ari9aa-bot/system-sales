"""Spec §135 - the HIGH-risk approval gate must PREVENT execution.

The failure this guards against is subtle and dangerous: an earlier version
created the ApprovalRequest, parked the run in WAITING_APPROVAL, and then
called the tool handler anyway. The UI showed "waiting for approval" while the
order had already been created / the refund already issued. A gate that only
records an intent to ask is worse than no gate, because it looks like control.

These tests are database-backed (they need a session for the approval row and
the tool-call audit row), so they skip when no database is configured - CI runs
them.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlalchemy import select

from app.modules.ai.approvals import ApprovalService
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentRun, AgentTool, ApprovalRequest
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.ai.runtime import AgentRunner
from app.modules.ai.tools import ToolSpec, register_tool

# Records every time the dangerous handler actually ran.
EXECUTED: list[str] = []

DANGEROUS_TOOL = "purge_customer_data"


class _Args(BaseModel):
    note: str = "default"


async def _dangerous_handler(session, tenant_id, *, note: str = "default", **kwargs):
    EXECUTED.append(note)
    return {"purged": True}


def _result(content=None, tool_calls=None) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=content,
        tool_calls=tool_calls or [],
        tokens_in=0,
        tokens_out=0,
        raw_model="fake-model",
    )


def _patch_gateway(monkeypatch, results: list[ChatCompletionResult]) -> None:
    calls = {"n": 0}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        calls["n"] += 1
        return results[min(calls["n"], len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake_chat)


async def _agent(db, tenant_id) -> Agent:
    agent = Agent(
        tenant_id=tenant_id, name="Ops Agent", model="fast", system_prompt="Be careful."
    )
    db.add(agent)
    await db.flush()
    db.add(
        AgentTool(tenant_id=tenant_id, agent_id=agent.id, name=DANGEROUS_TOOL, policy={})
    )
    await db.flush()
    return agent


def _request_call() -> ChatCompletionResult:
    return _result(
        tool_calls=[
            ToolCallRequest(id="c1", name=DANGEROUS_TOOL, arguments={"note": "now"})
        ]
    )


async def _conversation(db, tenant_id):
    """A real conversation row — agent_runs.conversation_id is a real FK, so a
    random uuid would fail on insert rather than exercise the gate."""
    from app.modules.conversations.service import ConversationService
    from app.modules.customers.service import CustomerService

    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        channel="whatsapp",
        external_id=f"wa-{uuid.uuid4().hex[:10]}",
        name="Ops Customer",
    )
    return await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="whatsapp"
    )


async def test_high_risk_tool_does_not_execute_before_approval(db, tenant_ctx, monkeypatch):
    """The action must NOT happen — the run parks and asks first."""
    EXECUTED.clear()
    register_tool(
        ToolSpec(
            name=DANGEROUS_TOOL,
            description="HIGH-risk: destroys customer data",
            args_schema=_Args,
            handler=_dangerous_handler,
            risk_level="HIGH",
        )
    )
    agent = await _agent(db, tenant_ctx.tenant_id)
    _patch_gateway(monkeypatch, [_request_call(), _result(content="waiting")])

    await AgentRunner(gateway=AIGateway()).run(
        db, tenant_ctx.tenant_id, agent_id=agent.id, user_message="purge it"
    )

    assert EXECUTED == [], "a HIGH-risk tool ran before a human approved it"

    approvals = (
        await db.execute(
            select(ApprovalRequest).where(ApprovalRequest.tenant_id == tenant_ctx.tenant_id)
        )
    ).scalars().all()
    assert len(approvals) == 1
    assert approvals[0].status == "PENDING"
    assert approvals[0].action == DANGEROUS_TOOL
    assert approvals[0].risk_level == "HIGH"
    # The arguments are captured so the human can see what they are approving.
    assert approvals[0].payload.get("arguments", {}).get("note") == "now"

    run = (
        await db.execute(select(AgentRun).where(AgentRun.agent_id == agent.id))
    ).scalars().one()
    assert run.status == "WAITING_APPROVAL"


async def test_an_approved_action_executes_once_and_is_consumed(
    db, tenant_ctx, monkeypatch
):
    """Resume: the granted approval releases exactly one execution."""
    EXECUTED.clear()
    register_tool(
        ToolSpec(
            name=DANGEROUS_TOOL,
            description="HIGH-risk: destroys customer data",
            args_schema=_Args,
            handler=_dangerous_handler,
            risk_level="HIGH",
        )
    )
    agent = await _agent(db, tenant_ctx.tenant_id)
    conversation_id = (await _conversation(db, tenant_ctx.tenant_id)).id

    # First pass: parked, nothing executed.
    _patch_gateway(monkeypatch, [_request_call(), _result(content="waiting")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation_id,
    )
    assert EXECUTED == []

    approval = (
        await db.execute(
            select(ApprovalRequest).where(ApprovalRequest.tenant_id == tenant_ctx.tenant_id)
        )
    ).scalars().one()
    await ApprovalService.decide(
        db,
        tenant_ctx.tenant_id,
        approval.id,
        decision="APPROVED",
        decided_by_user_id=tenant_ctx.user.id,
    )
    await db.flush()

    # Second pass (the resume): the gate finds the grant, executes once, consumes it.
    _patch_gateway(monkeypatch, [_request_call(), _result(content="done")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation_id,
    )

    assert EXECUTED == ["now"], "the approved action did not execute exactly once"
    refreshed = (
        await db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == approval.id)
        )
    ).scalars().one()
    assert refreshed.consumed_at is not None, "the approval was not consumed"


async def test_a_consumed_approval_does_not_authorize_a_second_run(
    db, tenant_ctx, monkeypatch
):
    """One approval = one action. Otherwise a resume loop would re-fire it."""
    EXECUTED.clear()
    register_tool(
        ToolSpec(
            name=DANGEROUS_TOOL,
            description="HIGH-risk: destroys customer data",
            args_schema=_Args,
            handler=_dangerous_handler,
            risk_level="HIGH",
        )
    )
    agent = await _agent(db, tenant_ctx.tenant_id)
    conversation_id = (await _conversation(db, tenant_ctx.tenant_id)).id

    _patch_gateway(monkeypatch, [_request_call(), _result(content="waiting")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation_id,
    )
    approval = (
        await db.execute(
            select(ApprovalRequest).where(ApprovalRequest.tenant_id == tenant_ctx.tenant_id)
        )
    ).scalars().one()
    await ApprovalService.decide(
        db,
        tenant_ctx.tenant_id,
        approval.id,
        decision="APPROVED",
        decided_by_user_id=tenant_ctx.user.id,
    )
    await db.flush()

    for _ in range(2):
        _patch_gateway(monkeypatch, [_request_call(), _result(content="again")])
        await AgentRunner(gateway=AIGateway()).run(
            db,
            tenant_ctx.tenant_id,
            agent_id=agent.id,
            user_message="purge it again",
            conversation_id=conversation_id,
        )

    assert EXECUTED == ["now"], f"expected exactly one execution, got {EXECUTED}"
