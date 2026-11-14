"""A bare greeting or thanks gets one short line back, without a model call.

A single "هلا" used to run the whole assistant: 5 seconds, about 1,400 tokens in, and a long menu of
things it could do. The match is deliberately narrow so it can never swallow a real question: the
WHOLE message, after dropping decoration, must be one of a short closed list of greetings or thanks.
One extra word, a digit or a question sends it to the model exactly as before. The reply is fixed
text chosen by the server, never anything the sender wrote.
"""

from __future__ import annotations

import re
import unicodedata

_TATWEEL = "\u0640"

# closed lists, written in their folded form (see ``_fold``)
_GREETINGS_AR = frozenset(
    {
        "هلا",
        "اهلا",
        "اهلا وسهلا",
        "مرحبا",
        "مرحبتين",
        "السلام عليكم",
        "سلام عليكم",
        "سلام",
        "صباح الخير",
        "مساء الخير",
        "صباحو",
        "هاي",
        "هلا والله",
        "اهلين",
        "هلو",
    }
)
_THANKS_AR = frozenset(
    {
        "شكرا",
        "شكرا ليك",
        "شكرا لك",
        "شكرا جزيلا",
        "تسلم",
        "تسلم ايدك",
        "متشكر",
        "مشكور",
        "مرسي",
        "ميرسي",
        "يسلمو",
        "يسلمو ايدك",
    }
)
_GREETINGS_EN = frozenset({"hi", "hello", "hey", "good morning", "good evening", "hi there"})
_THANKS_EN = frozenset({"thanks", "thank you", "thx", "thanks a lot", "thank you so much"})

_REPLY_GREETING_AR = "أهلاً بيك! اسألني عن أي حاجة في المحل."
_REPLY_THANKS_AR = "العفو، أي وقت."
_REPLY_GREETING_EN = "Hi! Ask me anything about your shop."
_REPLY_THANKS_EN = "You're welcome, anytime."

_DECORATION = re.compile(r"[^\w\s]|_", re.UNICODE)  # punctuation, emoji, symbols
_SPACES = re.compile(r"\s+")


def _fold(text: str) -> str:
    """One spelling per word: lower case, no diacritics, tatweel, punctuation or emoji, and a letter
    stretched for emphasis ("هلاااا") back to one."""
    out = unicodedata.normalize("NFKD", text).lower().replace(_TATWEEL, "")
    out = "".join(ch for ch in out if not unicodedata.combining(ch))
    out = _DECORATION.sub(" ", out)
    out = re.sub(r"(.)\1{2,}", r"\1", out)  # three or more of a letter -> one
    return _SPACES.sub(" ", out).strip()


def smalltalk_reply(message: object) -> str | None:
    """The fixed short reply when the whole message is a greeting or thanks, else ``None``."""
    if not isinstance(message, str) or not message.strip():
        return None
    folded = _fold(message)
    if not folded:
        return None
    if any("\u0600" <= ch <= "\u06ff" for ch in folded):
        # the closed list is matched whole, never as a prefix
        if folded in _GREETINGS_AR:
            return _REPLY_GREETING_AR
        if folded in _THANKS_AR:
            return _REPLY_THANKS_AR
        return None
    if folded in _GREETINGS_EN:
        return _REPLY_GREETING_EN
    if folded in _THANKS_EN:
        return _REPLY_THANKS_EN
    return None
