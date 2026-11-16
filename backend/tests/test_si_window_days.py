"""The window length a fact reports is the owner's calendar-day count, so the model can say it.

The cashier tool runs up to now, so its window ends part-way through today. Counting only whole
24-hour spans reported 29 for "the last 30 days"; the model said 30 (correct) and the number gate
refused a good answer and swapped in the canned "no clear result" text."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.ai.agents.sales_intelligence.response import validate_answer
from app.modules.ai.agents.sales_intelligence.tools import _window_days

D = lambda *a: datetime(*a, tzinfo=UTC)  # noqa: E731


def test_a_midnight_to_midnight_window_is_its_whole_days():
    assert _window_days(D(2026, 10, 17), D(2026, 11, 16)) == 30
    assert _window_days(D(2026, 11, 1), D(2026, 11, 15)) == 14


def test_a_window_ending_part_way_through_today_counts_today():
    assert _window_days(D(2026, 10, 18), D(2026, 11, 16, 2, 19)) == 30
    assert _window_days(D(2026, 10, 18), D(2026, 11, 16, 0, 0, 1)) == 30


def test_one_minute_into_today_is_one_day_not_zero():
    assert _window_days(D(2026, 11, 16), D(2026, 11, 16, 0, 1)) == 1


def test_an_empty_or_backwards_window_is_zero():
    assert _window_days(D(2026, 11, 16), D(2026, 11, 16)) == 0
    assert _window_days(D(2026, 11, 16), D(2026, 11, 10)) == 0


def test_the_real_cashier_answer_now_passes_the_gate():
    """The production answer: 'آخر 30 يوم' over 18 Oct to 16 Nov. Its window is now 30d, so 30 is a
    measured number and the answer is kept rather than replaced."""
    text = "الفترة: من 2026-10-18 لحد 2026-11-16 (آخر 30 يوم): فواتير الكاشير: صفر."
    days = _window_days(D(2026, 10, 18), D(2026, 11, 16, 2, 19))
    allowed = {"0", str(days)}
    dates = {(2026, 10, 18), (2026, 11, 16)}
    assert validate_answer(text, allowed, [], period_dates=dates) == []


def test_a_wrong_day_count_is_still_refused():
    text = "الفترة: من 2026-10-18 لحد 2026-11-16 (آخر 45 يوم): فواتير الكاشير: صفر."
    allowed = {"0", "30"}
    dates = {(2026, 10, 18), (2026, 11, 16)}
    assert validate_answer(text, allowed, [], period_dates=dates) == ["free number in answer: 45"]


def test_the_fact_the_model_reads_carries_the_calendar_day_count():
    """The wiring, not just the helper: the `window` the model is handed for a till fact (a window
    ending part-way through today) is 30d, so it can say 'the last 30 days' and pass the gate."""
    from types import SimpleNamespace

    from app.modules.ai.agents.sales_intelligence.tools import _fact_payload

    fact = SimpleNamespace(
        id="F1",
        metric="pos_sales_total",
        value="0",
        unit="money",
        filters={},
        period=SimpleNamespace(start=D(2026, 10, 18), end=D(2026, 11, 16, 2, 19), timezone="UTC"),
        maturity_status=SimpleNamespace(value="mature"),
    )
    assert _fact_payload(fact)["window"] == "30d"
