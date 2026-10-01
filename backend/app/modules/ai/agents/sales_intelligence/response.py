"""SI response path (spec §9-10) — validation, safe response.

The model drafts freely; the system validates and, when the draft cannot be
proven, answers deterministically from the findings (§10.4's SAFE RESPONSE —
no third model call).
"""

from __future__ import annotations

from app.modules.analytics.contracts import Finding
from app.modules.analytics.numbers import free_numerals
from app.modules.analytics.validators import validate_response

_SAFE_HEADER = "ده اللي البيانات بتقوله دلوقتي:"


def validate_answer(
    text: str,
    allowed_numbers: set[str],
    findings: list[Finding],
) -> list[str]:
    """§10.3 v1 — the deterministic gates on the model's answer.

    ``allowed_numbers`` are the digit runs the tools produced (the facts).
    Anything else digit-shaped in the answer is a free number → rejection.
    A hypothesis reaching HIGH is rejected by contract even here.
    """
    problems: list[str] = []
    for numeral in free_numerals(text):
        if numeral not in allowed_numbers and numeral.strip(".,%") not in allowed_numbers:
            problems.append(f"free number in answer: {numeral}")
    for finding in findings:
        if finding.type == "HYPOTHESIS" and finding.confidence == "HIGH":
            problems.append("hypothesis reached HIGH confidence")
    _ = validate_response  # the fuller placeholder gate joins when the model
    # starts DRAFTING with {{fact:fmt}} tokens (Phase 9's render path).
    return problems


def safe_response(findings: list[Finding], store_facts: dict[str, str]) -> str:
    """§10.4 — fully deterministic: top findings by materiality, rendered
    from evidence with fixed localized strings. No model call involved."""
    if not findings:
        return (
            f"{_SAFE_HEADER} مفيش نتيجة واضحة مدعومة بالبيانات حالياً. "
            "محتاجين فترة أطول أو بيانات إضافية عشان نقدر نحليل آمن."
        )
    lines = [_SAFE_HEADER]
    for index, finding in enumerate(findings, start=1):
        lines.append(f"{index}. {finding.statement}")
        if finding.confidence != "HIGH":
            lines.append(
                f"   (الثقة: {finding.confidence} — "
                + "؛ ".join(finding.confidence_reasons[:2])
                + ")"
            )
    lines.append(
        "ملاحظة: ده ملخص آمن من النتايج المحسوبة — اسأل سؤال أدق للتحليل الكامل."
    )
    _ = store_facts
    return "\n".join(lines)


def allowed_numbers_from_facts(facts_payload: list[dict]) -> set[str]:
    """Every digit run the tools produced — the answer's ONLY legal numbers."""
    allowed: set[str] = set()
    for payload in facts_payload:
        value = str(payload.get("value", ""))
        allowed |= {run for run in _digit_runs(value)}
    return allowed


def _digit_runs(text: str) -> list[str]:
    import re

    return re.findall(r"[0-9٠-٩][0-9٠-٩.,%]*", text)

