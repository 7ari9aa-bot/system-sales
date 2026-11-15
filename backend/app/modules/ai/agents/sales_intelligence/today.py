"""What day it is, for the owner assistant: facts the model cannot work out for itself.

The tools read a trailing ``days`` window that ENDS YESTERDAY in the shop's time zone (today is not
complete, so it is never part of a window). An owner says "this month", "yesterday", "last month".
Turning that into a ``days`` count is date arithmetic with an off-by-one at every edge (on the 15th
"this month" is 14 days; on the 1st it is none), and a model asked to do it guesses or falls back to
30. This module does the arithmetic once, in code, from the real clock in the shop's zone.

It returns FACTS for the model (a date, day names, day counts), never words for the owner, so it
does not create a prepared reply: the model still writes every answer, in the shop's dialect.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

# The ceilings the tools enforce: the sales reads stop at 90 days, the money reads at 366. They are
# stated in the main prompt (they never change), so this block carries only what changes daily.
SALES_MAX_DAYS = 90
MONEY_MAX_DAYS = 366

_DAYS_AR = ("الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _first_of_last_month(d: date) -> date:
    return _first_of_month(_first_of_month(d) - timedelta(days=1))


def today_context(now: datetime, zone: ZoneInfo | None = None) -> str:
    """The date block for the system message, computed from ``now`` in the shop's ``zone``.

    ``now`` may carry any zone (the server runs in UTC); ``zone`` is the shop's. When no zone is
    given, the clock's own zone is used.
    """
    if zone is not None:
        now = now.astimezone(zone)
    today = now.date()
    yesterday = today - timedelta(days=1)

    first_this = _first_of_month(today)
    first_last = _first_of_last_month(today)
    last_month_end = first_this - timedelta(days=1)

    # A window of N days covers yesterday and the N-1 days before it, so "since date D" is
    # (today - D) days: D = the first of the month on the 15th gives 14, the days 1..14.
    this_month_days = (today - first_this).days
    last_month_back = (today - first_last).days

    rows = [
        f"النهارده عند صاحب المحل: {today.isoformat()} ({_DAYS_AR[today.weekday()]}). "
        f"أمس: {yesterday.isoformat()}."
    ]
    if this_month_days >= 1:
        rows.append(f"هذا الشهر (من {first_this.isoformat()} لحد أمس): days={this_month_days}.")
    else:
        rows.append(
            "هذا الشهر: لسه ما فيش يوم مكتمل فيه (النهارده أول يوم)، فقول كده بدل ما تستخدم "
            "آخر 30 يوم على إنها الشهر ده."
        )
    rows.append(
        f"الشهر اللي فات ({first_last.isoformat()} لحد {last_month_end.isoformat()}): "
        f"days={last_month_back} (بيشمل كمان أيام من هذا الشهر، فقول الفترة الفعلية)."
    )
    return "\n".join(rows)


def now_in(zone: ZoneInfo) -> datetime:
    """The current instant in the shop's zone (a seam so tests can pin the clock)."""
    return datetime.now(UTC).astimezone(zone)
