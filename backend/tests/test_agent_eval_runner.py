"""The runner end to end with a SCRIPTED model: proves the pipe (case -> real shop -> real
runtime -> observed -> verdict), and that the verdict changes when the reply changes.

It says nothing about how a real model behaves; that is what the live evaluation is for.
"""

from __future__ import annotations

from app.modules.ai.gateway import AIGateway
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from tests.agent_eval.cases_core import CASES
from tests.agent_eval.runner import run_case


def _case(case_id: str):
    return next(c for c in CASES if c.id == case_id)


def _script(monkeypatch, *steps: ChatCompletionResult) -> None:
    queue = list(steps)

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        return queue.pop(0)

    monkeypatch.setattr(AIGateway, "chat", fake_chat)


def _calls(call_id: str, name: str, **arguments) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=None,
        tool_calls=[ToolCallRequest(id=call_id, name=name, arguments=arguments)],
        tokens_in=1,
        tokens_out=1,
        raw_model="m",
    )


def _says(text_: str) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=text_, tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
    )


async def test_a_correct_price_answer_passes(db, tenant_ctx, monkeypatch) -> None:
    case = _case("price-only-from-tool")
    _script(
        monkeypatch,
        _calls("c1", "search_catalog", query="تيشيرت قطن"),
        _says("التيشيرت القطن بـ 250 جنيه."),
    )

    result, records = await run_case(db, tenant_ctx.tenant_id, case)

    assert result.passed, [f"{f.check}: {f.detail}" for f in result.findings]
    assert "search_catalog" in records[0].observed.tools


async def test_an_invented_price_is_stopped_by_production_and_the_case_still_fails(
    db, tenant_ctx, monkeypatch
) -> None:
    """Two separate facts, both pinned.

    1. Production's grounding check withholds the reply and hands the chat to a person, so the
       customer never sees the invented price (the safety layer works).
    2. The CASE still fails: the question was answerable, and an agent that needs rescuing
       has not done its job. Safety holding is not the same as the agent being right.
    """
    case = _case("price-only-from-tool")
    _script(
        monkeypatch,
        _calls("c1", "search_catalog", query="تيشيرت قطن"),
        _says("التيشيرت القطن بـ 199 جنيه."),
        _says("التيشيرت القطن بـ 199 جنيه."),
    )

    result, records = await run_case(db, tenant_ctx.tenant_id, case)

    assert records[0].blocked_reason == "guardrail:grounding_failed"
    assert records[0].observed.reply == ""  # nothing invented reached the customer
    assert records[0].observed.handed_over  # and a person was brought in
    assert not result.passed
    assert {f.check for f in result.findings} >= {"handover", "contains_any"}


async def test_an_explicit_human_request_is_a_handover(db, tenant_ctx, monkeypatch) -> None:
    case = _case("explicit-human-request")
    _script(
        monkeypatch,
        _calls("c1", "handover_to_human", reason="customer_request", summary="طلب موظف"),
        _says("تمام، حد من الفريق هيكمل معاك."),
    )

    result, records = await run_case(db, tenant_ctx.tenant_id, case)

    assert records[0].observed.handed_over, records[0]
    assert result.passed, [f"{f.check}: {f.detail}" for f in result.findings]


async def test_an_out_of_scope_chat_needs_no_tool(db, tenant_ctx, monkeypatch) -> None:
    """A chat that is not about the shop is answered in words: no tool, no handover."""
    _script(
        monkeypatch,
        _says("ده خارج اختصاصي، أنا هنا أساعدك في منتجات المحل. تحب تعرف عن حاجة؟"),
    )

    result, records = await run_case(
        db, tenant_ctx.tenant_id, _case("out-of-scope-politely-returned")
    )

    assert not records[0].observed.handed_over
    assert result.passed, [f"{f.check}: {f.detail}" for f in result.findings]


async def test_a_stock_question_answered_without_looking_it_up_fails(
    db, tenant_ctx, monkeypatch
) -> None:
    """Regression for the lazy-agent flaw: a generic reply to a stock question used to pass.
    Now the case demands the catalogue was actually consulted."""
    _script(monkeypatch, _says("اتفضل، قولي تحب تعرف إيه عن المنتجات."))

    result, _ = await run_case(db, tenant_ctx.tenant_id, _case("plain-question-no-handover"))

    assert not result.passed
    assert "tools_called" in {f.check for f in result.findings}
