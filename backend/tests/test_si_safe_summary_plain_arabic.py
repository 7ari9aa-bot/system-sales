"""The safe summary shows a shop owner plain Arabic, never the analytics layer's engineer wording.

Found by asking the live assistant: when its answer was refused, the summary that replaced it read
"orders_placed: last 30d vs prior 30d ... (الثقة: LOW, sample below minimum (3 < 10))".
The analytics layer words its comparison labels and confidence reasons for engineers (and other
modules store them), so the translation lives here, in the one place the owner sees them. A
reason the table does not know is left out instead of shown in English.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.ai.agents.sales_intelligence.plain_words import plain_words
from app.applications.apparel.modules.ai.agents.sales_intelligence.response import safe_response

LATIN_WORD = re.compile(r"[A-Za-z]{2,}")


def _finding(statement="جملة عادية", confidence="LOW", reasons=()):
    return SimpleNamespace(
        statement=statement, confidence=confidence, confidence_reasons=list(reasons)
    )


def _shown(*findings) -> str:
    """What the owner reads: the summary after the same plain-words pass the agent applies."""
    return plain_words(safe_response(list(findings), {}))


ALL_REASONS = [
    "sample below minimum (3 < 10)",
    "period PARTIALLY_MATURE",
    "period IMMATURE",
    "temporal association is not causation",
    "hypotheses are never HIGH",
    "relies on reconstructed history",
    "data STALE — downgraded one level",
]


@pytest.mark.parametrize("reason", ALL_REASONS)
def test_every_known_confidence_reason_is_shown_in_arabic(reason):
    text = _shown(_finding(reasons=[reason]))
    assert not LATIN_WORD.search(text), text
    assert "(الثقة ضعيفة:" in text


def test_the_numbers_inside_a_reason_are_kept():
    text = _shown(_finding(reasons=["sample below minimum (3 < 10)"]))
    assert "3 من أصل 10" in text


def test_a_reason_nobody_translated_is_left_out_rather_than_shown_in_english():
    text = _shown(_finding(reasons=["some new internal reason"]))
    assert "internal" not in text
    assert "(الثقة ضعيفة)" in text


def test_an_unknown_reason_does_not_hide_a_known_one_after_it():
    text = _shown(_finding(reasons=["some new internal reason", "period IMMATURE"]))
    assert "لسه ما اكتملتش" in text and "internal" not in text


def test_only_the_first_two_known_reasons_are_shown():
    text = _shown(_finding(reasons=ALL_REASONS))
    assert text.count("؛") == 1


@pytest.mark.parametrize(("level", "word"), [("LOW", "ضعيفة"), ("MEDIUM", "متوسطة")])
def test_the_confidence_level_is_an_arabic_word_not_a_code(level, word):
    text = _shown(_finding(confidence=level, reasons=["period IMMATURE"]))
    assert f"الثقة {word}" in text
    assert "LOW" not in text and "MEDIUM" not in text


def test_a_high_confidence_finding_shows_no_confidence_line():
    assert "الثقة" not in _shown(_finding(confidence="HIGH"))


@pytest.mark.parametrize(
    ("days", "said"),
    [
        (1, "آخر يوم"),
        (2, "آخر يومين"),
        (3, "آخر 3 أيام"),
        (10, "آخر 10 أيام"),
        (11, "آخر 11 يوم"),
        (30, "آخر 30 يوم"),
    ],
)
def test_a_comparison_label_is_put_into_arabic_with_the_right_day_word(days, said):
    text = _shown(_finding(f"orders_placed: last {days}d vs prior {days}d: القيمة زاد بمقدار 5.0%"))
    assert said in text
    assert "last" not in text and "prior" not in text
    assert "عدد الأوردرات" in text  # the metric name is the shop word, not orders_placed


@pytest.mark.parametrize(("went", "said"), [("زاد", "زادت"), ("انخفض", "انخفضت")])
def test_the_verb_agrees_with_the_feminine_word_value(went, said):
    text = _shown(_finding(f"aov: last 7d vs prior 7d: القيمة {went} بمقدار 5.0%"))
    assert f"القيمة {said} بمقدار 5.0%" in text


def test_the_percentage_in_a_statement_is_never_changed():
    text = _shown(_finding("aov: last 30d vs prior 30d: القيمة زاد بمقدار 12.5%"))
    assert "12.5%" in text


def test_a_statement_in_any_other_shape_is_left_alone():
    assert "جملة عادية" in _shown(_finding("جملة عادية"))


def test_two_different_spans_are_both_said_and_never_called_the_same_duration():
    text = _shown(_finding("aov: last 30d vs prior 7d: القيمة زاد بمقدار 5.0%"))
    assert "آخر 30 يوم مقابل 7 أيام قبلها" in text
    assert "نفس المدة" not in text
    assert not LATIN_WORD.search(text), text


def test_equal_spans_are_called_the_same_duration():
    assert "نفس المدة" in _shown(_finding("aov: last 7d vs prior 7d: القيمة زاد بمقدار 5.0%"))


def test_a_label_in_a_shape_we_do_not_know_is_not_guessed_at():
    text = _shown(_finding("aov: last 30d vs the year before: القيمة زاد بمقدار 5.0%"))
    assert "نفس المدة" not in text and "مقابل" not in text


def test_nothing_in_a_full_summary_is_left_in_english():
    text = _shown(
        _finding(
            "orders_placed: last 30d vs prior 30d: القيمة زاد بمقدار 5.0%", reasons=ALL_REASONS
        ),
        _finding(
            "delivered_revenue: last 7d vs prior 7d: القيمة انخفض بمقدار 1.5%",
            "MEDIUM",
            ALL_REASONS,
        ),
    )
    assert not LATIN_WORD.search(text), text


def test_with_no_findings_the_summary_is_unchanged():
    assert "نحلل بأمان" in safe_response([], {})
