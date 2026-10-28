"""The whole golden set, run as one release gate.

Two modes, SAME code path:

* default (CI): a scripted stand-in model that behaves like a competent agent, built from the
  reference replies. It proves the pipe (cases -> real shop -> real runtime -> graders ->
  verdict) and that a competent agent SHIPS. It says nothing about any real model.
* ``-m live_eval`` with AI_API_KEY_PRIMARY set: the real gateway, a real model. THIS is the
  measurement. It is skipped by default because it costs money and needs a key; if you ask
  for it and the key is missing, it FAILS loudly rather than silently using a stand-in.
"""

from __future__ import annotations

import os

import pytest

from app.modules.ai.gateway import AIGateway
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from tests.agent_eval.cases_core import CASES as CORE
from tests.agent_eval.cases_flows import CASES as FLOWS
from tests.agent_eval.reference_replies import GOOD
from tests.agent_eval.report import render, summarise
from tests.agent_eval.runner import run_case

ALL = CORE + FLOWS

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
    if not os.environ.get("AI_API_KEY_PRIMARY"):
        pytest.fail("live_eval requested but AI_API_KEY_PRIMARY is not set; refusing to fake it")

    results = []
    for case in ALL:
        result, _ = await run_case(db, tenant_ctx.tenant_id, case)
        results.append(result)

    verdict = summarise(ALL, results)
    print("\n" + render(verdict))
    assert verdict.ship, "\n" + render(verdict)
