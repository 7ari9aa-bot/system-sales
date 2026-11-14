"""Plain shop words for the owner: no internal identifiers in an answer.

The tools need metric names (``refund_amount``) and the model copies them into its replies. The
owner is a shop owner, not an engineer, so every internal name is turned into the shop word here,
after the numbers have been checked and before the answer is saved. A closed table does the
translating; an identifier the table does not know is still never shown raw (it becomes a plain
word), so a metric added later cannot leak. Numbers, dates, links and ordinary words are left alone.
"""

from __future__ import annotations

import re

# internal name -> the word a shop owner uses
KNOWN: dict[str, str] = {
    "orders_placed": "عدد الأوردرات",
    "delivered_revenue": "المبيعات المسلَّمة",
    "shipped_orders": "الأوردرات المشحونة",
    "collected_revenue": "الفلوس المتحصّلة",
    "refund_amount": "المرتجعات",
    "net_revenue": "صافي المبيعات",
    "aov": "متوسط قيمة الأوردر",
    # single words the model also copies next to the Arabic word
    "channels": "القنوات",
    "channel": "القناة",
    "fulfillment": "التوصيل",
    "carrier": "شركة الشحن",
    "governorate": "المحافظة",
}

_SNAKE = re.compile(r"(?<![\w@/.:-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w@/])")
_WORD = re.compile(r"(?<![\w@/.:-])(?:channels?|fulfillment|carrier|governorate|aov)(?![\w@/])")
# "word (internal_name)": the owner already has the word, so the bracket is only noise
_BRACKET = re.compile(r"\s*[(\[（]\s*[`*_]*([a-z][a-z0-9_]*)[`*_]*\s*[)\]）]")
_TICKS = re.compile(r"[`*]+(?=[a-z][a-z0-9_]*[`*]+)|(?<=[a-z0-9])[`*]+(?=\W|$)")
_ARTICLE = re.compile(r"\bال[ـ]\s+(?=[a-z][a-z0-9]*(?:_[a-z0-9]+)+)")
_URL_OR_MAIL = re.compile(r"https?://\S+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")


def _mask(text: str) -> tuple[str, list[str]]:
    """Set links and emails aside so an underscore inside one is never rewritten."""
    keep: list[str] = []

    def _take(m: re.Match[str]) -> str:
        keep.append(m.group(0))
        return f"\u0000{len(keep) - 1}\u0000"

    return _URL_OR_MAIL.sub(_take, text), keep


def _unmask(text: str, keep: list[str]) -> str:
    for i, value in enumerate(keep):
        text = text.replace(f"\u0000{i}\u0000", value)
    return text


def _generic(name: str) -> str:
    # an identifier we have no word for: show its parts as plain words, never the raw name
    return name.replace("_", " ")


def plain_words(text: str | None) -> str:
    """The answer with every internal identifier replaced by a shop word."""
    if text is None or text == "":
        return ""
    out, keep = _mask(str(text))

    def _bracket(m: re.Match[str]) -> str:
        name = m.group(1)
        # a bracket that holds an identifier we know (or any snake_case name) is just noise
        return "" if (name in KNOWN or "_" in name) else m.group(0)

    # "الـ refund_amount": the shop word already carries its own "ال"
    out = _ARTICLE.sub("", out)
    out = _BRACKET.sub(_bracket, out)
    out = _TICKS.sub("", out)
    out = _SNAKE.sub(lambda m: KNOWN.get(m.group(0), _generic(m.group(0))), out)
    out = _WORD.sub(lambda m: KNOWN[m.group(0)], out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+([،,.؟!:])", r"\1", out)
    return _unmask(out, keep)
