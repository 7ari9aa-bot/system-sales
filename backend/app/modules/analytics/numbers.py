"""Number policy and placeholder rendering (spec §10.1-10.2).

Anti-hallucination, mechanically enforced: a measured number in the answer
appears ONLY as a placeholder bound to a fact id (``{{F3:money}}``), and the
SYSTEM renders it — locale, currency, digit script, separators, rounding.
The model proposes sentences; the system owns the digits.

Linguistic numbers ("يومين", "موديلين") are allowed only through the
non-measuring allowlist — they count nothing. Direction checks (rose vs
fell against the fact's sign) live with the response validator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.modules.analytics.contracts import MetricFact

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_]+):([a-z_]+)\}\}")

_DIGIT_SCRIPTS = {
    "latin": "0123456789",
    "arabic_indic": "٠١٢٣٤٥٦٧٨٩",
}

_FORMATS = frozenset(
    {"int", "money", "pct", "pct_points", "date", "date_range", "delta_money",
     "delta_pct", "count"}
)

#: Non-measuring expressions that may contain number WORDS without a fact.
#: Counting expressions ("3 قطع") are NOT here — those need a fact.
LINGUISTIC_ALLOWLIST = ("يومين", "موديلين", "أول", "أسبوعين", "شهرين", "نص")


@dataclass(frozen=True, slots=True)
class NumberPolicy:
    currency: str = "EGP"
    digit_script: str = "latin"  # "latin" | "arabic_indic"
    pct_decimals: int = 1
    money_decimals: int = 0  # EGP answers read naturally whole
    version: str = "v1"


def _script_convert(text: str, policy: NumberPolicy) -> str:
    table = str.maketrans(_DIGIT_SCRIPTS["latin"], _DIGIT_SCRIPTS[policy.digit_script])
    return text.translate(table)


def _money(value: Decimal, policy: NumberPolicy) -> str:
    quantized = value.quantize(Decimal(1).scaleb(-policy.money_decimals), ROUND_HALF_UP)
    whole = f"{quantized:,.{policy.money_decimals}f}"
    return f"{whole} {policy.currency}"


def render_placeholder(token: str, fmt: str, fact: MetricFact, policy: NumberPolicy) -> str:
    """Render one placeholder against its fact. Unknown format → KeyError by
    contract: the validator treats that as a rejected draft, never silence."""
    if fmt not in _FORMATS:
        raise ValueError(f"unknown number format: {fmt}")
    value = fact.value

    if fmt in ("int", "count"):
        text = f"{int(value):,}"
    elif fmt == "money":
        text = _money(value, policy)
    elif fmt == "delta_money":
        sign = "+" if value >= 0 else "−"
        text = f"{sign}{_money(abs(value), policy)}"
    elif fmt in ("pct", "delta_pct"):
        quantized = value.quantize(Decimal(1).scaleb(-policy.pct_decimals), ROUND_HALF_UP)
        sign = "+" if (fmt == "delta_pct" and value >= 0) else ""
        if fmt == "delta_pct" and value < 0:
            sign = "−"
        text = f"{sign}{abs(quantized):,.{policy.pct_decimals}f}%"
    elif fmt == "pct_points":
        quantized = value.quantize(Decimal(1).scaleb(-policy.pct_decimals), ROUND_HALF_UP)
        text = f"{quantized:,.{policy.pct_decimals}f} نقطة مئوية"
    elif fmt == "date":
        text = fact.period.start.date().isoformat()
    elif fmt == "date_range":
        text = (
            f"{fact.period.start.date().isoformat()} → "
            f"{fact.period.end.date().isoformat()}"
        )
    else:  # pragma: no cover — _FORMATS membership guarantees the rest
        raise ValueError(f"unhandled format: {fmt}")
    return _script_convert(text, policy)


def render_answer(
    text: str, facts_by_id: dict[str, MetricFact], policy: NumberPolicy | None = None
) -> tuple[str, list[str]]:
    """Render every placeholder in the draft; return (rendered, problems).

    Problems are the validator's input: unknown fact id, unknown format, or
    a placeholder left over because its fact was missing. The render NEVER
    invents a number to fill a hole.
    """
    policy = policy or NumberPolicy()
    problems: list[str] = []

    def _replace(match: re.Match) -> str:
        fact_id, fmt = match.group(1), match.group(2)
        fact = facts_by_id.get(fact_id)
        if fact is None:
            problems.append(f"unresolved placeholder: {match.group(0)} (no fact {fact_id})")
            return match.group(0)
        try:
            return render_placeholder(match.group(0), fmt, fact, policy)
        except ValueError as exc:
            problems.append(str(exc))
            return match.group(0)

    rendered = _PLACEHOLDER_RE.sub(_replace, text)
    return rendered, problems


def free_numerals(
    rendered_text: str, allowlist: tuple[str, ...] = LINGUISTIC_ALLOWLIST
) -> list[str]:
    """Numerals left in the text that no placeholder accounted for.

    Runs AFTER rendering: any digit sequence the renderer did not produce is
    a free number the model slipped in. Number WORDS on the allowlist
    ("يومين") are linguistic, not measuring. Returns the offending strings.
    """
    cleaned = rendered_text
    for token in allowlist:
        cleaned = cleaned.replace(token, "")
    digit_runs = re.findall(r"[0-9٠-٩][0-9٠-٩.,%]*", cleaned)
    return [run for run in digit_runs if run not in (".", ",", "%")]
