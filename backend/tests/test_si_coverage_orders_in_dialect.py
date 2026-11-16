"""The coverage check knows the Egyptian word for an order: "أوردر", not only "طلب".

Found by reading a live trace. The owner asked "قارن الطلبات والفلوس والإيراد". The first answer
was good and covered orders ("عدد الأوردرات: صفر مقابل صفر"), but the check looked for
طلب / طلبات / order and never أوردر, so it called orders a gap and made a second model call
(44.8 s, 3,310 tokens) that rewrote a sound answer into a longer, weaker one. The assistant is
told to write in the shop's own voice, so the check has to read that voice.
"""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence.coverage import coverage_gaps

EVIDENCE = {"facts": [{"metric": "orders_placed", "value": "0", "source": "orders"}]}
QUESTION = "قارن الطلبات والفلوس والإيراد آخر 15 يوم"


@pytest.mark.parametrize(
    "answer",
    [
        "عدد الأوردرات: صفر مقابل صفر.",
        "الأوردر الوحيد كان في سبتمبر.",
        "مفيش اوردرات جديدة.",
        "مفيش أوردرات جديدة.",
        "الطلبات صفر.",
        "orders: 0.",
    ],
)
def test_an_answer_that_names_orders_in_any_of_the_ways_people_say_it_is_not_a_gap(answer):
    assert "orders" not in coverage_gaps(QUESTION, answer, EVIDENCE)


def test_an_answer_that_never_mentions_orders_is_still_a_gap():
    assert "orders" in coverage_gaps(QUESTION, "الفلوس صفر والإيراد صفر.", EVIDENCE)


@pytest.mark.parametrize("question", ["الأوردرات عاملة ايه", "كام اوردر اتباع", "وريني الأوردر"])
def test_a_question_that_says_the_dialect_word_is_asking_about_orders(question):
    assert "orders" in coverage_gaps(question, "الفلوس صفر.", EVIDENCE)
    assert "orders" not in coverage_gaps(question, "عدد الأوردرات صفر.", EVIDENCE)


def test_the_real_first_answer_from_production_has_no_orders_gap():
    live = (
        "بص على المقارنة، آخر 15 يوم مقابل اللي قبلها:\n"
        "- **عدد الأوردرات**: صفر مقابل صفر.\n"
        "- **الإيراد المسلَّم**: صفر مقابل صفر.\n"
        "- **الفلوس اللي اتحصَّلت**: صفر مقابل صفر.\n"
        "الأوردرات: النظام بيسجّل أوردرات فعلاً، بس آخر أوردر متسجَّل هو سبتمبر."
    )
    assert "orders" not in coverage_gaps(QUESTION, live, EVIDENCE)
