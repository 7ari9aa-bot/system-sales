"""The server reads the days the shop recorded, so naming the last order never depends on the model.

Found on the live assistant: the model said "the last order was 17 September" in most answers, from
the conversation or from an earlier tool call, and in a turn that did not call the data-status tool
the gate refused the date as unmeasured. The owner got a generic text instead of a correct answer.

The server now reads the same read-only data-status query itself and gives the gate DATES ONLY. No
count travels with it, so no number becomes legal, and no reply text is prepared anywhere.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence import agent as si_agent
from app.modules.ai.agents.sales_intelligence import tools as si_tools
from app.modules.ai.agents.sales_intelligence.response import (
    allowed_numbers_from_facts,
    period_dates_from_evidence,
    recorded_days_from_evidence,
    validate_answer,
)

FACTS = [
    {
        "id": "f1",
        "metric": "delivered_revenue",
        "value": "0",
        "window": "14d",
        "period_start": "2026-11-01T00:00:00+00:00",
        "period_end": "2026-11-15T00:00:00+00:00",
    }
]
DAYS = ["2026-09-10", "2026-09-17"]


def _check(text, *, days=DAYS, summaries=None):
    ev = {"facts": FACTS, "summaries": summaries or []}
    if days is not None:
        ev["recorded_days"] = days
    return validate_answer(
        text,
        allowed_numbers_from_facts(ev, []),
        [],
        period_dates=period_dates_from_evidence(ev),
        yearless_dates=period_dates_from_evidence(ev, boundaries_only=True),
        recorded_dates=recorded_days_from_evidence(ev),
    )


@pytest.mark.parametrize(
    "text",
    [
        "آخر أوردر كان 17 سبتمبر 2026.",
        "آخر أوردر كان 2026-09-17.",
        "آخر أوردر 17/9/2026.",
        "آخر أوردر 17-09-2026.",
        "آخر أوردر 17 / 9 / 2026.",
        "أول أوردر 10 سبتمبر 2026 وآخر واحد 17 سبتمبر 2026.",
        "The last order was on 17 September 2026.",
    ],
)
def test_a_day_the_shop_recorded_may_be_named_without_the_model_asking(text):
    assert _check(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "آخر أوردر كان 18 سبتمبر 2026.",
        "آخر أوردر 17/9/2025.",
        "آخر أوردر 18/9/2026.",
        "آخر أوردر 17/10/2026.",
        "آخر أوردر 16-09-2026.",
        "آخر أوردر 17-08-2026.",
        "آخر أوردر 9/17/2026.",
        "آخر أوردر 117/9/2026.",
        "آخر أوردر 17/9/20267.",
    ],
)
def test_a_day_that_was_not_recorded_or_is_written_loosely_is_refused(text):
    assert _check(text) != []


def test_without_the_days_the_same_answer_is_refused():
    assert _check("آخر أوردر كان 17 سبتمبر 2026.", days=None) != []
    assert _check("آخر أوردر كان 17 سبتمبر 2026.", days=[]) != []


def test_a_recorded_day_makes_no_number_legal():
    # the digits of the day, the count of orders, and the year stay refused on their own
    for text in [
        "فيه 17 أوردر.",
        "فيه 2026 أوردر.",
        "فيه 3 أوردرات.",
        "آخر أوردر 17 سبتمبر 2026 وفيه 9.",
    ]:
        assert _check(text) != [], text
    with_days = allowed_numbers_from_facts({"facts": FACTS, "recorded_days": DAYS}, [])
    without = allowed_numbers_from_facts({"facts": FACTS}, [])
    assert with_days == without


def test_a_recorded_day_is_not_a_period_boundary():
    # it never joins the year-less PERIOD set, which is what builds the "from 1 to 14" ranges
    days = period_dates_from_evidence({"facts": FACTS, "recorded_days": DAYS}, boundaries_only=True)
    assert (2026, 9, 17) not in days
    assert (2026, 9, 17) in recorded_days_from_evidence({"recorded_days": DAYS})


class _Session:
    """Stands for the database: the data-status query reads through it, never the test."""


async def test_the_server_hands_the_gate_only_the_first_and_last_days(monkeypatch):
    async def fake(session, tenant_id, *, context=None):
        return {
            "summary": {
                "sources": [
                    {
                        "source": "orders",
                        "recorded": True,
                        "count": 3,
                        "first": "2026-09-10",
                        "last": "2026-09-17",
                    },
                    {
                        "source": "expenses",
                        "recorded": False,
                        "count": 0,
                        "first": None,
                        "last": None,
                    },
                    {
                        "source": "customers",
                        "recorded": True,
                        "count": 3,
                        "first": "2026-09-17",
                        "last": "2026-09-17",
                    },
                ]
            }
        }

    monkeypatch.setattr(si_tools, "_si_data_status", fake)
    days = await si_agent._recorded_days(_Session(), "t1")
    assert days == ["2026-09-10", "2026-09-17"]
    assert not any(ch.isalpha() for d in days for ch in d)


async def test_a_failed_read_returns_nothing_and_never_breaks_the_answer(monkeypatch):
    async def boom(session, tenant_id, *, context=None):
        raise RuntimeError("database went away")

    monkeypatch.setattr(si_tools, "_si_data_status", boom)
    assert await si_agent._recorded_days(_Session(), "t1") == []


async def test_a_shop_with_nothing_recorded_gives_no_days(monkeypatch):
    async def empty(session, tenant_id, *, context=None):
        return {
            "summary": {
                "sources": [
                    {"source": "orders", "recorded": False, "count": 0, "first": None, "last": None}
                ]
            }
        }

    monkeypatch.setattr(si_tools, "_si_data_status", empty)
    assert await si_agent._recorded_days(_Session(), "t1") == []


def test_the_run_reads_the_days_once_and_only_after_the_model_finished():
    # read the file itself: other tests replace the imported function, and a source read through
    # the live object would then see their stand-in instead of the real run
    import pathlib

    text = pathlib.Path(si_agent.__file__).read_text(encoding="utf-8")
    body = text[text.index("async def run_sales_analysis(") :]
    assert body.count("_recorded_days(") == 1
    assert body.index("runner.run(") < body.index("_recorded_days(") < body.index("build_findings(")


# --- the way an owner really says it: "the last order was on 17 September", no year -------------
# Found live: the model wrote the day without its year in most answers and the gate refused it,
# because the year-less form was allowed for period boundaries only. A day the shop really
# recorded is just as measured, so it may be written that way, but never as the end of a range.
@pytest.mark.parametrize(
    "text",
    [
        "آخر أوردر مسجّل تاريخه 17 سبتمبر، وبعده مفيش حاجة.",
        "أول أوردر 10 سبتمبر وآخر واحد 17 سبتمبر.",
        "آخر أوردر 17/9.",
        "آخر أوردر 17-09.",
        "The last order was on 17 September.",
    ],
)
def test_a_recorded_day_may_be_written_without_its_year(text):
    assert _check(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "آخر أوردر 18 سبتمبر.",
        "آخر أوردر 17 أكتوبر.",
        "آخر أوردر 17 سبتمبر 2025.",
        "آخر أوردر 17 سبتمبر 5 مرات.",
        "آخر أوردر 117 سبتمبر.",
        "آخر أوردر 17/9/25.",
        "آخر أوردر 9/17.",
        "آخر أوردر 17 سبتمبر و3 أوردرات.",
        "آخر أوردر 17 سبتمبر،2026.",
    ],
)
def test_a_year_less_day_that_is_not_recorded_or_has_anything_numeric_next_to_it_is_refused(text):
    assert _check(text) != []


def test_a_recorded_day_never_ends_a_range():
    # 10 and 17 September are both recorded, but they are not the two ends of a measured period
    assert _check("من 10 لـ 17 سبتمبر كان فيه أوردرات.") != []
    assert _check("من 10 سبتمبر لحد 17 سبتمبر كان فيه أوردرات.") == []


def test_the_year_less_form_without_recorded_days_is_still_refused():
    assert _check("آخر أوردر 17 سبتمبر.", days=None) != []
    assert _check("آخر أوردر 17 سبتمبر.", days=[]) != []


def test_recorded_days_are_read_only_from_their_own_key():
    ev = {"facts": FACTS, "summaries": [{"recorded_days": ["2026-09-17"]}], "other": "2026-09-17"}
    assert recorded_days_from_evidence(ev) == set()
    assert recorded_days_from_evidence({"recorded_days": ["2026-09-17", None, 5, "x"]}) == {
        (2026, 9, 17)
    }


# --- the wiring: the tests above call the gate directly, the live path is two call sites ---
# Dropping the argument at either of them left every test green while the real assistant refused
# the same answers again, so the call sites themselves are checked.
def _validate_calls(module):
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", "")) == "validate_answer"
    ]


@pytest.mark.parametrize(
    "module_name", ["agent", "coverage"], ids=["the answer gate", "the regenerated-answer gate"]
)
def test_every_real_gate_call_hands_over_the_recorded_days(module_name):
    import importlib

    module = importlib.import_module(f"app.modules.ai.agents.sales_intelligence.{module_name}")
    calls = _validate_calls(module)
    assert calls, "this module no longer validates an answer: update this test"
    for call in calls:
        keywords = {kw.arg: kw.value for kw in call.keywords}
        assert "recorded_dates" in keywords, "the real gate would refuse a recorded day again"
        text = ast_unparse(keywords["recorded_dates"])
        assert "recorded_days_from_evidence(evidence)" in text


def ast_unparse(node):
    import ast

    return ast.unparse(node)
