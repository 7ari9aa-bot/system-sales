"""The owner assistant's instructions: who it is, how it reads a period, and what "no data" means.

Each rule here exists because of a measured gap, not as decoration:

* it was introduced as a SALES analyst, so a question about stock or expenses read as out of scope;
* the model was never told the date, and the tools take a trailing day count, so "this month" was a
  guess (the date block now supplies the numbers; the prompt tells the model to use them and to
  say which period it answered);
* an empty answer could mean "no sales", "never recorded" or "the tool does not cover it", and the
  model had no way to say which. ``si_data_status`` now reports what the shop recorded.

Every line is an INSTRUCTION to the model. Nothing here is a sentence to be shown to the owner:
the standing rule is that no reply is prepared, so each answer is still written by the model.
"""

from __future__ import annotations

from app.modules.ai.agents.sales_intelligence.prompts import SI_SYSTEM_PROMPT as P

# phrases that would turn an instruction into a prepared reply the model could copy to the owner
CANNED = ("أهلا بيك", "أهلاً بيك", "تحت أمرك", "إزاي أقدر أساعدك", "كيف يمكنني مساعدتك")


def test_it_names_the_whole_shop_not_only_sales():
    for area in ("المخزون", "المصاريف", "الأرباح", "المشتريات", "الكاشير"):
        assert area in P, f"the assistant is not told it covers {area}"
    assert "تحليل المبيعات" not in P.split("\n")[0], "still introduced as a sales-only analyst"


def test_it_stays_read_only_and_for_the_owner():
    assert "للقراءة بس" in P
    assert "مش بتغيّر ولا بتنفّذ" in P
    assert "صاحب المحل" in P


def test_it_tells_the_model_to_use_the_date_it_is_given_and_to_name_the_period():
    assert "التاريخ اللي في آخر التعليمات" in P and "عدد الأيام" in P
    assert "متخمّنش" in P, "the model is not told to stop guessing the period"
    # examples of how an owner phrases a period, so the model knows what to convert
    for phrase in ("الشهر ده", "أمس"):
        assert phrase in P
    # and it must say WHICH days it answered about, in dates, not leave the owner to assume
    assert "قول الفترة اللي جاوبت عنها بتواريخها" in P


def test_an_unclear_question_is_answered_with_a_stated_assumption_not_a_questionnaire():
    assert "أقرب تفسير" in P
    assert "افتراضك" in P or "اللي افترضته" in P
    assert "متسألش" in P or "من غير ما تسأل" in P


def test_three_different_meanings_of_no_data_are_kept_apart():
    assert "si_data_status" not in P, "a tool name must never be written for the owner to see"
    # all three cases are present, numbered, each saying what it is
    assert "(1)" in P and "(2)" in P and "(3)" in P
    assert "ما سجّلش" in P  # (1) the shop never recorded it
    assert "صفر في الفترة" in P and "رقم حقيقي" in P  # (2) recorded, genuinely zero
    assert "مش من اللي بغطيها" in P  # (3) outside what the assistant reads
    # and it must forbid the lazy answer that hides which one it is
    assert "متقولش «مفيش بيانات» وبس" in P


def test_it_tells_the_model_to_check_what_was_recorded_before_claiming_there_is_none():
    assert "حالة البيانات" in P


def test_no_internal_or_tool_names_are_written_for_the_owner():
    for name in ("si_metric", "si_why", "si_activity", "si_finance", "si_stock_status"):
        assert name not in P, f"{name} would be shown to the owner"


def test_the_sales_rule_the_owner_chose_is_untouched():
    assert "delivered_revenue" in P and "collected_revenue" in P and "orders_placed" in P
    assert "الإيراد المسلَّم" in P


def test_the_dialect_is_not_hard_coded_into_the_rules():
    """The dialect is a per-shop setting that rides after the rules; the rules stay neutral."""
    assert "بنفس لغة وأسلوب صاحب المحل" in P
    for dialect_word in ("إزيك", "ازيك", "شلونك", "كيفك", "إيش"):
        assert dialect_word not in P


def test_nothing_in_it_is_a_canned_reply():
    for phrase in CANNED:
        assert phrase not in P, f"{phrase!r} reads as a prepared reply"


def test_it_does_not_grow_without_a_reason():
    """Every added line costs tokens on every turn. A bound makes growth a decision."""
    assert len(P) < 2100, (
        f"the prompt is {len(P)} characters; shorten it or raise the bound on purpose"
    )
