"""A bare greeting or thanks is answered at once, with no model call and no menu.

"هلا" cost 5.4 seconds, 1364 tokens in and a long list of suggestions. A greeting needs one short
friendly line. The match is deliberately narrow: the WHOLE message must be a greeting (or thanks),
so a real question is never swallowed, and anything doubtful goes to the model as before."""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence.smalltalk import smalltalk_reply


@pytest.mark.parametrize(
    "text",
    [
        "هلا",
        "هلا!",
        "  هلا  ",
        "أهلا",
        "اهلا",
        "أهلاً",
        "مرحبا",
        "مرحباً",
        "السلام عليكم",
        "سلام عليكم",
        "صباح الخير",
        "مساء الخير",
        "هاي",
        "hi",
        "Hello",
        "HELLO!",
        "هلا.",
        "هلا؟",
    ],
)
def test_a_bare_greeting_gets_a_short_greeting_back(text):
    out = smalltalk_reply(text)
    assert out and len(out) <= 80
    assert "\n" not in out and "-" not in out  # one line, no list


@pytest.mark.parametrize(
    "text", ["شكرا", "شكراً", "شكرًا", "تسلم", "متشكر", "thanks", "Thank you", "شكرا ليك!"]
)
def test_thanks_gets_a_short_welcome(text):
    out = smalltalk_reply(text)
    assert out and len(out) <= 80 and "\n" not in out


@pytest.mark.parametrize(
    "text",
    [
        "هلا كام مبيعات النهاردة",  # a real question after the greeting
        "صباح الخير عايز أعرف المرتجعات",
        "هلا 5",
        "كام مبيعات النهاردة",
        "مبيعات؟",
        "شكرا بس المرتجعات كام",
        "hi what are my sales",
        "السلام عليكم ورحمة الله وبركاته عايز تقرير",
        "",
        "   ",
        "؟",
        "!!!",
    ],
)
def test_anything_more_than_a_greeting_goes_to_the_model(text):
    assert smalltalk_reply(text) is None


def test_none_and_non_text_go_to_the_model():
    assert smalltalk_reply(None) is None
    assert smalltalk_reply(123) is None


def test_the_reply_never_contains_a_suggestion_menu_or_internal_name():
    for text in ("هلا", "شكرا", "صباح الخير", "hi"):
        out = smalltalk_reply(text)
        assert "_" not in out and "(" not in out and ":" not in out


def test_the_match_ignores_letter_variants_and_decoration():
    assert smalltalk_reply("أهـــلا") is not None  # tatweel
    assert smalltalk_reply("هَلا") is not None  # a diacritic
    assert smalltalk_reply("هلا 👋") is not None  # an emoji
    assert smalltalk_reply("هلاااا") is not None  # stretched letters


def test_it_is_answered_in_the_language_it_was_written_in():
    ar = smalltalk_reply("هلا")
    en = smalltalk_reply("hello")
    assert any("\u0600" <= c <= "\u06ff" for c in ar)
    assert not any("\u0600" <= c <= "\u06ff" for c in en)


def test_a_word_that_merely_contains_a_greeting_is_not_one():
    assert smalltalk_reply("هلاك") is None
    assert smalltalk_reply("shi") is None
    assert smalltalk_reply("history") is None


@pytest.mark.parametrize("text", ["إهلا", "آهلا", "اهلاً وسهلاً", "مرحباً", "صباح الخيـر"])
def test_hamza_and_tatweel_spellings_of_a_greeting_are_still_a_greeting(text):
    assert smalltalk_reply(text) is not None


def test_english_thanks_is_answered_in_english():
    out = smalltalk_reply("thanks")
    assert out and not any("\u0600" <= c <= "\u06ff" for c in out)
