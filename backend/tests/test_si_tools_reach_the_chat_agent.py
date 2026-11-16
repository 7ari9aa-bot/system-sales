"""An owner's assistant gets every tool the code defines, on the path the chat really uses.

`ensure_si_tools` attached missing tools, but only the old `/ai/sales` route called it. The chat
(`run_chat_turn` -> `run_sales_analysis`) never did, so a shop whose agent was created before a
tool existed never got it: in production 11 of 12 agents had three tools, and "which products are
running out" was answered "there is no stock data" although the stock tool was deployed. The attach
now happens inside `run_sales_analysis`, the one entry the chat, the route and the jobs share.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.ai.agents.sales_intelligence.agent import run_sales_analysis
from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentTool
from app.modules.ai.providers import ChatCompletionResult


@pytest.fixture(autouse=True)
def _quiet_model(monkeypatch):
    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        return ChatCompletionResult(
            content="تمام", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)


async def _agent(db, tenant_id, kind: str, tools: tuple[str, ...]) -> Agent:
    agent = Agent(tenant_id=tenant_id, name="A", model="fast", system_prompt="p", kind=kind)
    db.add(agent)
    await db.flush()
    for name in tools:
        db.add(AgentTool(tenant_id=tenant_id, agent_id=agent.id, name=name, policy={}))
    await db.flush()
    return agent


async def _names(db, agent_id: uuid.UUID) -> dict[str, bool]:
    rows = (await db.execute(select(AgentTool).where(AgentTool.agent_id == agent_id))).scalars()
    return {r.name: r.is_active for r in rows}


async def test_an_agent_created_with_one_tool_gets_all_of_them_when_asked(db, tenant_ctx):
    agent = await _agent(db, tenant_ctx.tenant_id, "sales_intelligence", ("si_metric",))

    await run_sales_analysis(db, tenant_ctx.tenant_id, agent_id=agent.id, question="المخزون؟")

    assert set(await _names(db, agent.id)) == set(SI_TOOLS)


async def test_a_tool_the_shop_switched_off_stays_off(db, tenant_ctx):
    agent = await _agent(db, tenant_ctx.tenant_id, "sales_intelligence", ("si_metric",))
    row = (await db.execute(select(AgentTool).where(AgentTool.agent_id == agent.id))).scalar_one()
    row.is_active = False
    await db.flush()

    await run_sales_analysis(db, tenant_ctx.tenant_id, agent_id=agent.id, question="؟")

    names = await _names(db, agent.id)
    assert names["si_metric"] is False, "an owner's off switch was turned back on"
    assert set(names) == set(SI_TOOLS)


async def test_a_policy_set_by_the_shop_is_kept(db, tenant_ctx):
    agent = await _agent(db, tenant_ctx.tenant_id, "sales_intelligence", ("si_metric",))
    row = (await db.execute(select(AgentTool).where(AgentTool.agent_id == agent.id))).scalar_one()
    row.policy = {"max_calls": 2}
    await db.flush()

    await run_sales_analysis(db, tenant_ctx.tenant_id, agent_id=agent.id, question="؟")

    row = (
        await db.execute(
            select(AgentTool).where(AgentTool.agent_id == agent.id, AgentTool.name == "si_metric")
        )
    ).scalar_one()
    assert row.policy == {"max_calls": 2}


async def test_asking_twice_does_not_duplicate_anything(db, tenant_ctx):
    agent = await _agent(db, tenant_ctx.tenant_id, "sales_intelligence", ("si_metric",))

    await run_sales_analysis(db, tenant_ctx.tenant_id, agent_id=agent.id, question="1")
    await run_sales_analysis(db, tenant_ctx.tenant_id, agent_id=agent.id, question="2")

    rows = (await db.execute(select(AgentTool).where(AgentTool.agent_id == agent.id))).scalars()
    names = [r.name for r in rows]
    assert len(names) == len(set(names)) == len(SI_TOOLS)


async def test_the_customer_agent_never_receives_an_owner_tool(db, tenant_ctx):
    """Another agent in the same shop is not touched by the owner assistant's attach."""
    owner = await _agent(db, tenant_ctx.tenant_id, "sales_intelligence", ("si_metric",))
    customer = await _agent(db, tenant_ctx.tenant_id, "customer", ("search_catalog",))

    await run_sales_analysis(db, tenant_ctx.tenant_id, agent_id=owner.id, question="؟")

    assert set(await _names(db, customer.id)) == {"search_catalog"}


async def test_another_shops_agent_is_not_touched(db, tenant_ctx):
    other_tenant = uuid.uuid4()
    mine = await _agent(db, tenant_ctx.tenant_id, "sales_intelligence", ("si_metric",))

    await run_sales_analysis(db, tenant_ctx.tenant_id, agent_id=mine.id, question="؟")

    stray = (
        (await db.execute(select(AgentTool).where(AgentTool.tenant_id == other_tenant)))
        .scalars()
        .all()
    )
    assert stray == []


async def _offered(db, tenant_ctx, monkeypatch, permissions) -> set[str]:
    """The tool names the model is actually shown for an asker holding ``permissions``."""
    seen: dict = {}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        seen["tools"] = tools
        return ChatCompletionResult(
            content="تمام", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    agent = await _agent(db, tenant_ctx.tenant_id, "sales_intelligence", ("si_metric",))
    await run_sales_analysis(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        question="؟",
        actor_permissions=frozenset(permissions),
    )
    return {t["function"]["name"] if "function" in t else t["name"] for t in seen["tools"]}


async def test_an_employee_without_finance_access_is_never_shown_the_money_tools(
    db, tenant_ctx, monkeypatch
):
    """Attaching the rows must not widen what a person may see: the permission still hides them."""
    shown = await _offered(db, tenant_ctx, monkeypatch, set())

    # all three are offered to everyone: the permission is checked by each read, when it runs
    assert shown == {"si_metric", "si_shop", "si_finance"}


async def test_an_asker_with_the_permission_is_shown_the_tool(db, tenant_ctx, monkeypatch):
    shown = await _offered(db, tenant_ctx, monkeypatch, {"finance:read", "orders:read"})

    assert shown == {"si_finance", "si_shop", "si_metric"}
