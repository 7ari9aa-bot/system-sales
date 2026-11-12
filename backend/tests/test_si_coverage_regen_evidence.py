"""The corrective regeneration must SHOW the model the evidence it is told to use.

``build_corrective_instruction`` says "rewrite from the evidence the tools gathered", and the
call passes ``tools=None`` with the comment "reuses the gathered evidence only". But the
messages sent held only the system prompt, the history, the first draft and the instruction.
The evidence was used for the gap check and never reached the model, so a model with nothing
to rewrite from answered "no tool results appeared", and that answer was accepted as the
correction. In a real run nine facts had been collected and the final answer said there were
none. Any ordinary model behaves this way; it is not a model quirk.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

from app.modules.ai.agents.sales_intelligence.coverage import regenerate_on_coverage_gap
from app.modules.ai.gateway import AIGateway, ChatCompletionResult


class _Session:
    def __init__(self, agent):
        self._agent = agent

    async def get(self, model, obj_id):
        return self._agent


def _agent():
    return SimpleNamespace(
        id=uuid.uuid4(),
        kind="sales_intelligence",
        model="fast",
        system_prompt="analyze",
        temperature=0.2,
        max_output_tokens=200,
    )


EVIDENCE = {
    "facts": [
        {"metric": "orders_placed", "value": "117", "window": "30d"},
        {"metric": "orders_placed", "value": "59", "window": "prior 30d"},
    ],
    "comparisons": [{"label": "orders_placed: last 30d vs prior 30d", "delta": "58"}],
    "drivers": [],
}


async def _run(monkeypatch, evidence=EVIDENCE):
    agent = _agent()
    seen: list[list[dict]] = []

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        seen.append(messages)
        return ChatCompletionResult(
            content="المبيعات: عدد الطلبات 117 مقابل 59",
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    await regenerate_on_coverage_gap(
        _Session(agent),
        uuid.uuid4(),
        agent_id=agent.id,
        run_id=None,
        question="كام مبيعات وليه اتغيرت؟",
        history=None,
        draft="سأعيد المحاولة بالاسم الصحيح.",
        evidence=evidence,
        allowed_numbers={"117", "59", "58"},
        findings=[],
        tool_calls_made=[],
    )
    return seen


async def test_the_regeneration_messages_carry_the_gathered_evidence(monkeypatch):
    seen = await _run(monkeypatch)

    assert len(seen) == 1
    everything = json.dumps(seen[0], ensure_ascii=False)
    for number in ("117", "59", "58"):
        assert number in everything, f"{number} from the tools never reached the model"
    assert "orders_placed" in everything


async def test_the_evidence_comes_before_the_instruction_that_refers_to_it(monkeypatch):
    seen = await _run(monkeypatch)
    last = seen[0][-1]

    assert last["role"] == "user"  # the correction stays the last turn
    text = last["content"]
    assert "117" in text
    assert text.index("117") < text.index("أعد صياغة"), "evidence must precede the instruction"


async def test_a_wide_analysis_is_capped_and_never_cut_mid_number(monkeypatch):
    from app.modules.ai.agents.sales_intelligence.coverage import build_evidence_message

    wide = {
        "facts": [{"metric": f"m{i}", "value": f"{i}.55", "pad": "x" * 200} for i in range(400)]
    }
    text = build_evidence_message(wide)

    assert len(text) < 8000
    assert "مقطوعة" in text
    for line in text.splitlines()[1:-1]:
        assert line.endswith("}"), f"cut mid-item: {line[-30:]}"


async def test_no_evidence_adds_no_block(monkeypatch):
    from app.modules.ai.agents.sales_intelligence.coverage import build_evidence_message

    assert build_evidence_message({}) == ""
    assert build_evidence_message({"facts": []}) == ""
