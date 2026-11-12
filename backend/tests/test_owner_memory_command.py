"""The owner saves a note by SAYING so, and the code, not the model, does the saving.

The assistant is read only. If the model could write memory, any text that reaches it (a customer's
comment, a product name) could try to make it "remember" something. So a note is only ever saved by
an explicit sentence the owner typed, recognised here before the model is called.

``parse_memory_command`` is deliberately narrow. A question that merely contains the word
("do you remember what sold?") is a question, and a negation ("don't remember that") is not a save.
Getting this wrong in either direction is a bug: one saves what nobody asked to keep, the other
ignores an owner who asked.
"""

from __future__ import annotations

import pytest

from app.modules.ai.owner_memory_command import MemoryCommand, parse_memory_command

SAVE = [
    ("افتكر إن المورد الرئيسي اسمه حسين", "المورد الرئيسي اسمه حسين"),
    ("افتكر ان الخصم الأقصى 10%", "الخصم الأقصى 10%"),
    ("افتكر: بنقفل الجمعة", "بنقفل الجمعة"),
    ("فكرني إن الإيجار أول الشهر", "الإيجار أول الشهر"),
    ("خليك فاكر إني بحب التقارير مختصرة", "إني بحب التقارير مختصرة"),
    ("خلي في بالك إن الشتا موسم البلوفر", "الشتا موسم البلوفر"),
    ("سجل عندك إن عندي فرعين", "عندي فرعين"),
    ("remember that my main supplier is Hussein", "my main supplier is Hussein"),
    ("Remember: we close on Fridays", "we close on Fridays"),
    ("  افتكر   إن   المحل   بيفتح 10   ", "المحل بيفتح 10"),
    ("الحمد لله\nافتكر إن عندي موظفين اتنين", None),  # not at the start: a question, not a command
]

NOT_A_SAVE = [
    "تفتكر إيه اللي اتباع الأسبوع ده؟",
    "افتكرت إن المخزون قليل",  # past tense: the owner is telling a story
    "هل تفتكر المورد بتاعي؟",
    "do you remember what sold yesterday?",
    "I remember that we closed Friday",
    "ما تفتكرش الكلام ده",
    "متفتكرش إن عندي دين",
    "don't remember that",
    "do not remember this",
    "مش عايزك تفتكر ده",
    "انسى اللي قلته",
    "ربحي كام؟",
    "",
    "   ",
    "افتكر",  # the word alone: nothing to keep
    "افتكر إن",  # a lead-in with no note
    "remember",
    "remember that",
]


@pytest.mark.parametrize(("text", "note"), [c for c in SAVE if c[1] is not None])
def test_an_explicit_remember_sentence_is_recognised_with_its_note(text, note):
    cmd = parse_memory_command(text)
    assert cmd == MemoryCommand(kind="remember", note=note), text


@pytest.mark.parametrize("text", NOT_A_SAVE)
def test_questions_stories_negations_and_empty_lead_ins_are_not_a_save(text):
    assert parse_memory_command(text) is None, text


def test_a_command_only_counts_at_the_start_of_the_message():
    assert parse_memory_command("الحمد لله\nافتكر إن عندي موظفين اتنين") is None
    assert parse_memory_command("ربحي كام؟ وافتكر إن الإيجار أول الشهر") is None


def test_hidden_characters_and_other_spellings_do_not_hide_the_command():
    assert parse_memory_command("اف\u200dتكر إن المحل بيقفل الجمعة") == MemoryCommand(
        kind="remember", note="المحل بيقفل الجمعة"
    )
    assert parse_memory_command("إفتكر إن عندي فرعين") == MemoryCommand(
        kind="remember", note="عندي فرعين"
    )
    assert parse_memory_command("ＲＥＭＥＭＢＥＲ that I open at nine") == MemoryCommand(
        kind="remember", note="I open at nine"
    )


def test_the_note_keeps_the_owners_own_words_and_is_not_rewritten():
    cmd = parse_memory_command('افتكر إن "سعر الجملة" أقل بـ 15% من سعر المحل')
    assert cmd.note == '"سعر الجملة" أقل بـ 15% من سعر المحل'


def test_a_very_long_note_is_returned_whole_so_the_service_can_refuse_it():
    """Cutting it here would silently save half of what the owner said."""
    long_note = "ا" * 900
    cmd = parse_memory_command(f"افتكر إن {long_note}")
    assert cmd.note == long_note


# ----------------------------------------------------------------- forget / list / switch

FORGET_ALL = ["انسى كل حاجة", "امسح كل الذاكرة", "forget everything", "امسح كل اللي فاكره عني"]
LIST = ["إيه اللي فاكره عني؟", "اعرض الذاكرة", "what do you remember about me?", "show my memory"]
OFF = ["وقف الذاكرة", "اقفل الذاكرة", "turn off memory", "stop remembering"]
ON = ["شغل الذاكرة", "افتح الذاكرة", "turn on memory"]


@pytest.mark.parametrize("text", FORGET_ALL)
def test_forget_everything(text):
    assert parse_memory_command(text) == MemoryCommand(kind="forget_all")


@pytest.mark.parametrize("text", LIST)
def test_list_what_is_remembered(text):
    assert parse_memory_command(text) == MemoryCommand(kind="list")


@pytest.mark.parametrize("text", OFF)
def test_switch_memory_off(text):
    assert parse_memory_command(text) == MemoryCommand(kind="off")


@pytest.mark.parametrize("text", ON)
def test_switch_memory_on(text):
    assert parse_memory_command(text) == MemoryCommand(kind="on")


@pytest.mark.parametrize(
    "text",
    [
        "انسى المورد حسين",  # forgetting ONE thing needs the screen: an ambiguous delete is not run
        "امسح الأوردر ده",  # an order is not a memory
        "امسح كل الأوردرات",  # "all" of something else
        "forget the supplier",
        "اقفل الوردية",  # close the shift, not the memory
        "وقف الطباعة",
        "شغل الكاشير",
    ],
)
def test_phrases_about_other_things_are_not_memory_commands(text):
    assert parse_memory_command(text) is None, text


def test_a_pronoun_fused_to_that_stays_in_the_note():
    """ "إني" is "that I". Dropping it would save "likes short reports" about nobody in general."""
    cmd = parse_memory_command("افتكر إني بحب التقارير مختصرة")
    assert cmd.note == "إني بحب التقارير مختصرة"
    assert parse_memory_command("افتكر إنه بيسافر كل شهر").note == "إنه بيسافر كل شهر"
    assert parse_memory_command("افتكر إن المحل بيقفل").note == "المحل بيقفل"


def test_a_command_in_the_middle_of_a_sentence_is_not_a_command():
    """Phrased so that a pattern with its start anchor removed WOULD match."""
    assert parse_memory_command("الحمد لله افتكر إن عندي فرعين") is None
    assert parse_memory_command("ربحي كام؟ وافتكر إن الإيجار أول الشهر") is None
    assert parse_memory_command("الأسبوع ده كان صعب، افتكر إن المورد اتأخر") is None


def test_a_question_about_remembering_with_a_long_tail_is_still_a_question():
    """Phrased so that a loose 'what ... remember ...' pattern WOULD match."""
    assert parse_memory_command("what do you remember about my orders from last year") is None
    assert parse_memory_command("what did I tell you to remember") is None
    assert parse_memory_command("ايه اللي فاكره عن طلبات السنة اللي فاتت كلها") is None


def test_invisible_and_direction_control_characters_are_not_saved_into_the_note():
    """Stored as typed, they would show the owner a blank gap or flip the text in their own screen.
    The service folds before it checks, so nothing unsafe slips through, but the saved words must
    be the clean ones."""
    zero = parse_memory_command("افتكر إن المحل\u200b بيقفل")
    assert zero.note == "المحل بيقفل"
    flip = parse_memory_command("افتكر إن المحل بيقفل\u202e الجمعة")
    assert flip.note == "المحل بيقفل الجمعة"
    assert not any(ord(c) in (0x200B, 0x200D, 0x202E, 0x2066) for c in flip.note)
