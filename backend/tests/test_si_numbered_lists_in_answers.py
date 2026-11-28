"""A numbered list in an answer is a position, not a measurement, and must not be refused.

Found by asking the live assistant "which month was best?": the model answered with a list
("1. ... 2. ...") and the number gate read the 1 and the 2 as numbers no tool had produced, so the
owner got "no clear result" instead of an answer. The same would have hit any "top 3" question.

The rule is deliberately narrow. Only a marker is let through: one digit 1-9 at the start of a line,
then a dot or a bracket and a space, counting up from 1 with no gap. A figure must never be able to
hide by looking like a bullet, so everything else stays gated.
"""

from __future__ import annotations

import pytest

from app.applications.apparel.modules.ai.agents.sales_intelligence.response import validate_answer

ALLOWED = {"999"}


def _problems(text: str) -> list[str]:
    return validate_answer(text, ALLOWED, [])


@pytest.mark.parametrize(
    "text",
    [
        "أحسن شهر:\n1. سبتمبر\n2. أكتوبر",
        "1) الأول\n2) التاني\n3) التالت",
        "خطوات:\n١. سجّل الشحنات\n٢. راجع المصاريف",
        "  1. مسافة قبل الرقم\n  2. وتاني",
        "1. أ\n\n2. ب",
        "1. أ\n2. ب\n\nوبعدين:\n1. ج\n2. د",
    ],
)
def test_a_list_numbered_from_one_without_gaps_is_not_a_free_number(text):
    assert _problems(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "3. الأول\n4. التاني",
        "2. الأول\n3. التاني",
        "1. الأول\n3. التالت",
        "1. أ\n2. ب\n4. د",
        "5 عملاء جداد",
        "1.5 مليون",
        "هتزيد 20%",
        "1. المبيعات 9999\n2. تمام",
        "1. أ\n2. ب\nوعندك 77 أوردر",
        "المبيعات 1. وبعدين 2.",
    ],
)
def test_anything_that_is_not_a_clean_list_marker_is_still_gated(text):
    assert _problems(text), f"{text!r} should still be refused"


def test_a_number_inside_a_list_item_is_still_checked():
    assert _problems("1. المبيعات 9999\n2. تمام") == ["free number in answer: 9999"]


def test_a_measured_number_inside_a_list_item_is_allowed():
    assert _problems("1. المبيعات 999\n2. تمام") == []


def test_a_marker_is_dropped_only_from_the_line_start():
    assert _problems("الترتيب 1. سبتمبر") != []


def test_a_list_does_not_unlock_the_digits_in_the_rest_of_the_answer():
    assert _problems("1. أ\n2. ب\n3. ج\nوالمجموع 3") != []


def test_a_list_of_nine_items_passes_but_a_tenth_is_a_number():
    nine = "\n".join(f"{i}. بند" for i in range(1, 10))
    assert _problems(nine) == []
    assert _problems(nine + "\n10. بند") != []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.5\n2.5", ["free number in answer: 1.5", "free number in answer: 2.5"]),
        ("1.أ\n2.ب", ["free number in answer: 1.", "free number in answer: 2."]),
        ("1. أ\n2.ب", ["free number in answer: 2."]),
    ],
)
def test_a_marker_needs_a_space_so_a_decimal_is_never_cut_into_a_smaller_number(text, expected):
    """Without the space, "1.5" would lose its "1." and leave a "5" that looks harmless."""
    assert _problems(text) == expected
