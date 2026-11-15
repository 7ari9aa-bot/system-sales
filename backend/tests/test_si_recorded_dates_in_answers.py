"""An answer may name when a source was first and last recorded, and a period without its year.

Found by asking the live assistant. The tools were right and the model's words were right, and the
number gate refused them anyway, so the owner got the generic "no clear result" text:

* "the last order on the system was 17 September 2026" (the data-status tool reports it under
  ``first``/``last``, which the gate did not treat as measured dates)
* "from 1 November to 14 November" (a period boundary written the way people talk, without the year)

Only a real date is let through, as a whole. The digits inside it stay forbidden elsewhere.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence.response import (
    allowed_numbers_from_facts,
    period_dates_from_evidence,
    validate_answer,
)

PERIOD = [
    {
        "id": "f1",
        "metric": "collected_revenue",
        "value": "0",
        "window": "14d",
        "period_start": "2026-11-01T00:00:00+02:00",
        "period_end": "2026-11-14T23:59:59+02:00",
    }
]
STATUS = {
    "sources": [
        {
            "source": "orders",
            "recorded": True,
            "count": 3,
            "first": "2026-09-10",
            "last": "2026-09-17",
        },
        {"source": "expenses", "recorded": False, "count": 0, "first": None, "last": None},
    ]
}


def _ev(summaries=None, facts=None):
    return {"facts": facts if facts is not None else PERIOD, "summaries": summaries or []}


def _check(text, **kw):
    ev = _ev(**kw)
    allowed = allowed_numbers_from_facts(ev["facts"], [])
    return validate_answer(
        text,
        allowed,
        [],
        period_dates=period_dates_from_evidence(ev),
        yearless_dates=period_dates_from_evidence(ev, boundaries_only=True),
    )


@pytest.mark.parametrize(
    "text",
    [
        "آخر أوردر متسجل كان يوم 17 سبتمبر 2026.",
        "أول أوردر كان 10 سبتمبر 2026 وآخر واحد 17 سبتمبر 2026.",
        "The last order was on 17 September 2026.",
        "آخر أوردر كان يوم 2026-09-17.",
        "آخر أوردر كان ١٧ سبتمبر ٢٠٢٦.",
    ],
)
def test_the_first_and_last_day_a_source_was_recorded_may_be_named(text):
    assert _check(text, summaries=[STATUS]) == []


@pytest.mark.parametrize(
    "text",
    [
        "الفترة من 1 نوفمبر لحد 14 نوفمبر، المبيعات 0.",
        "من 1 نوفمبر إلى 14 نوفمبر 2026 المبيعات 0.",
        "From 1 November to 14 November the sales were 0.",
        "المبيعات 0 من 1 نوفمبر لحد 14 نوفمبر.",
    ],
)
def test_a_measured_boundary_may_be_written_without_the_year(text):
    assert _check(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "آخر أوردر كان يوم 18 سبتمبر 2026.",  # not a recorded day
        "آخر أوردر كان يوم 17 سبتمبر.",  # recorded day without a year is NOT accepted for these
        "من 2 نوفمبر لحد 14 نوفمبر، المبيعات 0.",  # 2 is not a boundary
        "من 1 نوفمبر لحد 15 نوفمبر، المبيعات 0.",  # 15 is not a boundary
        "المبيعات 0 وزادت 17 في المية.",  # a free number stays free
        "من 1 نوفمبر لحد 14 نوفمبر، المبيعات 0 وعدد العملاء 23.",  # a free count beside real dates
    ],
)
def test_anything_else_is_still_refused(text):
    assert _check(text, summaries=[STATUS]) != []


def test_a_recorded_date_does_not_unlock_its_digits_elsewhere():
    assert _check("آخر أوردر 17 سبتمبر 2026 وعندك 17 عميل.", summaries=[STATUS]) != []
    assert _check("آخر أوردر 17 سبتمبر 2026 وعندك 2026 عميل.", summaries=[STATUS]) != []


def test_a_first_or_last_key_outside_the_data_status_summary_is_not_a_date():
    other = [{"first": "2026-08-08", "last": "2026-08-09", "value": "1"}]
    assert _check("كان ذلك يوم 8 أغسطس 2026.", summaries=other) != []


def test_a_missing_or_null_recorded_day_adds_nothing():
    empty = {
        "sources": [
            {"source": "expenses", "recorded": False, "count": 0, "first": None, "last": None}
        ]
    }
    assert _check("آخر مصروف كان يوم 17 سبتمبر 2026.", summaries=[empty]) != []


def test_the_year_less_form_needs_the_boundary_to_be_measured():
    assert _check("من 1 نوفمبر لحد 14 نوفمبر، المبيعات 0.", facts=[]) != []


def test_a_row_without_a_source_name_is_not_a_recorded_day():
    anon = {
        "sources": [{"recorded": True, "count": 1, "first": "2026-09-10", "last": "2026-09-17"}]
    }
    assert _check("آخر أوردر كان يوم 17 سبتمبر 2026.", summaries=[anon]) != []


def test_a_summary_that_is_itself_a_row_is_not_a_recorded_day():
    flat = {"source": "orders", "first": "2026-09-10", "last": "2026-09-17"}
    assert _check("آخر أوردر كان يوم 17 سبتمبر 2026.", summaries=[flat]) != []


@pytest.mark.parametrize(
    "text",
    [
        "من 1 نوفمبر 2025 لحد 14 نوفمبر 2025، المبيعات 0.",  # another year: not this period
        "من 11 نوفمبر لحد 14 نوفمبر، المبيعات 0.",  # 11 only ends in the digit 1
        "من 21 نوفمبر لحد 14 نوفمبر، المبيعات 0.",
        "المبيعات 0 يوم 1 novemberx.",  # a longer word is not the month
        "المبيعات 0 يوم 1 نوفمبرات.",
    ],
)
def test_the_year_less_form_matches_a_whole_day_and_month_with_no_other_year(text):
    assert _check(text) != []
