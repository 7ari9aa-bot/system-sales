"""SQL fragments several modules need and none should re-derive."""

from __future__ import annotations

LIKE_ESCAPE = "\\"


def escape_like(term: str) -> str:
    r"""Make a caller's text safe to embed in a LIKE pattern.

    `%` stands for anything and `_` for any one character, so a term typed into a
    search box widens the search the moment it is bound raw — `100%_off` asks for
    every row. The escape character is a backslash, and a statement that uses this
    must declare it (`escape="\\"` on the ORM side, `ESCAPE '\'` in raw SQL) or the
    backslashes stay literal text and the escaping does nothing.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_pattern(fragment: str) -> str:
    """A contains-match whose wildcards belong to us and only to us.

    The single owner of `%…%` in this codebase — `tests/test_like_patterns_are_escaped.py`
    fails the moment a call site spells the wrapping out for itself.
    """
    return f"%{escape_like(fragment)}%"


# --- Arabic-tolerant search -------------------------------------------------------------------
#
# A till is typed on by people who do not spell the way a catalogue was entered: "احمر" for
# "أحمر", "حقيبه" for "حقيبة", "شتوى" for "شتوي", with or without tashkeel, and digits from an
# Arabic keyboard ("٠٠٢٩٩٩"). A plain ILIKE misses all of them and the cashier sees "no result"
# for a product that exists. Nothing is rewritten in storage (no migration, no second column):
# the TERM is widened into a POSIX regex whose character classes accept every spelling of each
# letter, and it is matched with ``~*`` against the stored text.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# Every letter that has interchangeable spellings -> the class that matches all of them.
_ARABIC_CLASSES = {
    "ا": "[اأإآٱ]", "أ": "[اأإآٱ]", "إ": "[اأإآٱ]", "آ": "[اأإآٱ]", "ٱ": "[اأإآٱ]",
    "ة": "[ةه]", "ه": "[ةه]",
    "ي": "[يىئ]", "ى": "[يىئ]", "ئ": "[يىئ]",
    "و": "[وؤ]", "ؤ": "[وؤ]",
}  # fmt: skip
# Tashkeel + tatweel: typed or stored, they never decide whether two words are the same.
_MARKS = "ًٌٍَُِّْٰـ"
_MARKS_TABLE = {ord(c): None for c in _MARKS}
# Optional marks may sit after any letter of the STORED text ("مِعطف").
_OPTIONAL_MARKS = f"[{_MARKS}]*"
_REGEX_SPECIAL = set("\\.^$|?*+()[]{}")
# A dash, slash or space typed between parts of a code may or may not be stored.
_SEPARATORS = set("-/ ")
_OPTIONAL_SEPARATOR = "[-/ ]?"


def normalize_digits(term: str) -> str:
    """Arabic-Indic and Persian digits to ASCII, so `R-٠٠٢٩٩٩` finds `R-002999`."""
    return term.translate(_DIGITS)


def arabic_regex(fragment: str) -> str:
    """A POSIX regex matching ``fragment`` under every common Arabic spelling of its letters.

    The result is for ``~*`` (case-insensitive). It is built only from characters we emit
    ourselves: every character of the caller's text is either mapped to one of our fixed
    classes or escaped, so a term can never inject regex syntax.
    """
    cleaned = normalize_digits(fragment).translate(_MARKS_TABLE).strip()
    # "R-002999", "R002999" and "R 002999" are one receipt to the person reading it out, so a code
    # (letters/digits and separators only, no Arabic) tolerates a dash, slash or space between ANY
    # two of its characters. Prose keeps its own spaces: "فستان احمر" must not match "فستاناحمر".
    is_code = bool(cleaned) and all(
        ch.isascii() and (ch.isalnum() or ch in _SEPARATORS) for ch in cleaned
    )
    if is_code:
        cleaned = "".join(ch for ch in cleaned if ch not in _SEPARATORS)
    glue = _OPTIONAL_SEPARATOR if is_code else _OPTIONAL_MARKS
    parts: list[str] = []
    for ch in cleaned:
        if ch in _ARABIC_CLASSES:
            parts.append(_ARABIC_CLASSES[ch])
        elif ch in _REGEX_SPECIAL:
            parts.append("\\" + ch)
        else:
            parts.append(ch)
        parts.append(glue)
    return "".join(parts)
