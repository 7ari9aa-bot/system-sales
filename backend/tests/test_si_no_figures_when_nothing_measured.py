"""A tool that measured nothing tells the model it has no figure to quote.

An empty till returns no facts, so the number gate has nothing to allow and refuses every figure
in the answer. The model wrote "the last 30 days (17 Oct to 15 Nov)" about it, the gate refused,
and the owner waited for a second model call (36 s). The honest answer needs no figure."""

from __future__ import annotations

import uuid

from app.modules.ai.agents.sales_intelligence import tools as si
from app.modules.ai.agents.sales_intelligence.agent import run_sales_analysis
from app.modules.ai.agents.sales_intelligence.tools import (
    NO_FIGURES_NOTE,
    _say_it_without_figures,
)
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import AgentTool
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.ai.tools import TOOLS
from tests.test_si_agent import _seed


def _wrapped(result):
    async def handler(session, tenant_id, **kw):
        return result

    return _say_it_without_figures(handler)


async def _call(result):
    return await _wrapped(result)(None, uuid.uuid4())


async def test_an_empty_result_gets_the_note_and_keeps_its_own_limits():
    out = await _call({"status": "no_data", "facts": [], "limitations": ["no register yet"]})
    assert out["limitations"] == ["no register yet", NO_FIGURES_NOTE]


async def test_a_result_with_no_limitations_key_still_gets_it():
    out = await _call({"status": "no_data", "facts": []})
    assert out["limitations"] == [NO_FIGURES_NOTE]


async def test_it_is_never_added_twice():
    first = await _call({"status": "no_data", "facts": [], "limitations": [NO_FIGURES_NOTE]})
    assert first["limitations"].count(NO_FIGURES_NOTE) == 1


async def test_a_result_that_measured_something_is_untouched():
    result = {"status": "ok", "facts": [{"metric": "m"}], "limitations": ["x"]}
    assert await _call(result) == result


async def test_ok_with_no_facts_is_untouched():
    """Only 'no_data' means nothing was measured; a find that matched nobody is its own case."""
    result = {"status": "ok", "facts": [], "limitations": ["x"]}
    assert await _call(result) == result


async def test_no_data_that_still_carries_a_fact_is_untouched():
    result = {"status": "no_data", "facts": [{"metric": "m"}], "limitations": []}
    assert await _call(result) == result


async def test_a_non_dict_result_passes_through():
    for odd in (None, [], "text"):
        assert await _call(odd) == odd


async def test_the_input_is_not_mutated():
    result = {"status": "no_data", "facts": [], "limitations": ["a"]}
    await _call(result)
    assert result["limitations"] == ["a"]


def test_the_note_forbids_figures_periods_and_dates():
    for word in ("number", "period", "date", "last N days"):
        assert word in NO_FIGURES_NOTE


async def test_the_real_cashier_tool_for_a_shop_with_no_register_carries_it(db, tenant_ctx):
    """The wiring: through the registered tool, as the model reaches it (the production case)."""
    TOOLS.pop("si_cashier_summary", None)
    si.register_si_tools()
    handler = TOOLS["si_cashier_summary"].handler
    out = await handler(db, tenant_ctx.tenant_id, days=30)
    assert out["status"] == "no_data"
    assert NO_FIGURES_NOTE in out["limitations"]
    assert "no cashier register is set up yet, so there are no till sales" in out["limitations"]


async def test_every_registered_tool_is_wrapped():
    TOOLS.pop("si_cashier_summary", None)
    si.register_si_tools()
    names = [n for n in TOOLS if n.startswith("si_")]
    assert names
    for n in names:
        assert getattr(TOOLS[n].handler, "says_it_without_figures", False), n


def test_the_rewrite_instruction_speaks_to_the_owner_not_to_a_reviewer():
    """Production: the rewrite began 'OK, here is the answer after the correction', talking to the
    reviewer. The instruction now says the owner reads it as written and not to say it is a redo."""
    from app.core.guardrails import screen_inbound
    from app.modules.ai.agents.sales_intelligence.coverage import build_rejection_instruction

    text = build_rejection_instruction(["30", "17"])
    assert "صاحب المحل هيقرأ" in text
    assert "تصحيح" in text
    assert "30، 17" in text
    # it must still pass the guard the runner applies to what it sends
    assert screen_inbound(text).decision == "allow"


# ------------------------------ a whole round, as production ran it -----------------------------

OWNER_QUESTION = "اداء وكيل المبيعات اي"
FIGURES_DRAFT = "آخر 30 يوم (من 17 أكتوبر لحد 15 نوفمبر) صفر فواتير من الكاشير."
PLAIN_ANSWER = "الكاشير لسه ما اتجهّزش عندك، فمفيش مبيعات كاشير مسجلة."


async def _round(db, tenant_ctx, monkeypatch):
    """The model asks for the till, then answers. It writes the figures draft unless the tool
    result it was handed tells it there is nothing to quote, exactly the production failure."""
    TOOLS.pop("si_cashier_summary", None)
    si.register_si_tools()
    agent = await _seed(db, tenant_ctx.tenant_id)
    db.add(AgentTool(tenant_id=tenant_ctx.tenant_id, agent_id=agent.id, name="si_cashier_summary"))
    await db.flush()

    seen: list[list[dict]] = []

    async def fake(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        seen.append(messages)
        if len(seen) == 1:
            return ChatCompletionResult(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="c1", name="si_cashier_summary", arguments={"days": 30, "limit": 15}
                    )
                ],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            )
        told = any(NO_FIGURES_NOTE in str(m.get("content", "")) for m in messages)
        return ChatCompletionResult(
            content=PLAIN_ANSWER if told else FIGURES_DRAFT,
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )

    monkeypatch.setattr(AIGateway, "chat", fake)
    result = await run_sales_analysis(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        question=OWNER_QUESTION,
        actor_permissions={"analytics:read", "orders:read"},
    )
    return result, seen


async def test_the_model_is_handed_the_note_and_answers_in_one_pass(db, tenant_ctx, monkeypatch):
    result, seen = await _round(db, tenant_ctx, monkeypatch)
    assert any(NO_FIGURES_NOTE in str(m.get("content", "")) for m in seen[-1])
    assert result.answer == PLAIN_ANSWER
    assert result.guardrail_reason is None
    # tool round + the answer: no third call to rewrite a rejected draft (it cost 36 s)
    assert len(seen) == 2
