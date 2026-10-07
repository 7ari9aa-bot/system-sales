"""Tool error containment (AI hardening) — nothing internal reaches the model.

A tool handler's unexpected exception used to become `str(exc)` inside the
tool result the runner feeds back to the model: SQL fragments, connection
strings, filesystem paths, keys and provider bodies could all enter the
model's context (and from there, customer-visible replies). The boundary is
now: DESIGNED domain errors are data and pass through; everything else is
collapsed to a fixed generic outcome with the full traceback in the logs.

Each test drives the REAL AgentRunner with a stubbed gateway (same pattern
as test_ai_runtime_vision) and inspects the messages of the SECOND model
call — the one that carries the tool result.
"""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import BaseModel

from app.core.errors import ConflictError
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentTool
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.ai.runtime import AgentRunner
from app.modules.ai.tools import ToolSpec, register_tool

# A fingerprint no legitimate tool output would carry — each matrix entry
# raises an exception whose message embeds it, and the assertions check that
# NEITHER the model context NOR the reply ever contains it.
_MATRIX = {
    "connection_string": "postgresql+asyncpg://app:hunter2@db.internal:5432/sales",
    "api_key": "sk-live-9f8e7d6c5b4a3f2e1d0c",
    "filesystem_path": r"C:\Users\svc-agent\.secrets\provider.pem",
    "sql_fragment": "SELECT * FROM order_payments WHERE token_hash = $1",
    "stack_trace": 'Traceback (most recent call last):\n  File "handlers.py", line 42',
    "provider_body": '{"error":{"code":"NOT_ENOUGH_BALANCE","internal_ref":"acct-77"}}',
}

CONSUMED_SUFFIX = uuid.uuid4().hex[:6]


class _EmptyArgs(BaseModel):
    pass


def _register_boom_tool(name: str, exc: Exception, *, handler=None) -> None:
    def _boom(session, tenant_id, **kwargs):
        raise exc

    register_tool(
        ToolSpec(
            name=name,
            description="a tool that fails",
            args_schema=_EmptyArgs,
            handler=handler or _boom,
            risk_level="LOW",
        )
    )


def _patch_gateway(monkeypatch) -> dict:
    """Call 1 asks for the tool; call 2 answers plainly after seeing its result."""
    calls = {"count": 0, "list": []}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        calls["count"] += 1
        calls["list"].append({"messages": messages, "tools": tools})
        if calls["count"] == 1:
            return ChatCompletionResult(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name=_tool_name(), arguments={})],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            )
        return ChatCompletionResult(
            content="تمام", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return calls


_TOOL_NAME = f"boom_{CONSUMED_SUFFIX}"


def _tool_name() -> str:
    return _TOOL_NAME


async def _agent_for(db, tenant_id) -> Agent:
    agent = Agent(tenant_id=tenant_id, name="Sales Agent", model="fast", system_prompt="You sell.")
    db.add(agent)
    await db.flush()
    db.add(AgentTool(tenant_id=tenant_id, agent_id=agent.id, name=_TOOL_NAME, policy={}))
    await db.flush()
    return agent


def _model_tool_messages(calls: dict) -> list[str]:
    """The contents of the tool-role messages the SECOND model call saw."""
    second = calls["list"][1]["messages"]
    return [m["content"] for m in second if m.get("role") == "tool"]


async def _run(db, tenant_id, agent, conversation_id=None):
    return await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_id,
        agent_id=agent.id,
        conversation_id=conversation_id,
        user_message="شغّل الأداة",
    )


@pytest.mark.parametrize("kind", sorted(_MATRIX))
async def test_unexpected_tool_error_leaks_nothing_to_the_model(
    db, tenant_ctx, monkeypatch, caplog, kind
):
    secret = _MATRIX[kind]
    _register_boom_tool(_TOOL_NAME, RuntimeError(secret))
    agent = await _agent_for(db, tenant_ctx.tenant_id)
    calls = _patch_gateway(monkeypatch)

    with caplog.at_level("ERROR", logger="app.modules.ai.runtime"):
        result = await _run(db, tenant_ctx.tenant_id, agent)

    # The model's tool message carries only the fixed generic outcome.
    contents = json.dumps(_model_tool_messages(calls))
    assert secret not in contents
    assert '"error": "tool failed unexpectedly"' in contents.replace("\\n", "\n") or any(
        '"error": "tool failed unexpectedly"' in c for c in _model_tool_messages(calls)
    )
    # The loop COMPLETED: the model answered plainly after the contained
    # failure.
    assert result.content == "تمام"

    # The full detail went to the LOGS, not the model.
    assert secret in caplog.text


async def test_designed_domain_error_passes_through_as_data(db, tenant_ctx, monkeypatch):
    """A tool that MEANS to refuse (insufficient stock, unknown id...) says so:
    the message is part of the tool's contract, not a leak."""
    refusal = f"insufficient stock for SKU-{CONSUMED_SUFFIX}"
    _register_boom_tool(_TOOL_NAME, ConflictError(refusal))
    agent = await _agent_for(db, tenant_ctx.tenant_id)
    calls = _patch_gateway(monkeypatch)

    result = await _run(db, tenant_ctx.tenant_id, agent)

    contents = _model_tool_messages(calls)
    assert any(refusal in c for c in contents)
    assert result.content == "تمام"


async def test_a_db_failure_inside_the_tool_does_not_poison_the_run(db, tenant_ctx, monkeypatch):
    """A statement-level DB error inside a handler aborts the transaction —
    without the savepoint the failed ToolCall insert would die on a poisoned
    session and the whole run would come down with it. The savepoint rolls the
    handler's partial work back; the run completes and the ToolCall row
    records the failure."""

    from sqlalchemy import text

    from app.modules.ai.models import ToolCall

    async def _db_boom(session, tenant_id, **kwargs):
        # A real statement-level failure (division by zero is a runtime
        # error in Postgres) — the exact shape that poisons a transaction.
        await session.execute(text("SELECT 1/0"))

    _register_boom_tool(_TOOL_NAME, RuntimeError("unused"), handler=_db_boom)
    agent = await _agent_for(db, tenant_ctx.tenant_id)
    _patch_gateway(monkeypatch)

    result = await _run(db, tenant_ctx.tenant_id, agent)

    assert result.content == "تمام"
    row = (
        await db.execute(
            ToolCall.__table__.select().where(
                ToolCall.__table__.c.run_id == result.run_id,
                ToolCall.__table__.c.name == _TOOL_NAME,
            )
        )
    ).first()
    assert row is not None
    assert row.status == "error"
    assert row.error == "tool failed unexpectedly"
