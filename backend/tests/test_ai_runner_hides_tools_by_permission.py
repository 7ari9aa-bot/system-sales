"""The runner shows the model only the tools the asker may use, and refuses the rest by name.

Two layers on purpose. Hiding is the real protection (a model that never saw the tool cannot
choose it); the refusal at execution is the net for a model that names a tool it was never
offered, which providers do occasionally. Both must hold, so each is broken on its own below.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.modules.ai.core.registry import AgentDefinition, AgentRegistry
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentTool, ToolCall
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.ai.runtime import AgentRunner
from app.modules.ai.tools import TOOLS, ToolSpec, register_tool

pytestmark = pytest.mark.usefixtures("db")

KIND = "zz_probe"
GATED = "zz_gated_profit"
OPEN = "zz_open_metric"


class _NoArgs(BaseModel):
    pass


def _result(content=None, tool_calls=None) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=content, tool_calls=tool_calls or [], tokens_in=1, tokens_out=1, raw_model="fake"
    )


@pytest.fixture
def gated_tools():
    ran = {"gated": 0}

    async def gated(session, tenant_id, **_):
        ran["gated"] += 1
        return {"profit": 123}

    async def open_(session, tenant_id, **_):
        return {"orders": 4}

    register_tool(
        ToolSpec(
            name=GATED, description="g", args_schema=_NoArgs, handler=gated, requires="finance:read"
        )
    )
    register_tool(ToolSpec(name=OPEN, description="o", args_schema=_NoArgs, handler=open_))
    # The runner drops any tool the agent KIND does not list, before the permission filter even
    # runs, so the probe kind has to list both or every test here would pass on an empty set.
    AgentRegistry.register(
        AgentDefinition(
            kind=KIND,
            name="probe",
            description="permission-visibility probe",
            system_prompt_template="p",
            allowed_tools=[GATED, OPEN],
            default_tools=[GATED, OPEN],
        ),
        allow_override=True,
    )
    yield ran
    AgentRegistry._definitions.pop(KIND, None)
    TOOLS.pop(GATED, None)
    TOOLS.pop(OPEN, None)


async def _agent(db, tenant_id) -> Agent:
    agent = Agent(tenant_id=tenant_id, name="Owner", kind=KIND, model="fast", system_prompt="p")
    db.add(agent)
    await db.flush()
    for name in (GATED, OPEN):
        db.add(AgentTool(tenant_id=tenant_id, agent_id=agent.id, name=name, policy={}))
    await db.flush()
    return agent


def _patch(monkeypatch, results):
    seen = {"tools": []}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kw):
        seen["tools"].append([t["function"]["name"] for t in (tools or [])])
        return results[min(len(seen["tools"]), len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return seen


async def _run(db, tenant_ctx, agent, **kw):
    return await AgentRunner(gateway=AIGateway()).run(
        db, tenant_ctx.tenant_id, agent_id=agent.id, user_message="profit?", **kw
    )


async def test_the_model_is_not_offered_a_tool_the_asker_may_not_use(
    db, tenant_ctx, monkeypatch, gated_tools
):
    agent = await _agent(db, tenant_ctx.tenant_id)
    seen = _patch(monkeypatch, [_result(content="ok")])
    await _run(db, tenant_ctx, agent, actor_permissions={"analytics:read"})
    assert seen["tools"][0] == [OPEN]


async def test_the_model_is_offered_the_tool_when_the_asker_holds_the_permission(
    db, tenant_ctx, monkeypatch, gated_tools
):
    agent = await _agent(db, tenant_ctx.tenant_id)
    seen = _patch(monkeypatch, [_result(content="ok")])
    await _run(db, tenant_ctx, agent, actor_permissions={"finance:read"})
    assert sorted(seen["tools"][0]) == sorted([GATED, OPEN])


async def test_a_gated_tool_the_model_names_anyway_is_refused_and_never_runs(
    db, tenant_ctx, monkeypatch, gated_tools
):
    agent = await _agent(db, tenant_ctx.tenant_id)
    _patch(
        monkeypatch,
        [
            _result(tool_calls=[ToolCallRequest(id="c1", name=GATED, arguments={})]),
            _result(content="cannot"),
        ],
    )
    result = await _run(db, tenant_ctx, agent, actor_permissions={"analytics:read"})
    assert result.tool_calls_made[0]["status"] == "denied"
    assert gated_tools["gated"] == 0
    row = (
        (await db.execute(select(ToolCall).where(ToolCall.tenant_id == tenant_ctx.tenant_id)))
        .scalars()
        .one()
    )
    assert row.status == "denied" and row.result is None


async def test_an_unknown_asker_sees_only_the_ungated_tools(
    db, tenant_ctx, monkeypatch, gated_tools
):
    """A caller that does not say who is asking gets the safe subset, never everything."""
    agent = await _agent(db, tenant_ctx.tenant_id)
    seen = _patch(monkeypatch, [_result(content="ok")])
    await _run(db, tenant_ctx, agent)
    assert seen["tools"][0] == [OPEN]


async def test_an_agent_tool_with_no_registered_spec_is_left_alone(
    db, tenant_ctx, monkeypatch, gated_tools
):
    """Hiding is for tools that declare a requirement. A name with no spec has none to read,
    and dropping it would turn the honest "unknown tool" answer into "not enabled"."""
    agent = await _agent(db, tenant_ctx.tenant_id)
    db.add(AgentTool(tenant_id=tenant_ctx.tenant_id, agent_id=agent.id, name="zz_ghost", policy={}))
    await db.flush()
    from app.modules.ai.runtime import _tools_the_asker_may_use

    rows = (
        (await db.execute(select(AgentTool).where(AgentTool.agent_id == agent.id))).scalars().all()
    )
    kept = {t.name for t in _tools_the_asker_may_use(rows, {"analytics:read"})}
    assert kept == {OPEN, "zz_ghost"}
