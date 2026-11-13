"""What the assistant may SUGGEST remembering about the owner, measured from what they asked.

A habit here is a count: the same period asked for again and again. No model reads the questions
and nothing is saved by this module. It returns a suggestion, and the owner accepts it on the memory
screen; only then does it become a note (``source="inferred"``).

Two choices keep it from becoming a way to write into the memory:

* The suggestion text is a fixed sentence per period, never the owner's own words. A customer's
  name or a pasted comment inside a question cannot reach a note through this module.
* A habit needs a minimum number of questions AND a clear majority among the questions that name a
  period at all. A handful of questions, or an even spread, suggests nothing.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.modules.ai.owner_memory import _fold

# Fewer questions than this say nothing about a habit.
MIN_PERIOD_QUESTIONS = 5
# The favourite period must be at least this share of the questions that name any period.
PERIOD_SHARE = 0.6
# Only the most recent questions are measured, so a habit that changed shows up instead of being
# outvoted by a long history.
RECENT_QUESTIONS = 60


@dataclass(frozen=True)
class Habit:
    period: str
    count: int
    suggestion: str


# period -> the sentence offered to the owner. Fixed text on purpose (see the module docstring).
_SUGGESTIONS = {
    "today": "بتفضّل تشوف أرقام النهارده",
    "yesterday": "بتفضّل تشوف أرقام امبارح",
    "last_7_days": "بتفضّل تشوف الأرقام عن آخر 7 أيام",
    "last_30_days": "بتفضّل تشوف الأرقام عن آخر 30 يوم",
    "this_month": "بتفضّل تشوف الأرقام عن الشهر الحالي",
}

# Patterns run on FOLDED text (hamza forms, ى/ي, ة/ه flattened, Arabic-Indic digits to ASCII), so
# they are written in that folded spelling. Order matters: the first period that matches names the
# question, so the specific ones (a number of days) come before the general ones.
_PERIODS: list[tuple[str, re.Pattern[str]]] = [
    ("last_30_days", re.compile(r"(?:اخر|لاخر|خلال|last|past)\s*(?:30|ثلاثين)\s*(?:يوم|days?)")),
    (
        "last_7_days",
        re.compile(
            r"(?:اخر|لاخر|خلال|last|past)\s*(?:7|سبعه|سبع)\s*(?:ايام|يوم|days?)"
            r"|(?:الاسبوع|اسبوع)\s*(?:اللي\s*فات|الماضي|الي\s*فات)"
            r"|(?:last|past)\s*week"
        ),
    ),
    ("yesterday", re.compile(r"امبارح|امس\b|yesterday")),
    ("today", re.compile(r"النهارده|النهارد[هة]|اليوم|today")),
    ("this_month", re.compile(r"الشهر\s*(?:ده|دا|هذا|الحالي|الجاري)|this\s*month")),
]

# A period the owner is refusing, not asking for: "not the last 7 days".
_NEGATION = re.compile(r"(?:مش|ليس|لا|بدون|غير|not|no)\s*(?:عايز|عاوز|اريد|want)?\s*$")


def _period_of(text: str) -> str | None:
    folded = _fold(text)
    for period, pattern in _PERIODS:
        match = pattern.search(folded)
        if match is None:
            continue
        before = folded[max(0, match.start() - 14) : match.start()]
        if _NEGATION.search(before):
            continue
        return period
    return None


PERIODS = tuple(_SUGGESTIONS)


def suggestion_text(period: str) -> str | None:
    """The fixed sentence for a period key, or None for anything that is not one of ours."""
    return _SUGGESTIONS.get(period)


def detect_period_habit(questions: list[str]) -> Habit | None:
    """The period this owner keeps asking about, or None when there is no clear habit."""
    counts: Counter[str] = Counter()
    for question in questions:
        if not isinstance(question, str) or not question.strip():
            continue
        period = _period_of(question)
        if period is not None:
            counts[period] += 1
    total = sum(counts.values())
    if total < MIN_PERIOD_QUESTIONS:
        return None
    period, count = counts.most_common(1)[0]
    if count < MIN_PERIOD_QUESTIONS or count / total < PERIOD_SHARE:
        return None
    return Habit(period=period, count=count, suggestion=_SUGGESTIONS[period])
