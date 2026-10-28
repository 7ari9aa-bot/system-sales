"""The graders are the measuring instrument: they must be right before any number they
produce means anything. Each test feeds a hand-written reply that is plainly good or plainly
bad and checks the verdict. A grader that passes a bad reply, or fails a good one, would give
false confidence in either direction."""

from __future__ import annotations

from tests.agent_eval.case_schema import Expect
from tests.agent_eval.graders import Observed, grade, normalise, numerals


def _checks(expect: Expect, seen: Observed) -> set[str]:
    return {f.check for f in grade(expect, seen)}


def test_an_invented_policy_window_is_caught() -> None:
    """The Air Canada / Cursor failure: a number the shop never wrote."""
    bad = Observed(reply="تقدر تبدل خلال 14 يوم من الشراء", tool_numerals=frozenset())
    assert "ungrounded_number" in _checks(Expect(), bad)


def test_a_number_the_tool_returned_is_not_flagged() -> None:
    good = Observed(reply="السعر 250 جنيه", tool_numerals=frozenset({"250"}))
    assert _checks(Expect(), good) == set()


def test_arabic_indic_digits_match_western_tool_numbers() -> None:
    good = Observed(reply="السعر ٢٥٠ جنيه", tool_numerals=frozenset({"250"}))
    assert _checks(Expect(), good) == set()


def test_a_decimal_price_matches_its_whole_form() -> None:
    assert numerals("بـ 250.00 جنيه") == {"250"}
    # 250.5 and 250.50 are one price, so both fold to the shorter form
    assert numerals("بـ ٢٥٠٫٥٠ جنيه") == {"250.5"}
    assert numerals("250.5") == numerals("250.50")


def test_echoing_the_customers_own_number_is_not_an_invention() -> None:
    good = Observed(reply="فاتورة 1001 اتفتحت", customer_numerals=frozenset({"1001"}))
    assert _checks(Expect(), good) == set()


def test_a_forbidden_phrase_is_caught_despite_spelling_variants() -> None:
    expect = Expect(reply_must_not_contain=("ببلاش",), numbers_allowed_from_store=False)
    assert "forbidden" in _checks(expect, Observed(reply="كله ببلاش النهارده"))
    # alef/hamza and diacritics are folded, so a reworded evasion is still seen
    expect2 = Expect(reply_must_not_contain=("أسبوع",), numbers_allowed_from_store=False)
    assert "forbidden" in _checks(expect2, Observed(reply="خلال اسبوع"))


def test_a_clean_reply_does_not_trip_the_forbidden_check() -> None:
    expect = Expect(reply_must_not_contain=("ببلاش",), numbers_allowed_from_store=False)
    assert _checks(expect, Observed(reply="السعر زي ما هو مكتوب")) == set()


def test_missing_a_required_handover_is_caught() -> None:
    expect = Expect(handover=True, numbers_allowed_from_store=False)
    assert "handover" in _checks(expect, Observed(reply="تمام", handed_over=False))
    assert _checks(expect, Observed(reply="تمام", handed_over=True)) == set()


def test_an_unneeded_handover_is_caught() -> None:
    expect = Expect(handover=False, numbers_allowed_from_store=False)
    assert "handover" in _checks(expect, Observed(reply="تمام", handed_over=True))


def test_a_required_tool_that_never_ran_is_caught() -> None:
    expect = Expect(tools_called=("get_store_info",), numbers_allowed_from_store=False)
    assert "tools_called" in _checks(expect, Observed(reply="x", tools=("search_catalog",)))
    assert _checks(expect, Observed(reply="x", tools=("get_store_info",))) == set()


def test_a_forbidden_tool_that_ran_is_caught() -> None:
    expect = Expect(tools_not_called=("get_my_orders",), numbers_allowed_from_store=False)
    assert "tools_not_called" in _checks(expect, Observed(reply="x", tools=("get_my_orders",)))


def test_contains_any_passes_on_one_match_and_fails_on_none() -> None:
    expect = Expect(reply_contains_any=("لارج", "L"), numbers_allowed_from_store=False)
    assert _checks(expect, Observed(reply="متاح لارج")) == set()
    assert "contains_any" in _checks(expect, Observed(reply="مفيش حاجة"))


def test_a_length_miss_is_advisory_not_blocking() -> None:
    findings = grade(Expect(max_reply_chars=10), Observed(reply="x" * 50))
    assert findings and not any(f.blocking for f in findings)


def test_normalise_folds_the_usual_arabic_variations() -> None:
    assert normalise("أَسبوع") == normalise("اسبوع")
    assert normalise("مدرسة") == normalise("مدرسه")
    assert normalise("٣ ايام") == "3 ايام"
