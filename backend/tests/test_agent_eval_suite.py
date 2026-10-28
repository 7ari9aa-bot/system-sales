"""The whole golden set, run as one release gate.

Two modes, SAME code path:

* default (CI): a scripted stand-in model that behaves like a competent agent, built from the
  reference replies. It proves the pipe (cases -> real shop -> real runtime -> graders ->
  verdict) and that a competent agent SHIPS. It says nothing about any real model.
* ``-m live_eval`` with the three AI_*_PRIMARY variables set: the real gateway and a real
  model. THIS is the measurement. It is skipped by default because it costs money; if you
  ask for it and any variable is missing, it FAILS loudly rather than use a stand-in.
"""

from __future__ import annotations

import os

import pytest

from app.modules.ai.gateway import AIGateway
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from tests.agent_eval import judge
from tests.agent_eval.cases_channels import CASES as CHANNELS
from tests.agent_eval.cases_core import CASES as CORE
from tests.agent_eval.cases_failure_modes import CASES as MODES
from tests.agent_eval.cases_flows import CASES as FLOWS
from tests.agent_eval.cases_self_resolve import CASES as SELF
from tests.agent_eval.reference_replies import GOOD
from tests.agent_eval.report import render, summarise
from tests.agent_eval.runner import run_case

ALL = CORE + FLOWS + MODES + SELF + CHANNELS

# What the competent stand-in does for a tool it is "calling": the minimal valid arguments.
_TOOL_ARGS = {
    "search_catalog": {"query": "تيشيرت"},
    "get_store_info": {"question": "سياسة"},
    "find_support_playbook": {"problem": "الطلب اتأخر"},
    "handover_to_human": {"reason": "customer_request", "summary": "طلب العميل موظف"},
    "get_my_orders": {"number": "x"},
    "get_product_details": {"product_id": "x"},
}


def _competent_model(monkeypatch, case) -> None:
    """Replay the reference behaviour for this case: call its tools, then say its reply."""
    steps: list[ChatCompletionResult] = []
    for observed in GOOD[case.id]:
        for i, tool in enumerate(observed.tools):
            if tool in _TOOL_ARGS:
                steps.append(
                    ChatCompletionResult(
                        content=None,
                        tool_calls=[
                            ToolCallRequest(
                                id=f"c{len(steps)}-{i}", name=tool, arguments=_TOOL_ARGS[tool]
                            )
                        ],
                        tokens_in=1,
                        tokens_out=1,
                        raw_model="stand-in",
                    )
                )
        steps.append(
            ChatCompletionResult(
                content=observed.reply,
                tool_calls=[],
                tokens_in=1,
                tokens_out=1,
                raw_model="stand-in",
            )
        )
    queue = list(steps)

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        return queue.pop(0)

    monkeypatch.setattr(AIGateway, "chat", fake_chat)


async def test_the_pipe_runs_every_case_and_produces_a_verdict(db, tenant_ctx, monkeypatch) -> None:
    """Every case is executed and reaches the report. Verdict content is NOT asserted here:
    a stand-in cannot honestly stand in for the real data the tools return."""
    results = []
    for case in ALL:
        _competent_model(monkeypatch, case)
        result, records = await run_case(db, tenant_ctx.tenant_id, case)
        assert len(records) == len(case.turns), case.id
        results.append(result)

    verdict = summarise(ALL, results)
    assert sum(t for _, t in verdict.by_risk.values()) == len(ALL)
    assert render(verdict).startswith(("SHIP", "DO NOT SHIP"))


@pytest.mark.live_eval
async def test_live_model_against_the_golden_set(db, tenant_ctx) -> None:
    """THE measurement. Run with: pytest -m live_eval tests/test_agent_eval_suite.py -s"""
    # All three are needed. A key alone sends the request to model="openai" and fails at the
    # provider with a 400 nobody can attribute (see the note in app/core/config.py), after
    # money may already have been spent on retries. Refuse before the first call instead.
    missing = [
        name
        for name in ("AI_API_KEY_PRIMARY", "AI_MODEL_PRIMARY", "AI_BASE_URL_PRIMARY")
        if not os.environ.get(name)
    ]
    if missing:
        pytest.fail(f"live_eval requested but {', '.join(missing)} not set; refusing to fake it")

    results = []
    records_by_case = {}
    for case in ALL:
        result, records = await run_case(db, tenant_ctx.tenant_id, case)
        results.append(result)
        records_by_case[case.id] = records

    verdict = summarise(ALL, results)
    print("\n" + render(verdict))

    # Quality (natural, grounded, per-case rubric) is judged by a model, and only when asked:
    # it costs more calls and the judge alias is the user's choice (a stronger model than the
    # one answering customers is usually right). It is reported, and gates nothing by itself,
    # until a live run has shown the judge agrees with a human on real replies.
    judge_alias = os.environ.get("AGENT_EVAL_JUDGE_ALIAS")
    if judge_alias:
        await _report_quality(db, tenant_ctx.tenant_id, judge_alias, records_by_case)
    else:
        print("\n(quality judge skipped: set AGENT_EVAL_JUDGE_ALIAS to e.g. 'strong' to run it)")

    assert verdict.ship, "\n" + render(verdict)


async def _report_quality(db, tenant_id, alias: str, records_by_case) -> None:
    max_calls = int(os.environ.get("AGENT_EVAL_JUDGE_MAX_CALLS", "400"))
    gateway = AIGateway()

    async def chat(system: str, user: str) -> str:
        result = await gateway.chat(
            db,
            tenant_id,
            alias=alias,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
            max_tokens=200,
        )
        return result.content or ""

    limited, used = judge.capped(chat, max_calls)
    await judge.require_calibrated(limited)  # raises before a single real verdict is used

    failed: list[str] = []
    total = 0
    for case in ALL:
        for v in await judge.judge_case(limited, case, records_by_case[case.id]):
            total += 1
            if not v.passed:
                failed.append(f"  {case.id} {v.criterion}: {v.reason}")
    print(f"\nQUALITY (judge alias={alias}, {used()} calls): {total - len(failed)}/{total} ok")
    for line in failed:
        print(line)


async def test_the_judge_is_fed_what_the_agent_actually_read(db, tenant_ctx, monkeypatch) -> None:
    """Regression: the judge was once handed ``outcome.grounding``, which is a STATUS WORD
    ("ok" / "failed" / "skipped_no_facts"), not data. It would have judged every reply against
    the word "ok". This goes through the real runner and checks the text is the tool results."""
    case = next(c for c in ALL if c.id == "self-details-of-a-named-product")
    _competent_model(monkeypatch, case)
    _, records = await run_case(db, tenant_ctx.tenant_id, case)

    text = records[0].tool_text
    assert text not in ("", "ok", "failed", "skipped_no_facts"), text
    assert "[search_catalog]" in text
    # What the tool really returns: a price and a per-variant title (here the size, because the
    # fixture names variants by size) with availability as a WORD, not a stock count. The
    # product's own name is NOT guaranteed to be in it, so this must not demand one.
    assert '"price": "250.00"' in text
    assert '"title": "L"' in text
    # and the production status word is still available, unchanged, as its own field
    assert records[0].grounding in {"ok", "failed", "skipped_no_facts"}


async def test_a_turn_with_no_tool_calls_gives_the_judge_nothing_to_ground_against(
    db, tenant_ctx, monkeypatch
) -> None:
    case = next(c for c in ALL if c.id == "self-asks-for-the-invoice-instead-of-handing-over")
    _competent_model(monkeypatch, case)
    _, records = await run_case(db, tenant_ctx.tenant_id, case)
    assert records[0].tool_text == ""
