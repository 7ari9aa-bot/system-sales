"""An answer may name the dates of the periods the tools measured, and only those.

The number gate rejects every digit run no tool produced, and period boundaries are excluded
from the allowed numbers on purpose: letting a timestamp's digits in is how a made-up "16%"
would pass. The side effect was that "from 13 October 2026" is a free number three times over
(13, 2026 and the month's digits in an ISO date), so any analysis that names its own period
fell back to the safe response. In a real run the model's corrected answer carried nine
genuine figures and was refused for its dates alone.

The fix recognises a whole date only when it equals a period boundary found in the evidence.
Every other digit, a made-up date included, stays subject to the gate.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence.response import (
    allowed_numbers_from_facts,
    period_dates_from_evidence,
    validate_answer,
)

FACTS = [
    {
        "id": "f1",
        "metric": "orders_placed",
        "value": "117",
        "window": "30d",
        "period_start": "2026-10-13T00:00:00+00:00",
        "period_end": "2026-11-12T00:00:00+00:00",
    },
    {
        "id": "f2",
        "metric": "orders_placed",
        "value": "59",
        "window": "prior",
        "period_start": "2026-09-13T00:00:00+00:00",
        "period_end": "2026-10-13T00:00:00+00:00",
    },
]


def _check(text: str) -> list[str]:
    allowed = allowed_numbers_from_facts(FACTS, [])
    dates = period_dates_from_evidence({"facts": FACTS})
    return validate_answer(text, allowed, [], period_dates=dates)


@pytest.mark.parametrize(
    "text",
    [
        "من 13 أكتوبر 2026 إلى 12 نوفمبر 2026 بلغ عدد الطلبات 117 مقابل 59.",
        "من 2026-10-13 إلى 2026-11-12 بلغ عدد الطلبات 117.",
        "الفترة السابقة بدأت 13 سبتمبر 2026 وبلغت 59 طلب.",
        "From 13 October 2026 to 12 November 2026 there were 117 orders.",
        "من ١٣ أكتوبر ٢٠٢٦ بلغ ١١٧ طلب.",
    ],
)
def test_a_real_period_date_is_not_a_free_number(text):
    assert _check(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "زادت الطلبات 16% عن الفترة السابقة (117 مقابل 59).",
        "من 5 مارس 2026 بلغ عدد الطلبات 117.",  # a date no tool measured
        "من 14 أكتوبر 2026 بلغ عدد الطلبات 117.",  # one day off a real boundary
        "بلغ عدد الطلبات 13 في الفترة.",  # 13 is a count here, not the day
        "في سنة 2026 بلغ عدد الطلبات 117.",  # a bare year is not a boundary
    ],
)
def test_anything_else_is_still_refused(text):
    assert _check(text) != []


def test_a_date_does_not_unlock_the_numbers_inside_it():
    # "13" is only legal as part of the whole date "13 October 2026".
    problems = _check("بلغ عدد الطلبات 117 في 13 أكتوبر 2026 وزاد 13 عن أمس.")
    assert any("13" in p for p in problems)


def test_without_dates_the_gate_behaves_exactly_as_before():
    allowed = allowed_numbers_from_facts(FACTS, [])
    assert validate_answer("من 13 أكتوبر 2026 بلغ 117.", allowed, []) != []


def test_dates_come_only_from_period_fields_of_the_evidence():
    dates = period_dates_from_evidence(
        {"facts": FACTS, "comparisons": [{"period_start": "2026-08-01T00:00:00+00:00"}]}
    )
    assert (2026, 10, 13) in dates and (2026, 11, 12) in dates and (2026, 8, 1) in dates
    assert (2026, 3, 5) not in dates
    assert period_dates_from_evidence({}) == set()
    assert period_dates_from_evidence({"facts": [{"period_start": "not a date"}]}) == set()


async def test_the_corrective_regeneration_accepts_an_answer_naming_its_period(monkeypatch):
    # The real failure: the regenerated answer was refused for its dates alone and the user
    # got the model's one-line first draft instead.
    import uuid
    from types import SimpleNamespace

    from app.modules.ai.agents.sales_intelligence.coverage import regenerate_on_coverage_gap
    from app.modules.ai.gateway import AIGateway, ChatCompletionResult

    agent = SimpleNamespace(
        id=uuid.uuid4(),
        kind="sales_intelligence",
        model="fast",
        system_prompt="analyze",
        temperature=0.2,
        max_output_tokens=200,
    )

    class _Session:
        async def get(self, model, obj_id):
            return agent

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        return ChatCompletionResult(
            content="المبيعات: من 13 أكتوبر 2026 إلى 12 نوفمبر 2026 بلغ عدد الطلبات 117 مقابل 59",
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    replacement, note, _ = await regenerate_on_coverage_gap(
        _Session(),
        uuid.uuid4(),
        agent_id=agent.id,
        run_id=None,
        question="كام مبيعات؟",
        history=None,
        draft="سأعيد المحاولة.",
        evidence={"facts": FACTS},
        allowed_numbers=allowed_numbers_from_facts(FACTS, []),
        findings=[],
        tool_calls_made=[],
    )

    assert note["succeeded"] is True
    assert replacement and "117" in replacement


def test_an_iso_date_that_is_not_a_boundary_is_still_refused():
    assert _check("من 2026-03-05 إلى 2026-04-05 بلغ عدد الطلبات 117.") != []
    assert _check("من 2026-10-14 بلغ عدد الطلبات 117.") != []


def test_a_timestamp_elsewhere_in_the_evidence_does_not_become_a_legal_date():
    # computed_at, created_at and the like are provenance, not measured periods.
    facts = [{**FACTS[0], "computed_at": "2026-11-12T09:00:00+00:00", "note": "2026-07-04"}]
    dates = period_dates_from_evidence({"facts": facts})
    assert (2026, 7, 4) not in dates
    assert (2026, 11, 12) in dates  # it is also a real period_end
    allowed = allowed_numbers_from_facts(facts, [])
    assert validate_answer("بتاريخ 2026-07-04 بلغ 117.", allowed, [], period_dates=dates) != []


def test_the_day_and_the_month_must_both_match():
    # 13 September is a real boundary of the prior period; 13 November is not.
    assert _check("من 13 سبتمبر 2026 بلغ 59.") == []
    assert _check("من 13 نوفمبر 2026 بلغ 59.") != []
    assert _check("من 12 أكتوبر 2026 بلغ 59.") != []
