"""Recognising "remember this" in what the owner typed, before the model is ever called.

The assistant is read only, and a memory is a write. If the model could save one, any text that
reaches it (a customer's comment, a product name) could try to make it "remember" something. So the
model never saves a note. The owner does, by saying so, and this module is the only reader of those
sentences. It is a pure function: text in, command out, no database and no model.

It is narrow on purpose. A question that merely contains the word ("do you remember what sold?") is
a question, a past-tense story ("I remembered the stock was low") is a story, and a negation
("don't remember that") is the opposite of a save. Only a sentence that BEGINS with the command
counts, and only with something after it to keep.

Forgetting one note by voice is not supported: "forget the supplier" could mean any of several
notes, and a wrong delete costs more than asking the owner to use the screen. Forgetting
EVERYTHING is unambiguous, so it is.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.modules.ai.owner_memory import _fold


@dataclass(frozen=True)
class MemoryCommand:
    kind: str  # remember | forget_all | list | off | on
    note: str | None = None


def _clean(text: str) -> str:
    """The owner's words with hidden characters and spacing tidied, and nothing else changed."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(
        ch for ch in text if unicodedata.category(ch) not in ("Cf", "Cc") or ch in "\n\t "
    )
    return re.sub(r"[ \t]+", " ", text).strip()


def _p(pattern: str, flags: int = 0) -> re.Pattern[str]:
    """Compile a pattern written in natural spelling, matched against FOLDED text.

    The text is folded (hamza forms, ى/ي, ة/ه, tashkeel flattened) before matching, so a pattern
    written with "انسى" or "ذاكرة" would never match "انسي" or "ذاكره". Only the ARABIC letters of
    the pattern are folded, with the same table the text goes through, so the two cannot drift
    apart. Everything else is left alone: folding the whole pattern would lower-case ``\\S`` into
    ``\\s`` and ``(?P<`` into ``(?p<``, which reverses its meaning or breaks it."""
    arabic = re.compile(r"[\u0600-\u06FF]+")
    return re.compile(arabic.sub(lambda m: _fold(m.group(0)), pattern), flags)


# What may follow the command word before the note itself: "that", ":", "إن", "ان".
# Only the bare conjunction is dropped. "إني" and "إنه" are "that I" and "that he", so the pronoun
# is part of what the owner said and stays in the note.
_LEAD_IN = r"(?:\s*[:：،,-]\s*|\s+(?:ان|إن|أن|that)\b\s*[:：،,-]?\s*|\s+)"

# The command words, in the FOLDED form (hamza forms and tashkeel already flattened by ``_fold``).
_REMEMBER = _p(
    r"^(?:"
    r"افتكر|فكرني|خليك فاكر|خلي في بالك|خلى فى بالك|سجل عندك|دون عندك|"
    r"remember|please remember|keep in mind|note that|make a note"
    r")" + _LEAD_IN + r"(?P<note>\S.*)$",
    re.DOTALL,
)

# A command word with nothing to keep ("افتكر", "remember that") is not a save.
_BARE = _p(
    r"^(?:افتكر|فكرني|خليك فاكر|خلي في بالك|سجل عندك|دون عندك|remember|please remember)"
    r"(?:\s+(?:ان|إن|أن|that))?\s*[:：،,-]?\s*$"
)

_FORGET_ALL = _p(
    r"^(?:"
    r"انسى\s+كل\s+(?:حاجه|شي|شيء|حاجة)|"
    r"امسح\s+(?:كل\s+)?(?:ال)?ذاكره|امسح\s+كل\s+(?:اللي|ما)\s+فاكره(?:\s+عني)?|"
    r"forget\s+(?:everything|all)|clear\s+(?:my\s+)?memory|delete\s+(?:my\s+)?memory"
    r")\s*[.!؟?]*$"
)
_LIST = _p(
    r"^(?:"
    r"(?:ايه|إيه)\s+اللي\s+فاكره\s+عني|ايه\s+فاكر\s+عني|"
    r"اعرض\s+(?:ال)?ذاكره|وريني\s+(?:ال)?ذاكره|"
    r"what\s+do\s+you\s+remember(?:\s+about\s+me)?|show\s+(?:me\s+)?(?:my\s+)?memory"
    r")\s*[.!؟?]*$"
)
_OFF = _p(
    r"^(?:وقف|اقفل|طفي|اقفل)\s+(?:ال)?ذاكره\s*[.!]*$|"
    r"^(?:turn\s+off|disable|stop)\s+(?:my\s+)?(?:memory|remembering)\s*[.!]*$"
)
_ON = _p(
    r"^(?:شغل|افتح|فعل)\s+(?:ال)?ذاكره\s*[.!]*$|"
    r"^(?:turn\s+on|enable)\s+(?:my\s+)?memory\s*[.!]*$"
)


def parse_memory_command(text: str | None) -> MemoryCommand | None:
    """The memory command the owner typed, or None when the message is anything else."""
    if not text or not text.strip():
        return None
    cleaned = _clean(text)
    folded = re.sub(r"\s+", " ", _fold(cleaned)).strip()
    if not folded:
        return None
    for kind, pattern in (
        ("forget_all", _FORGET_ALL),
        ("list", _LIST),
        ("off", _OFF),
        ("on", _ON),
    ):
        if pattern.match(folded):
            return MemoryCommand(kind=kind)
    if _BARE.match(folded):
        return None
    match = _REMEMBER.match(folded)
    if match is None:
        return None
    # The note is cut from the owner's OWN words, not from the folded copy, so a quote, a hamza or
    # a digit comes back as typed. The folded copy only decided that this is a command.
    note = _original_tail(cleaned, folded, match.start("note"))
    return MemoryCommand(kind="remember", note=note) if note else None


def _original_tail(cleaned: str, folded: str, folded_start: int) -> str:
    """The part of ``cleaned`` that corresponds to ``folded[folded_start:]``.

    Folding can change a character's width but not the number of words, so the tail is found by
    counting the words that precede it and slicing the original at the same word boundary."""
    words_before = len(folded[:folded_start].split())
    parts = re.split(r"(\s+)", cleaned)
    seen = 0
    for i, part in enumerate(parts):
        if part.strip():
            if seen == words_before:
                return re.sub(r"\s+", " ", "".join(parts[i:])).strip()
            seen += 1
    return ""
