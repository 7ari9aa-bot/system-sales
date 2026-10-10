"""Multi-turn history injection for the SI chat (spec §SI-chat).

`history` carries bounded prior turns, server-built from ai_chat_messages,
between the system message and the current user turn — narrative context
only, never numeric authority. The customer-messaging path stays untouched:
passing history must not acquire a conversation lease or look up a
conversation. DB-backed (CI runs it; local skips without DATABASE_URL_APP_ADMIN).
"""

from __future__ import annotations

from sqlalchemy import select

from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentRun
from app.modules.ai.providers import ChatCompletionResult
from app.modules.ai.runtime import AgentRunner


def _result(content=None, tool_calls=None, tokens_in=0, tokens_out=0) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=content,
        tool_calls=tool_calls or [],
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )


def _patch_gateway_chat(monkeypatch, results: list[ChatCompletionResult]) -> dict:
    calls: dict = {"count": 0, "messages": None}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        calls["count"] += 1
        calls["messages"] = messages
        return results[min(calls["count"], len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return calls


async def _si_agent(db, tenant_id) -> Agent:
    agent = Agent(
        tenant_id=tenant_id,
        kind="sales_intelligence",
        name="Sales Intelligence",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    return agent


HISTORY = [
    {"role": "user", "content": "قارن مبيعات الشهر ده باللي فات."},
    {"role": "assistant", "content": "الشهر ده أعلى بنسبة 12 بالمئة."},
]


async def test_history_lands_between_system_and_user_turn(db, tenant_ctx, monkeypatch):
    agent = await _si_agent(db, tenant_ctx.tenant_id)
    calls = _patch_gateway_chat(monkeypatch, [_result(content="إجابة تحليلية")])

    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        history=HISTORY,
        user_message="طب إيه سبب الانخفاض؟",
    )

    messages = calls["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1] == HISTORY[0]
    assert messages[2] == HISTORY[1]
    assert messages[-1] == {"role": "user", "content": "طب إيه سبب الانخفاض؟"}
    run_row = (
        (await db.execute(select(AgentRun).where(AgentRun.tenant_id == tenant_ctx.tenant_id)))
        .scalars()
        .one()
    )
    assert run_row.status == "succeeded"


async def test_history_does_not_enter_the_customer_messaging_path(
    db, tenant_ctx, monkeypatch
):
    import app.core.lease as lease

    def _explode(*_a, **_k):
        raise AssertionError("conversation lease must never be acquired for chat history")

    monkeypatch.setattr(lease, "conversation_lease", _explode)
    agent = await _si_agent(db, tenant_ctx.tenant_id)
    calls = _patch_gateway_chat(monkeypatch, [_result(content="إجابة")])

    result = await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        history=HISTORY,
        user_message="سؤال تاني",
    )

    assert result.content == "إجابة"
    assert calls["messages"][1] == HISTORY[0]
