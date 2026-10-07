"""SI response path (spec §9-10) — validation, safe response.

The model drafts freely; the system validates and, when the draft cannot be
proven, answers deterministically from the findings (§10.4's SAFE RESPONSE —
no third model call).
"""

from __future__ import annotations

from app.modules.analytics.contracts import AnswerDraft, Finding
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
    Also executes `validate_response` on the synthesized AnswerDraft.
    """
    problems: list[str] = []
    for numeral in free_numerals(text):
        if numeral not in allowed_numbers and numeral.strip(".,%") not in allowed_numbers:
            problems.append(f"free number in answer: {numeral}")
    for finding in findings:
        if finding.type == "HYPOTHESIS" and finding.confidence == "HIGH":
            problems.append("hypothesis reached HIGH confidence")

    # Contract gate: run validate_response to catch unrendered placeholders or free numbers
    draft = AnswerDraft(text=text, findings=findings)
    for p in validate_response(draft, text):
        if p.startswith("free number in answer: "):
            num = p.removeprefix("free number in answer: ").strip()
            if num in allowed_numbers or num.strip(".,%") in allowed_numbers:
                continue
        if p not in problems:
            problems.append(p)
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
    """Every digit run the tools produced — the answer's ONLY legal numbers.

    Recursively scans all values in the fact payloads (deltas, delta percentages,
    breakdown items, driver contributions, sample sizes, fulfillment rates, money values).
    """
    allowed: set[str] = set()

    def _extract_all_numbers(obj: object) -> None:
        if obj is None:
            return
        if isinstance(obj, (int, float)):
            allowed.update(_digit_runs(str(obj)))
            if isinstance(obj, float):
                allowed.update(_digit_runs(f"{obj:.1f}"))
                allowed.update(_digit_runs(f"{obj:.2f}"))
                allowed.update(_digit_runs(f"{obj:.0f}"))
        elif isinstance(obj, str):
            allowed.update(_digit_runs(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                _extract_all_numbers(v)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                _extract_all_numbers(item)

    for payload in facts_payload:
        _extract_all_numbers(payload)

    return allowed


def _digit_runs(text: str) -> list[str]:
    import re

    return re.findall(r"[0-9٠-٩][0-9٠-٩.,%]*", text)

