"""A month named with its year, "September 2026", is legal only when that month holds measured data.

Found by asking the live assistant "which month was best?": it answered "September 2026" and the
number gate refused the 2026 as a free number, so the owner got "no clear result". Naming a month is
the natural way to answer that question, so the gate now accepts it, but only for a month and year
that hold a measured period boundary or a day the shop recorded. A month with no data, another year,
or a bare year stays refused, so the digits of a year can never be used to smuggle a figure in.
"""

from __future__ import annotations

import pytest

from app.applications.apparel.modules.ai.agents.sales_intelligence.response import validate_answer

ALLOWED = {"1112.98", "3"}
RECORDED = {(2026, 9, 17)}
PERIOD = {(2026, 8, 17), (2026, 11, 15)}


def _problems(text: str, *, period=PERIOD, recorded=RECORDED) -> list[str]:
    return validate_answer(text, ALLOWED, [], period_dates=period, recorded_dates=recorded)


@pytest.mark.parametrize(
    "text",
    [
        "أحسن شهر كان سبتمبر 2026",
        "أحسن شهر كان شهر سبتمبر 2026 بإجمالي 1112.98",
        "كان أحسن في September 2026",
        "من أغسطس 2026 لحد نوفمبر 2026",
        "سبتمبر 2026، وبعده نوفمبر 2026",
    ],
)
def test_a_month_and_year_that_hold_measured_data_is_accepted(text):
    assert _problems(text) == []


@pytest.mark.parametrize(
    ("text", "left"),
    [
        ("أحسن شهر كان ديسمبر 2026", "2026"),
        ("أحسن شهر كان أكتوبر 2026", "2026"),
        ("أحسن شهر كان سبتمبر 2025", "2025"),
        ("أحسن شهر كان سبتمبر 1999", "1999"),
        ("في 2026 كله", "2026"),
        ("سنة 2026 فيها 3 أوردرات", "2026"),
        ("سبتمبر 20266", "20266"),
        ("سبتمبر 2026 و2027", "2027"),
    ],
)
def test_a_month_without_data_another_year_or_a_bare_year_stays_refused(text, left):
    assert _problems(text) == [f"free number in answer: {left}"]


def test_a_day_glued_to_the_month_is_not_a_month():
    assert _problems("1سبتمبر 2026") != []


def test_a_month_name_never_unlocks_the_digits_beside_it():
    assert _problems("سبتمبر 2026 فيه 77 أوردر") == ["free number in answer: 77"]


def test_a_month_holding_only_a_recorded_day_is_accepted_with_no_period_at_all():
    """The early exit when there is no period used to skip this, so a shop whose only data is old
    could never name its own month."""
    assert _problems("أحسن شهر كان سبتمبر 2026", period=set()) == []
    assert _problems("ديسمبر 2026", period=set()) != []


def test_a_whole_recorded_date_is_unchanged_by_the_month_rule():
    """The month rule runs last, so "17 September 2026" is judged exactly as before it existed:
    the day is a measured one (the data-status tool's last order), so nothing is left over."""
    day = {(2026, 9, 17)}
    text = "آخر أوردر 17 سبتمبر 2026"
    assert validate_answer(text, ALLOWED, [], period_dates=day, yearless_dates=day) == []


@pytest.mark.parametrize("text", ["وسبتمبر 2026", "في سبتمبر 2026", "بسبتمبر 2026", "لسبتمبر 2026"])
def test_one_arabic_prefix_letter_on_the_month_is_ordinary_writing(text):
    assert _problems(text) == []


@pytest.mark.parametrize(
    "text", ["5سبتمبر 2026", "9سبتمبر 2026", "xسبتمبر 2026", "Xseptember 2026"]
)
def test_a_digit_or_latin_letter_glued_to_the_month_is_never_a_prefix(text):
    """A digit stuck to the month name would hide a number inside the 'month'."""
    assert "free number in answer: 2026" in _problems(text)
