"""The customer agent through the REAL runtime, with only the model scripted.

Everything else is production code: the provisioned agent row, its tool rows,
registry authorization, argument validation, the handler, the ledger, the
grounding check and the turn coordinator. The earlier turn tests substitute the
whole runner, so they cannot see a mis-wired tool; these can.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.modules.ai.agents.customer.turn import TurnInput, run_customer_turn
from app.modules.ai.core.provisioning import provision_canonical_agents
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, KnowledgeItem
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.ai.runtime import AgentRunner


async def _customer_agent(db, tenant_id) -> Agent:
    await provision_canonical_agents(db, tenant_id)
    await db.flush()
    return (
        await db.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.kind == "customer")
        )
    ).scalar_one()


async def _conversation(db, tenant_id) -> uuid.UUID:
    from app.modules.conversations.models import Conversation
    from app.modules.customers.models import Customer

    customer = Customer(tenant_id=tenant_id, name="E2E Customer")
    db.add(customer)
    await db.flush()
    conversation = Conversation(tenant_id=tenant_id, customer_id=customer.id, channel="webchat")
    db.add(conversation)
    await db.flush()
    return conversation.id


def _script(monkeypatch, *steps: ChatCompletionResult) -> dict:
    """The model says exactly these things, in order; records what it was shown."""
    seen: dict = {"calls": []}
    queue = list(steps)

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        seen["calls"].append({"messages": messages, "tools": tools})
        return queue.pop(0)

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return seen


def _calls(name: str, **arguments) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=None,
        tool_calls=[ToolCallRequest(id="c1", name=name, arguments=arguments)],
        tokens_in=1,
        tokens_out=1,
        raw_model="m",
    )


def _says(text: str) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=text, tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
    )


async def _turn(db, tenant_id, agent, body):
    return await run_customer_turn(
        db,
        TurnInput(
            tenant_id=tenant_id,
            conversation_id=await _conversation(db, tenant_id),
            agent_id=agent.id,
            inbound_message_id=uuid.uuid4(),
            body=body,
        ),
        runner=AgentRunner(gateway=AIGateway()),
    )


async def test_the_model_only_sees_the_merged_store_tool(db, tenant_ctx, monkeypatch):
    agent = await _customer_agent(db, tenant_ctx.tenant_id)
    seen = _script(monkeypatch, _says("أهلا بيك"))

    await _turn(db, tenant_ctx.tenant_id, agent, "السلام عليكم")

    offered = {t["function"]["name"] for t in seen["calls"][0]["tools"]}
    assert "get_store_info" in offered
    assert "search_knowledge" not in offered, "two tools over one table are back"


async def test_a_policy_answered_from_store_info_reaches_the_customer(
    db, tenant_ctx, monkeypatch
):
    tenant_id = tenant_ctx.tenant_id
    agent = await _customer_agent(db, tenant_id)
    db.add(
        KnowledgeItem(
            tenant_id=tenant_id,
            title="سياسة الاسترجاع",
            source_type="text",
            content="الاسترجاع خلال 14 يوم من الاستلام.",
            visibility="customer_facing",
        )
    )
    await db.flush()
    seen = _script(
        monkeypatch,
        _calls("get_store_info", question="ينفع ارجع المنتج؟"),
        _says("أيوه، الاسترجاع خلال 14 يوم من الاستلام."),
    )

    outcome = await _turn(db, tenant_id, agent, "ينفع ارجع المنتج؟")

    tool_msgs = [m["content"] for m in seen["calls"][1]["messages"] if m.get("role") == "tool"]
    assert "updated_at" in tool_msgs[0] and "truncated" in tool_msgs[0]
    assert outcome.reply == "أيوه، الاسترجاع خلال 14 يوم من الاستلام."
    assert outcome.grounding == "ok"


async def test_the_same_policy_without_the_tool_is_withheld(db, tenant_ctx, monkeypatch):
    """The 14 is true in the store's data, but THIS run never read it."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _customer_agent(db, tenant_id)
    _script(monkeypatch, _says("أيوه، الاسترجاع خلال 14 يوم من الاستلام."))

    outcome = await _turn(db, tenant_id, agent, "ينفع ارجع المنتج؟")

    assert outcome.reply is None
    assert outcome.blocked_reason == "grounding:unsourced numeral: 14"


async def test_the_retired_tool_cannot_be_called_even_if_the_model_asks(
    db, tenant_ctx, monkeypatch
):
    tenant_id = tenant_ctx.tenant_id
    agent = await _customer_agent(db, tenant_id)
    seen = _script(
        monkeypatch,
        _calls("search_knowledge", query="الاسترجاع"),
        _says("ثواني هتأكدلك من الفريق."),
    )

    await _turn(db, tenant_id, agent, "ينفع ارجع؟")

    tool_msgs = [m["content"] for m in seen["calls"][1]["messages"] if m.get("role") == "tool"]
    assert "not authorized" in tool_msgs[0]
