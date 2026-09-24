"""AI guardrails — outbound chain and inbound screen (spec §41/§173).

Chain order before ANY outbound AI content:
    schema/validity → policy checks → factual constraints (tool results)
    → PII leakage → brand/tone → channel policy → approval gate

`screen_inbound` is the mirror image: what a run is ABOUT to show the model,
judged before it is shown. The outbound chain cannot cover that — it only ever
sees what came back.

A guardrail verdict is either ALLOW or BLOCK(+reason) or HANDOVER. Tool
authorization answers "may the AI act?"; guardrails answer "may this text be
sent?" — both are required.

Lives in `app/core` rather than `app/modules/ai` because §173 requires the
check to be enforced at the boundary that actually inserts an outbound message
(`conversations.service.add_message`), not only inside the AI runner. `ai`
already imports `conversations`, so a `conversations -> ai` import would close
an import cycle. The chain is pure (regex + dataclasses, no models, no session),
so it belongs in core anyway — both modules may depend on it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

# Invisible joiners and compatibility forms are the cheapest way past a literal
# marker, so every pattern below is matched against `_screened()` output — one
# normalised view for the whole chain.
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)


# Beyond the zero-width set: the bidi isolates and embeds a paste carries, and
# tatweel (U+0640), Arabic's visual extender — it stretches a word and changes
# its spelling to no one but a pattern matcher.
_BIDI_AND_FILLER = dict.fromkeys(
    [
        0x200E, 0x200F,
        0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
        0x2066, 0x2067, 0x2068, 0x2069,
        0x0640,
    ],
    None,
)
# Harakat are not compatibility decompositions, so NFKC leaves the vowel marks
# that spell one Arabic word two ways (the imperative with a kasra, the same
# word typed without).
_ARABIC_MARKS = dict.fromkeys([*range(0x064B, 0x0653), 0x0670], None)
# Every keyboard's spelling of one letter, folded onto one: the four hamza
# carriers onto bare alef, the two forms of ya and the ta marbuta onto ha, and
# the hamza-bearing waw/ya onto their plain letters.
_ARABIC_LETTERS = {
    0x0623: 0x0627,  # أ
    0x0625: 0x0627,  # إ
    0x0622: 0x0627,  # آ
    0x0671: 0x0627,  # ٱ
    0x0649: 0x064A,  # ى -> ي
    0x0629: 0x0647,  # ة -> ه
    0x0624: 0x0648,  # ؤ -> و
    0x0626: 0x064A,  # ئ -> ي
}


def _screened(content: str) -> str:
    """Fold, strip and caseless the text the way every check reads it."""
    folded = (
        unicodedata.normalize("NFKC", content)
        .translate(_ZERO_WIDTH)
        .translate(_BIDI_AND_FILLER)
        .translate(_ARABIC_MARKS)
        .translate(_ARABIC_LETTERS)
    )
    return re.sub(r"\s+", " ", folded).casefold().strip()


# Patterns that must never leak from internal context into customer messages.
# `supplier/internal/wholesale cost|price` and `profit margin` are internal
# vocabulary in any spelling a human would type, so they block on sight. A bare
# `margin` is ordinary English ("a margin of error", "30 day margin") and only
# leaks when it carries the figure, so it blocks next to a percentage or an
# amount — blocking the word itself produced false positives on every delivery
# estimate while "our internal cost is 40" (typed with a space) walked free.
_MONEY = (
    r"(?:%|٪|percent|[\d,.]+\s*"
    r"(?:egp|sar|aed|usd|eur|جنيه|ريال|درهم|دولار|يورو))"
)
_PII_PATTERNS = [
    (re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), "card_number"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ssn_like"),
    (re.compile(r"sk-[a-z0-9]{20,}"), "api_key"),
    (
        re.compile(
            r"\b(?:internal|supplier|wholesale)\s*[-_]?\s*(?:cost|price)\b"
            r"|\bprofit\s*[-_]?\s*margin\b"
        ),
        "internal_margin",
    ),
    (
        re.compile(
            rf"\b(?:margin|markup)s?\b[^.\n]{{0,12}}?{_MONEY}|{_MONEY}[^.\n]{{0,12}}?"
            rf"\b(?:margin|markup)s?\b"
        ),
        "internal_margin",
    ),
]


# Two verb classes, because they are not equally ordinary. `ignore`, `disregard`
# and `bypass` in front of a rule word are a configuration phrase no one types by
# accident; `override`, `forget` and `skip` are business English around
# promotions and discounts, so they need the stronger target to count.
_INJ_VERB_STRONG = r"(?:ignore|disregard|bypass|disobey)"
_INJ_VERB_WEAK = r"(?:override|forget|discard|skip)"
# The determiner slot is not just "the/all": the classic phrasing names whose
# instructions they are — "forget YOUR instructions" — and a list without the
# possessives let the most idiomatic attempt of all walk straight through.
_INJ_QUALIFIER = (
    r"(?:(?:all|any|every|the|these|those|your|my|our|their|its)\s+)*"
)
_INJ_SCOPE = r"(?:(?:previous|prior|above|earlier|preceding|original|initial|system)\s+)*"
_INJ_NOUN = r"(?:instructions?|rules?|prompts?|guidelines?|directives?)"
_INJ_NOUN_OWN = r"(?:instructions?|prompts?|guidelines?|directives?)"
# The Arabic verbs and nouns below are written in FOLDED spelling, because that
# is what `_screened` hands them: after the fold, الغى and الغي are one string,
# and إرشادات and ارشادات are one string, so a pattern must not carry both.
_INJ_AR_VERB = r"(?:تجاهل|تجاوز|تخطي|انسي|نساي|الغي|الغ)"
# `نظام` ("system", but also a plan: نظام الفاتورة, the billing plan) and
# `قواعد` ("rules", but also a school subject: قواعد اللغة, grammar) are ordinary
# nouns in this dialect. An override verb two words from either is not evidence
# of an attempt, so they only count inside the phrase that points at the
# system's own rules.
_INJ_AR_NOUN = r"(?:تعليمات|ارشادات)"
_INJ_AR_RULES_PHRASE = (
    r"(?:(?:تعليمات|ارشادات|قواعد)\s*(?:النظام|السابق|الاصلي|الاول)"
    r"|(?:كل|جميع)\s*(?:ال)?قواعد)"
)

_INJECTION_PATTERNS = [
    # "ignore/disregard (all) (previous) instructions|rules|..." — the qualifier
    # and scope words are optional so "disregard all rules" and
    # "ignore the previous instructions" are the same attempt.
    re.compile(rf"\b{_INJ_VERB_STRONG}\s+{_INJ_QUALIFIER}{_INJ_SCOPE}{_INJ_NOUN}\b"),
    # The softer verbs only read as an attempt when the target is the run's own
    # instructions or prompt — not any rule the sentence happens to mention.
    re.compile(rf"\b{_INJ_VERB_WEAK}\s+{_INJ_QUALIFIER}{_INJ_SCOPE}{_INJ_NOUN_OWN}\b"),
    re.compile(
        r"\b(?:reveal|show|print|repeat|output|display|paste|leak|dump)\b"
        r"[^.\n]{0,20}?\b(?:system\s+prompt|your\s+(?:instructions?|rules?|prompts?))\b"
    ),
    re.compile(r"\bsystem\s+prompt\s*:"),
    # Arabic: an override verb near the word for instructions, or the phrase
    # "the system's rules" / "all the rules" wherever it appears.
    re.compile(rf"{_INJ_AR_VERB}[^.\n]{{0,25}}?{_INJ_AR_NOUN}"),
    re.compile(_INJ_AR_RULES_PHRASE),
]


@dataclass
class GuardrailVerdict:
    decision: str  # allow | block | handover
    reason: str | None = None
    checks: list[str] = field(default_factory=list)


class OutputGuardrail:
    """Configurable chain. Each check returns None (pass) or a verdict."""

    def __init__(self) -> None:
        self._checks: list[tuple[str, Callable[[str, dict], GuardrailVerdict | None]]] = []

    def add_check(
        self, name: str, fn: Callable[[str, dict], GuardrailVerdict | None]
    ) -> OutputGuardrail:
        self._checks.append((name, fn))
        return self

    def evaluate(self, content: str, context: dict) -> GuardrailVerdict:
        checks_run: list[str] = []
        for name, fn in self._checks:
            checks_run.append(name)
            verdict = fn(content, context)
            if verdict is not None and verdict.decision != "allow":
                verdict.checks = checks_run
                return verdict
        return GuardrailVerdict(decision="allow", checks=checks_run)


def _validity(content: str, ctx: dict) -> GuardrailVerdict | None:
    if not content or not content.strip():
        return GuardrailVerdict(decision="block", reason="empty content")
    return None


def _pii(content: str, ctx: dict) -> GuardrailVerdict | None:
    screened = _screened(content)
    for pattern, label in _PII_PATTERNS:
        if pattern.search(screened):
            return GuardrailVerdict(decision="block", reason=f"pii_leak:{label}")
    return None


def _injection_risk(content: str, ctx: dict) -> GuardrailVerdict | None:
    screened = _screened(content)
    if any(pattern.search(screened) for pattern in _INJECTION_PATTERNS):
        return GuardrailVerdict(decision="handover", reason="injection_risk")
    return None


_CROSS_TENANT_MARKERS = (
    "تينانت تاني",  # another tenant
    "تينانت تانى",
    "tenant آخر",
    "another tenant",
    "other tenant",
    "different tenant",
    "cross-tenant",
)


def _cross_tenant_request(content: str, ctx: dict) -> GuardrailVerdict | None:
    # §115/§132: an explicit request for ANOTHER tenant's data is an access
    # attempt, not a question. Server-side tool scoping is the enforcement; this
    # catches the phrasing so the attempt is handed to a human instead of being
    # answered with a refusal the model may talk its way around.
    screened = _screened(content)
    if any(marker in screened for marker in _CROSS_TENANT_MARKERS):
        return GuardrailVerdict(decision="handover", reason="cross_tenant_request")
    return None


# A price, a stock level or a discount is only as good as the record behind it.
# Narrow on purpose — "the widget is in stock." with no figure makes no claim a
# number can contradict, and withholding it would be the false positive again.
_FACT_CLAIM = re.compile(
    r"(?:"
    r"(?:price|cost|total|amount|discount|stock|availability|quantity)\D{0,12}\d"
    rf"|{_MONEY}"
    r"|(?:سعر|ثمن|تكلفة|متوفر|متوفرين|بكم|كم)\D{0,12}\d"
    r")"
)


def claims_facts(text: str) -> bool:
    """True when the text asserts a figure the run should be able to source."""
    return bool(_FACT_CLAIM.search(_screened(text)))


def default_guardrail(*, require_tool_evidence: bool = False) -> OutputGuardrail:
    """Production-default chain.

    `require_tool_evidence` is off by default because it needs the run's tool
    results, which only the AI runner has — the outbound-message boundary has no
    run to look at. The runner turns it on: without a caller passing
    `tool_results`, the factual constraint could never fire and §41's chain was
    four checks with a fifth comment beside them.
    """
    chain = OutputGuardrail()

    def _tool_evidence(content: str, ctx: dict) -> GuardrailVerdict | None:
        # Factual constraint: price/stock claims must come from tool results.
        if not require_tool_evidence:
            return None
        claimed = ctx.get("claims_facts", claims_facts(content))
        if claimed and not ctx.get("tool_results"):
            return GuardrailVerdict(decision="handover", reason="unsourced_claim")
        return None

    chain.add_check("validity", _validity)
    chain.add_check("pii", _pii)
    chain.add_check("injection_echo", _injection_risk)
    chain.add_check("cross_tenant", _cross_tenant_request)
    chain.add_check("tool_evidence", _tool_evidence)
    return chain


# What a provider must never be shown, before it is shown. The output chain
# cannot cover this: it only ever sees what came back.
_INBOUND_CHAIN = (
    OutputGuardrail()
    .add_check("injection_risk", _injection_risk)
    .add_check("cross_tenant", _cross_tenant_request)
)


def screen_inbound(text: str) -> GuardrailVerdict:
    """Judge the content a run is ABOUT to put in front of the model.

    Empty or ordinary customer prose always allows — refusing a customer for
    typing is worse than answering them. Only the two attempts that are
    questions-in-disguise (instruction override, another tenant's data) hand
    over, and nothing about a run is needed to spot them.
    """
    if not text or not text.strip():
        return GuardrailVerdict(decision="allow", checks=[])
    return _INBOUND_CHAIN.evaluate(text, {})



# The sender types whose content is AI-authored and must pass the chain. A human
# agent's own words are their responsibility; a `system` notice is not customer
# prose.
AI_SENDER_TYPES: frozenset[str] = frozenset({"ai"})
