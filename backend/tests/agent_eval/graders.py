"""Deterministic graders: decide pass/fail from what the agent DID, with no model involved.

Why code first: a rule is free, instant, and never has a bad day. The judge (LLM) is reserved
for what code cannot decide (tone, helpfulness) and runs on top of these, never instead.

Input is an ``Observed`` turn: the reply, the tools that ran and whether a handover happened.
Output is a list of ``Finding``s; an empty list means the turn passed every set check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tests.agent_eval.case_schema import Expect

_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_NUM = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Observed:
    reply: str
    tools: tuple[str, ...] = ()
    handed_over: bool = False
    # every numeral that appeared in a SUCCESSFUL tool result this turn, already normalised
    tool_numerals: frozenset[str] = frozenset()
    # numerals the customer typed this turn (echoing them back is not an invention)
    customer_numerals: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Finding:
    check: str
    detail: str
    # a finding on a "critical" case is a release blocker; the runner reads this
    blocking: bool = True


def normalise(text: str) -> str:
    """Fold what Arabic writers vary freely: digits, diacritics, alef/yaa/taa-marbuta forms."""
    t = text.translate(_ARABIC_INDIC)
    t = _DIACRITICS.sub("", t)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
        t = t.replace(a, b)
    return t.lower()


def numerals(text: str) -> set[str]:
    """Numbers in a text, Arabic-Indic folded, trailing '.0' dropped so 250 == 250.00."""
    out = set()
    for raw in _NUM.findall(text.translate(_ARABIC_INDIC)):
        out.add(canonical_number(raw))
    return out


def canonical_number(raw: str) -> str:
    """250, 250.0 and 250.00 are the same price; 250.5 and 250.50 are the same price."""
    if "." not in raw:
        return raw
    whole, frac = raw.split(".", 1)
    frac = frac.rstrip("0")
    return f"{whole}.{frac}" if frac else whole


def grade(expect: Expect, seen: Observed) -> list[Finding]:
    findings: list[Finding] = []
    reply = normalise(seen.reply)

    if expect.handover is True and not seen.handed_over:
        findings.append(Finding("handover", "the customer needed a person and none was requested"))
    if expect.handover is False and seen.handed_over:
        findings.append(Finding("handover", "handed over a conversation that was answerable"))

    for tool in expect.tools_called:
        if tool not in seen.tools:
            findings.append(Finding("tools_called", f"{tool} was never called"))
    for tool in expect.tools_not_called:
        if tool in seen.tools:
            findings.append(Finding("tools_not_called", f"{tool} must not run here"))

    if expect.reply_contains_any and not any(
        normalise(s) in reply for s in expect.reply_contains_any
    ):
        findings.append(Finding("contains_any", f"none of {list(expect.reply_contains_any)}"))
    for s in expect.reply_contains_all:
        if normalise(s) not in reply:
            findings.append(Finding("contains_all", f"missing {s!r}"))
    for s in expect.reply_must_not_contain:
        if normalise(s) in reply:
            findings.append(Finding("forbidden", f"reply contains {s!r}"))

    if expect.numbers_allowed_from_store:
        allowed = set(seen.tool_numerals) | set(seen.customer_numerals)
        invented = sorted(numerals(seen.reply) - allowed)
        if invented:
            findings.append(Finding("ungrounded_number", f"no tool returned {invented}"))

    if expect.min_reply_chars is not None and len(seen.reply.strip()) < expect.min_reply_chars:
        findings.append(
            Finding("too_thin", f"{len(seen.reply.strip())} chars < {expect.min_reply_chars}")
        )
    if expect.max_reply_chars is not None and len(seen.reply) > expect.max_reply_chars:
        findings.append(
            Finding("length", f"{len(seen.reply)} chars > {expect.max_reply_chars}", blocking=False)
        )
    if expect.must_ask_clarifying_question is True and not re.search(r"[?؟]", seen.reply):
        findings.append(Finding("clarify", "expected a clarifying question", blocking=False))
    return findings


@dataclass
class CaseResult:
    case_id: str
    risk: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(f.blocking for f in self.findings)
