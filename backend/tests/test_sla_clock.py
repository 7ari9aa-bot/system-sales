"""Spec §46 - the SLA clock is business-hours, holiday and timezone aware.

An SLA deadline computed as `created_at + N minutes` on the wall clock marks a
merchant as breaching at 02:00 while they are closed. These tests pin the
behaviour that makes the number mean something: the clock PAUSES at close and
RESUMES at the next opening.

Pure logic, so this runs without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.core.errors import ValidationError
from app.modules.operations.sla import BusinessClock, validate_calendar


@dataclass
class FakeCalendar:
    timezone: str = "UTC"
    hours: dict = field(default_factory=dict)
    holidays: list = field(default_factory=list)


WEEKDAYS_9_TO_5 = {str(d): [["09:00", "17:00"]] for d in range(5)}  # Mon-Fri
WEEKDAYS_9_TO_5["5"] = []
WEEKDAYS_9_TO_5["6"] = []


def _clock(**kwargs) -> BusinessClock:
    return BusinessClock(FakeCalendar(**kwargs))


def _dt(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


# --- a calendar with no configuration must not block anyone ---------------


def test_absent_hours_means_24_7() -> None:
    clock = _clock()
    assert clock.is_open(_dt(2026, 9, 20, 3, 0)) is True
    start = _dt(2026, 9, 20, 3, 0)
    assert clock.add_business_minutes(start, 90) == start.replace(hour=4, minute=30)


def test_a_sunday_is_open_when_no_calendar_is_configured() -> None:
    # 2026-09-20 is a Sunday.
    assert _clock().is_open(_dt(2026, 9, 20, 12, 0)) is True


# --- business hours --------------------------------------------------------


def test_closed_before_opening_and_after_closing() -> None:
    clock = _clock(hours=WEEKDAYS_9_TO_5)
    # 2026-09-21 is a Monday.
    assert clock.is_open(_dt(2026, 9, 21, 8, 59)) is False
    assert clock.is_open(_dt(2026, 9, 21, 9, 0)) is True
    assert clock.is_open(_dt(2026, 9, 21, 16, 59)) is True
    assert clock.is_open(_dt(2026, 9, 21, 17, 1)) is False


def test_minutes_inside_the_window_are_simple() -> None:
    clock = _clock(hours=WEEKDAYS_9_TO_5)
    start = _dt(2026, 9, 21, 10, 0)
    assert clock.add_business_minutes(start, 60) == start.replace(hour=11)


def test_the_clock_pauses_at_close_and_resumes_next_opening() -> None:
    """The core behaviour: 2h from 16:00 Monday is 10:00 TUESDAY, not 18:00."""
    clock = _clock(hours=WEEKDAYS_9_TO_5)
    deadline = clock.add_business_minutes(_dt(2026, 9, 21, 16, 0), 120)
    assert deadline == _dt(2026, 9, 22, 10, 0)


def test_closed_days_are_skipped_entirely() -> None:
    """Friday 16:30 + 60 min lands Monday 09:30, not Saturday."""
    clock = _clock(hours=WEEKDAYS_9_TO_5)
    # 2026-09-25 is a Friday.
    deadline = clock.add_business_minutes(_dt(2026, 9, 25, 16, 30), 60)
    assert deadline == _dt(2026, 9, 28, 9, 30)  # Monday


def test_a_start_outside_hours_rolls_to_the_next_opening_first() -> None:
    clock = _clock(hours=WEEKDAYS_9_TO_5)
    # Sunday 22:00 + 30 min -> Monday 09:30.
    deadline = clock.add_business_minutes(_dt(2026, 9, 20, 22, 0), 30)
    assert deadline == _dt(2026, 9, 21, 9, 30)


# --- holidays --------------------------------------------------------------


def test_a_holiday_is_skipped() -> None:
    clock = _clock(hours=WEEKDAYS_9_TO_5, holidays=["2026-09-21"])  # Monday
    assert clock.is_open(_dt(2026, 9, 21, 10, 0)) is False
    deadline = clock.add_business_minutes(_dt(2026, 9, 21, 9, 0), 60)
    assert deadline == _dt(2026, 9, 22, 10, 0)


def test_a_configured_holiday_closes_even_a_24_7_calendar() -> None:
    """Listing a holiday is an explicit statement that the business is shut
    that day, so it must win over the 24/7 default."""
    clock = _clock(holidays=["2026-09-21"])
    assert clock.is_open(_dt(2026, 9, 21, 10, 0)) is False
    # 30 minutes from the holiday itself lands at the next day's opening.
    assert clock.add_business_minutes(_dt(2026, 9, 21, 10, 0), 30) == _dt(2026, 9, 22, 0, 30)


def test_the_window_is_half_open_at_closing_time() -> None:
    """Regression: with a closed interval, an instant exactly on the closing
    time read as "open with zero minutes left", the walk made no progress and
    spun until its guard tripped, silently degrading to wall-clock time."""
    clock = _clock(hours=WEEKDAYS_9_TO_5)
    assert clock.is_open(_dt(2026, 9, 21, 17, 0)) is False
    # 30 min from exactly 17:00 Monday -> Tuesday 09:30, not Monday 17:30.
    assert clock.add_business_minutes(_dt(2026, 9, 21, 17, 0), 30) == _dt(2026, 9, 22, 9, 30)


# --- timezones -------------------------------------------------------------


def test_an_instant_is_evaluated_on_the_calendars_wall_clock() -> None:
    """09:00 in Cairo is 06:00 UTC — the calendar must judge the LOCAL time."""
    clock = _clock(timezone="Africa/Cairo", hours=WEEKDAYS_9_TO_5)
    # 06:00 UTC = 09:00 Cairo on a Monday -> open.
    assert clock.is_open(_dt(2026, 9, 21, 6, 0)) is True
    # 06:00 UTC is still closed for a UTC calendar.
    assert _clock(hours=WEEKDAYS_9_TO_5).is_open(_dt(2026, 9, 21, 6, 0)) is False


def test_an_unknown_timezone_degrades_to_utc_instead_of_crashing() -> None:
    clock = _clock(timezone="Mars/Olympus_Mons")
    assert clock.is_open(_dt(2026, 9, 21, 12, 0)) is True


# --- misconfiguration must not hang a worker ------------------------------


def test_a_calendar_that_never_opens_degrades_to_wall_clock() -> None:
    """A closed-every-day calendar must not spin forever."""
    clock = _clock(hours={str(d): [] for d in range(7)})
    start = _dt(2026, 9, 21, 10, 0)
    assert clock.next_opening(start) is None
    assert clock.add_business_minutes(start, 30) == start.replace(minute=30)


def test_zero_or_negative_minutes_returns_the_start() -> None:
    clock = _clock(hours=WEEKDAYS_9_TO_5)
    start = _dt(2026, 9, 21, 10, 0)
    assert clock.add_business_minutes(start, 0) == start
    assert clock.add_business_minutes(start, -5) == start


# --- validation ------------------------------------------------------------


def test_a_valid_calendar_passes() -> None:
    validate_calendar(WEEKDAYS_9_TO_5, ["2026-01-01"])


@pytest.mark.parametrize(
    "bad",
    [
        {"7": [["09:00", "17:00"]]},  # invalid weekday
        {"1": [["17:00", "09:00"]]},  # close before open
        {"1": [["9am", "5pm"]]},  # not HH:MM
        {"1": [["09:00"]]},  # not a pair
    ],
)
def test_a_malformed_calendar_is_refused(bad: dict) -> None:
    with pytest.raises(ValidationError):
        validate_calendar(bad, [])


def test_holidays_must_be_a_list() -> None:
    with pytest.raises(ValidationError):
        validate_calendar(None, "2026-01-01")


# --- a CLOSED day expressed as null / omitted (regression) -----------------
#
# JSON object keys are always strings, and `null` is the documented way to say
# "closed" (the BusinessCalendar docstring: {"mon": [["09:00","17:00"]],
# "sun": null}). The weekday lookup read `hours.get(str(weekday))` but the
# "does this calendar define any weekday?" test checked for INTEGER keys, so a
# string-keyed calendar never matched and every closed/omitted day fell through
# to _ALWAYS_OPEN: a merchant closed on Friday and Saturday had both days read
# as 24/7 open, pushing every SLA deadline later than it should be.

CLOSED_FRIDAY_AS_NULL = {
    "0": [["09:00", "17:00"]],
    "1": [["09:00", "17:00"]],
    "2": [["09:00", "17:00"]],
    "3": [["09:00", "17:00"]],
    "4": None,  # Friday closed
    "6": [["09:00", "17:00"]],
}


def test_a_null_weekday_is_closed() -> None:
    clock = BusinessClock(FakeCalendar(hours=CLOSED_FRIDAY_AS_NULL))
    # Friday 2026-09-25, 12:00 — inside the 09:00-17:00 window other days use.
    assert clock.is_open(_dt(2026, 9, 25, 12, 0)) is False


def test_a_null_weekday_does_not_run_a_business_clock_through_it() -> None:
    """The deadline must jump to the next OPEN day, not count Friday."""
    clock = BusinessClock(FakeCalendar(hours=CLOSED_FRIDAY_AS_NULL))
    # Thursday 16:00 + 60 business minutes = 09:00-16:00 split: 60 min of
    # Thursday left, so the rest lands on the next open day (Sunday, since
    # Saturday is omitted/undefined here and must also read as closed).
    deadline = clock.add_business_minutes(_dt(2026, 9, 24, 16, 0), 60)
    assert deadline.weekday() != 4, f"landed on closed Friday: {deadline}"


def test_an_omitted_weekday_is_closed_when_others_are_defined() -> None:
    """Saturday is absent from the dict entirely — that means closed."""
    clock = BusinessClock(FakeCalendar(hours=CLOSED_FRIDAY_AS_NULL))
    # Saturday 2026-09-26, 12:00
    assert clock.is_open(_dt(2026, 9, 26, 12, 0)) is False


def test_integer_keys_behave_the_same_as_string_keys() -> None:
    as_int = {0: [["09:00", "17:00"]], 4: None}
    clock = BusinessClock(FakeCalendar(hours=as_int))
    assert clock.is_open(_dt(2026, 9, 25, 12, 0)) is False  # Friday closed
    assert clock.is_open(_dt(2026, 9, 21, 12, 0)) is True  # Monday open


def test_an_empty_calendar_is_still_24_7() -> None:
    """The fix must not close a tenant that never configured hours."""
    clock = BusinessClock(FakeCalendar(hours={}))
    assert clock.is_open(_dt(2026, 9, 25, 3, 0)) is True


def test_a_calendar_of_only_null_days_never_opens() -> None:
    """Defining ANY weekday makes the omitted ones closed.

    So a calendar whose only entry is null never opens. That is the documented
    intent ("treat as closed for that weekday only if the calendar defines other
    days") and it is handled downstream — the clock degrades to wall-clock
    rather than silently treating the tenant as 24/7.
    """
    clock = BusinessClock(FakeCalendar(hours={"4": None}))
    assert clock.is_open(_dt(2026, 9, 25, 12, 0)) is False  # Friday, the null day
    assert clock.is_open(_dt(2026, 9, 21, 12, 0)) is False  # Monday, omitted
