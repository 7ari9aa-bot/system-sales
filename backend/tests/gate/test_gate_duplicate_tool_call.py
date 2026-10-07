"""§176 gate scenario 19 — duplicate tool call (§15-16).

§15-16's rule: a retried run or a replayed inbound event that re-issues the SAME
tool call must not run its side effect twice (no double order, no double tag).
The guard is the ``(run_id, tool_call_id)`` idempotency key: ``AgentRunner._ex-
ecute_tool`` looks for a prior ``ToolCall`` row for that key and, when it finds
an ``ok`` result, returns the CACHED result without calling the handler again
(runtime.py:623-642). A unique constraint on ``(tenant_id, idempotency_key)``
makes the check-then-insert atomic across concurrent retries.

No gate file covered this scenario at all. Nothing else in ``test_gate.py`` even
reaches ``_execute_tool``.

These tests drive the REAL ``AgentRunner._execute_tool`` against a counting tool
registered in the live registry, and assert:

* the same ``(run, tool_call_id)`` executed twice runs the handler EXACTLY once
  and the second call returns the first call's stored result;
* only one ``ToolCall`` row exists for that key;
* a DIFFERENT ``tool_call_id`` on the same run is a distinct action and DOES
  execute again — proving the guard keys on the call identity rather than being
  a blanket "run nothing twice" that would pass vacuously.

DB-backed (real ``tool_calls`` rows + the real unique constraint); skips via
``db_url`` without an application database — CI-only evidence.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from app.modules.ai import tools as ai_tools
from app.modules.ai.models import Agent, AgentRun, AgentTool, ToolCall
from app.modules.ai.providers import ToolCallRequest
from app.modules.ai.runtime import AgentRunner

pytestmark = [pytest.mark.gate]

TOOL_NAME = "gate_counting_tool"


class _NoArgs(BaseModel):
    """A tool that takes no arguments."""


async def test_gate_a_replayed_tool_call_executes_its_handler_exactly_once(
    db, tenant_ctx, monkeypatch
) -> None:
    tid = tenant_ctx.tenant_id
    calls: list[int] = []

    async def handler(session, tenant_id, **kwargs) -> dict:
        calls.append(len(calls) + 1)
        return {"executed": len(calls), "nonce": uuid.uuid4().hex}

    spec = ai_tools.ToolSpec(
        name=TOOL_NAME,
        description="counts executions",
        args_schema=_NoArgs,
        handler=handler,
        risk_level="LOW",
    )
    monkeypatch.setitem(ai_tools.TOOLS, TOOL_NAME, spec)

    agent = Agent(tenant_id=tid, name="Gate Agent", model="fast", is_active=True)
    db.add(agent)
    await db.flush()
    agent_tool = AgentTool(
        tenant_id=tid, agent_id=agent.id, name=TOOL_NAME, policy={}, is_active=True
    )
    run = AgentRun(tenant_id=tid, agent_id=agent.id, status="running")
    db.add_all([agent_tool, run])
    await db.flush()

    runner = AgentRunner()
    request = ToolCallRequest(id="call-1", name=TOOL_NAME, arguments={})

    first = await runner._execute_tool(db, tid, run=run, agent_tools=[agent_tool], request=request)
    second = await runner._execute_tool(db, tid, run=run, agent_tools=[agent_tool], request=request)

    assert calls == [1], f"the handler ran {len(calls)} times for one tool_call_id"
    assert first["status"] == "ok" and second["status"] == "ok"
    # The replay returns the STORED result — byte-identical, no new side effect.
    assert second["result"] == first["result"]

    rows = (
        await db.execute(
            select(func.count())
            .select_from(ToolCall)
            .where(
                ToolCall.tenant_id == tid,
                ToolCall.idempotency_key == f"{run.id}:call-1",
            )
        )
    ).scalar_one()
    assert rows == 1, f"{rows} ToolCall rows for one (run, tool_call_id) key"


async def test_gate_a_different_tool_call_id_is_a_distinct_action(
    db, tenant_ctx, monkeypatch
) -> None:
    """Negative control: the guard keys on call identity, not 'never twice'."""
    tid = tenant_ctx.tenant_id
    calls: list[int] = []

    async def handler(session, tenant_id, **kwargs) -> dict:
        calls.append(len(calls) + 1)
        return {"executed": len(calls)}

    spec = ai_tools.ToolSpec(
        name=TOOL_NAME,
        description="counts executions",
        args_schema=_NoArgs,
        handler=handler,
        risk_level="LOW",
    )
    monkeypatch.setitem(ai_tools.TOOLS, TOOL_NAME, spec)

    agent = Agent(tenant_id=tid, name="Gate Agent", model="fast", is_active=True)
    db.add(agent)
    await db.flush()
    agent_tool = AgentTool(
        tenant_id=tid, agent_id=agent.id, name=TOOL_NAME, policy={}, is_active=True
    )
    run = AgentRun(tenant_id=tid, agent_id=agent.id, status="running")
    db.add_all([agent_tool, run])
    await db.flush()

    runner = AgentRunner()
    await runner._execute_tool(
        db,
        tid,
        run=run,
        agent_tools=[agent_tool],
        request=ToolCallRequest(id="call-a", name=TOOL_NAME, arguments={}),
    )
    await runner._execute_tool(
        db,
        tid,
        run=run,
        agent_tools=[agent_tool],
        request=ToolCallRequest(id="call-b", name=TOOL_NAME, arguments={}),
    )
    assert calls == [1, 2], "two distinct tool_call_ids must each execute once"
