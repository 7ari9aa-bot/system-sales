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
from decimal import Decimal, InvalidOperation

# Invisible joiners and compatibility forms are the cheapest way past a literal
# marker, so every pattern below is matched against `_screened()` output — one
# normalised view for the whole chain.
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)


# Beyond the zero-width set: the bidi isolates and embeds a paste carries, and
# tatweel (U+0640), Arabic's visual extender — it stretches a word and changes
# its spelling to no one but a pattern matcher.
_BIDI_AND_FILLER = dict.fromkeys(
    [
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
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
_INJ_QUALIFIER = r"(?:(?:all|any|every|the|these|those|your|my|our|their|its)\s+)*"
_INJ_SCOPE = r"(?:(?:previous|prior|above|earlier|preceding|original|initial|system)\s+)*"
_INJ_NOUN = r"(?:instructions?|rules?|prompts?|guidelines?|directives?)"
_INJ_NOUN_OWN = r"(?:instructions?|prompts?|guidelines?|directives?)"
# The Arabic verbs and nouns below are written in FOLDED spelling, because that
# is what `_screened` hands them: after the fold, الغى and الغي are one string,
# and إرشادات and ارشادات are one string, so a pattern must not carry both.
_INJ_AR_VERB = r"(?:تجاهل|تجاوز|تخطي|انسي|نساي|الغي|الغ)"
_INJ_AR_QUALIFIER = r"(?:(?:كل|جميع|اي|هذه|هذي|تلك)\s+)*"
_INJ_AR_SCOPE = r"(?:(?:السابقه|السابق|الاصليه|الاولى|الاول|الحاليه)\s+)*"
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
    # Arabic: an override verb directly targeting instructions/guidelines,
    # or the phrase "the system's rules" / "all the rules" wherever it appears.
    # P1-13: Requires direct collocation with qualifiers/scope so legitimate customer
    # requests like "الغي الطلب وابعتلي تعليمات الاسترجاع" do not trigger false positives.
    re.compile(rf"{_INJ_AR_VERB}\s+{_INJ_AR_QUALIFIER}{_INJ_AR_SCOPE}(?:ال)?{_INJ_AR_NOUN}"),
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


# The markers above are the words of a developer ("another tenant"). A shop owner or a customer
# asks the same thing in the words they use every day: "show me the OTHER SHOP's data". A shop,
# a store, an account and a company are all a tenant to them. The phrase is only an attempt when
# THREE things are in one request, because each alone is ordinary:
#   * a verb that asks to be shown something  (show, give, bring me ...)
#   * a thing that is data                     (data, sales, orders, customers, invoices ...)
#   * a business that is not theirs            (the other shop, another store, a different account)
# "Is the other branch open?" has the third and not the first two; "show me my store data" has the
# first two and not the third. Both must keep passing, so a lone word never blocks.
# Written in FOLDED spelling (see `_screened`): no hamza, ta marbuta as ha, ya for alef maqsura.
_XT_ASK_AR = (
    r"(?:ورين[يا]|وريني|اعرض(?:لي)?|هات(?:لي)?|اديني|عايز(?:ه)?\s+اشوف|ابعتلي|طلعلي|اظهر(?:لي)?)"
)
_XT_ASK_EN = r"(?:show|give|get|bring|send|list|display|pull|export|fetch|share)"
_XT_DATA_AR = r"(?:بيانات|مبيعات|اوردرات|طلبات|عملاء|فواتير|ارباح|مصاريف|مخزون|ارقام|تقارير|حسابات)"
_XT_DATA_EN = (
    r"(?:data|sales|orders|customers|clients|invoices|revenue|profits?|expenses|inventory"
    r"|stock|reports?|numbers|figures|records)"
)
_XT_BUSINESS_AR = r"(?:محل|محلات|متجر|متاجر|حساب|شركه|شركات|مطعم|فرع)"
_XT_OTHER_AR = r"(?:تاني|تانيه|تانيين|اخر|اخري|اخرى|مختلف|غير\s+محلي|باقي|بقيه)"
_XT_OTHER_EN = r"(?:another|other|different|else'?s?|someone\s+else'?s?|competitor'?s?)"
_XT_BUSINESS_EN = (
    r"(?:shops?|stores?|merchants?|accounts?|compan(?:y|ies)|businesses|business|tenants?)"
)

# The same words are what an honest REFUSAL says: "I can't show you another shop's data". The check
# also reads the assistant's own replies, and blocking the refusal would hide the correct answer.
# So a request that sits behind a negation or an inability is the speaker describing a limit, not
# someone asking: the verb is not the first thing said in its clause.
_XT_REFUSAL_AR = (
    r"(?:"
    # "I can't / won't be able to": مقدرش، مش هقدر، ما اقدر، لن استطيع، مش بقدر
    r"(?:(?:ما|م|مش|لا|لن)\s*(?:اقدر|هقدر|بقدر|استطيع|اسمح|هسمح|بسمح)\w*|مقدر\w*|مسمح\w*)"
    # "it is not allowed": ممنوع، مينفعش، مش مسموح، غير مسموح، مش من حقي
    r"|ممنوع|مينفعش|ما\s*ينفعش|مش\s*ينفع|(?:مش|غير)\s*(?:مسموح|مصرح|متاح)|مش\s*من\s*حقي"
    r")"
)
_XT_REFUSAL_EN = (
    r"(?:cannot|can'?t|won'?t|unable\s+to|not\s+able\s+to|not\s+allowed\s+to|"
    r"i\s+only|only|never|don'?t|do\s+not|am\s+not\s+allowed\s+to)"
)
_REFUSAL_RE = re.compile(rf"(?:{_XT_REFUSAL_AR}|{_XT_REFUSAL_EN})")


_CROSS_TENANT_PATTERNS = [
    # "ورّيني بيانات المحل التاني" / "اعرض لي مبيعات متجر آخر" / "هات عملاء محل تاني"
    re.compile(
        rf"{_XT_ASK_AR}\b.{{0,40}}?{_XT_DATA_AR}\b.{{0,25}}?"
        rf"(?:(?:ال)?{_XT_BUSINESS_AR}\s+(?:ال)?{_XT_OTHER_AR}|{_XT_OTHER_AR}\s+(?:ال)?{_XT_BUSINESS_AR})"
    ),
    # the owner's own wording puts the business first: "هات لي عملاء محل تاني"
    re.compile(
        rf"{_XT_ASK_AR}\b.{{0,40}}?(?:ال)?{_XT_BUSINESS_AR}\s+(?:ال)?{_XT_OTHER_AR}"
        rf"\b.{{0,25}}?{_XT_DATA_AR}"
    ),
    # "show me another store's orders" / "give me the customers of a different shop"
    re.compile(
        rf"\b{_XT_ASK_EN}\b.{{0,40}}?{_XT_OTHER_EN}\s+{_XT_BUSINESS_EN}\b.{{0,25}}?{_XT_DATA_EN}\b"
    ),
    re.compile(
        rf"\b{_XT_ASK_EN}\b.{{0,40}}?{_XT_DATA_EN}\b.{{0,25}}?"
        rf"(?:of|from|for|at)\s+(?:an?\s+|the\s+)?{_XT_OTHER_EN}\s+{_XT_BUSINESS_EN}\b"
    ),
    # the whole set at once: "بيانات المحلات التانية كلها" / "اديني بيانات باقي المحلات"
    re.compile(rf"{_XT_DATA_AR}\b.{{0,15}}?(?:ال)?(?:محلات|متاجر|شركات)\s+(?:ال)?{_XT_OTHER_AR}"),
    re.compile(rf"{_XT_DATA_AR}\b.{{0,15}}?(?:باقي|بقيه)\s+(?:ال)?(?:محلات|متاجر|شركات|عملاء)"),
]


def _is_declined(lead: str) -> bool:
    """Is the request that follows `lead` being declined rather than made?

    `lead` is what the same sentence said before the verb. A decline puts its limit word right
    against the verb ("مقدرش اعرض بيانات ...", "I can't show ..."). A word in between breaks it:
    "ممنوع التأخير ورّيني ..." is an order that happens to start with a negative word, and an
    attacker can write exactly that, so only the last one or two words before the verb are read.
    """
    words = lead.split()
    return any(_REFUSAL_RE.fullmatch(" ".join(words[-n:])) for n in (1, 2) if len(words) >= n)


def _cross_tenant_request(content: str, ctx: dict) -> GuardrailVerdict | None:
    # §115/§132: an explicit request for ANOTHER tenant's data is an access
    # attempt, not a question. Server-side tool scoping is the enforcement; this
    # catches the phrasing so the attempt is handed to a human instead of being
    # answered with a refusal the model may talk its way around.
    screened = _screened(content)
    if any(marker in screened for marker in _CROSS_TENANT_MARKERS):
        return GuardrailVerdict(decision="handover", reason="cross_tenant_request")
    for pattern in _CROSS_TENANT_PATTERNS:
        for hit in pattern.finditer(screened):
            # what comes before the verb in its own sentence decides if it is asked or declined
            lead = re.split(r"[.!?؟،,;\n]", screened[: hit.start()])[-1]
            if not _is_declined(lead):
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


def _numerals(text: str) -> set[Decimal]:
    """Every number in `text`, as a Decimal so they compare NUMERICALLY.

    The tools return money in the two-decimal form the schema stores ("120.00")
    while the model says "120", and the customer agent answers in Arabic so the
    figure may be Arabic-Indic ("١٢٠"). As strings none of those intersect, and
    a price that WAS sourced got handed to a human — the customer's answer
    silently withheld by the check that exists to protect it.
    """
    found: set[Decimal] = set()
    for raw in re.findall(r"\d+(?:\.\d+)?", text):
        try:
            found.add(Decimal(raw))
        except InvalidOperation:
            continue
    return found


def claim_checks(content: str, ctx: dict) -> GuardrailVerdict | None:
    """V12 §26: Generated commercial claims verified against authoritative evidence.
    No evidence -> BLOCK.
    """
    if claims_facts(content):
        evidence_present = bool(
            ctx.get("evidence_set_id")
            or ctx.get("verified_facts")
            or ctx.get("evidence_facts")
            or ctx.get("tool_results")
        )
        if not evidence_present:
            return GuardrailVerdict(decision="block", reason="unverified_commercial_claim")
    return None


def default_guardrail(
    *, require_tool_evidence: bool = False, require_claim_check: bool = False
) -> OutputGuardrail:
    """Production-default chain.

    `require_tool_evidence` is off by default because it needs the run's tool
    results, which only the AI runner has — the outbound-message boundary has no
    run to look at. The runner turns it on: without a caller passing
    `tool_results`, the factual constraint could never fire and §41's chain was
    four checks with a fifth comment beside them.

    `require_claim_check` (V12 §26): when enabled, commercial claims asserting
    prices/stock without verifiable evidence are strictly BLOCKED.
    """
    chain = OutputGuardrail()

    def _claim_checks_gate(content: str, ctx: dict) -> GuardrailVerdict | None:
        if not require_claim_check and not ctx.get("require_claim_check", False):
            return None
        return claim_checks(content, ctx)

    def _tool_evidence(content: str, ctx: dict) -> GuardrailVerdict | None:
        # P1-12: Factual constraint — price/stock claims must come from tool
        # results AND the claimed numerals must actually appear in those results.
        # Previously any tool call (even an unrelated one like get_customer)
        # greenlighted a hallucinated price claim.
        if not require_tool_evidence:
            return None
        claimed = ctx.get("claims_facts", claims_facts(content))
        if not claimed:
            return None
        tool_results = ctx.get("tool_results")
        if not tool_results:
            return GuardrailVerdict(decision="handover", reason="unsourced_claim")
        # `_FACT_CLAIM` also fires on a bare "%"/"percent", so a claim can carry
        # no numeral at all. This check's job is to source the NUMBERS in the
        # answer; with none there is nothing to compare and nothing to withhold.
        content_nums = _numerals(_screened(content))
        if not content_nums:
            return None
        tool_text = str(tool_results) if not isinstance(tool_results, str) else tool_results
        # At least one claimed numeral must be sourced from a tool result.
        if not content_nums & _numerals(tool_text):
            return GuardrailVerdict(decision="handover", reason="unsourced_claim")
        return None

    chain.add_check("validity", _validity)
    chain.add_check("pii", _pii)
    chain.add_check("injection_echo", _injection_risk)
    chain.add_check("cross_tenant", _cross_tenant_request)
    chain.add_check("claim_checks", _claim_checks_gate)
    chain.add_check("tool_evidence", _tool_evidence)
    return chain


def _analytics_pii(content: str, ctx: dict) -> GuardrailVerdict | None:
    screened = _screened(content)
    for pattern, label in _PII_PATTERNS:
        if label == "internal_margin":
            continue
        if pattern.search(screened):
            return GuardrailVerdict(decision="block", reason=f"pii_leak:{label}")
    return None


def analytics_guardrail() -> OutputGuardrail:
    """Specialized guardrail for analytics / business intelligence agents.

    Permits internal metrics/margins (essential for merchant reporting), but
    enforces schema validity, sensitive PII (cards, SSN, API keys), prompt
    injection echo, and cross-tenant leakage.
    """
    chain = OutputGuardrail()
    chain.add_check("validity", _validity)
    chain.add_check("pii", _analytics_pii)
    chain.add_check("injection_echo", _injection_risk)
    chain.add_check("cross_tenant", _cross_tenant_request)
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
