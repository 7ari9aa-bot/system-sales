"""SI response path (spec §9-10) — validation, safe response.

The model drafts freely; the system validates and, when the draft cannot be
proven, answers deterministically from the findings (§10.4's SAFE RESPONSE —
no third model call).

The allowed-number gate mirrors the customer agent's fact ledger rules
(app.modules.ai.agents.customer.ledger): provenance fields (ids, ISO dates,
URLs) are NOT quotable data — their digit runs would let a hallucinated
"16%" pass because 16 appeared inside a timestamp. Arabic-Indic digits are
folded to Western before matching, and thousands separators / trailing
punctuation are normalized, so a numerically faithful answer passes in any
script or format the model naturally writes.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.modules.analytics.contracts import AnswerDraft, Finding
from app.modules.analytics.numbers import free_numerals
from app.modules.analytics.validators import validate_response

_SAFE_HEADER = "ده اللي البيانات بتقوله دلوقتي:"

# ٠-٩ → 0-9 and the Arabic decimal separator → a dot, so the same number in
# either script is one number to the gate (the customer agent's grounding
# controller applies the identical fold).
_ARABIC_INDIC = str.maketrans(
    {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "٫": ".",
    }
)

#: Provenance-shaped strings carry digit runs that are NOT measurements: a
#: fact id is hex, a period boundary is a date. Same rules as the ledger.
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_IGNORED_KEY_SUFFIXES = ("_id", "_at", "_url", "_token", "_hash")
_IGNORED_KEYS = frozenset(
    {
        "id",
        "uuid",
        "code",
        "period_start",
        "period_end",
        "data_as_of",
        "as_of",
        "timezone",
        "source",
        "attribution_basis",
        "maturity_policy",
    }
)


def _is_provenance_string(value: str) -> bool:
    s = value.strip()
    return bool(_UUID_RE.match(s) or _ISO_DATE_RE.match(s))


def _should_ignore_key(key: str) -> bool:
    k = key.lower()
    if k in _IGNORED_KEYS:
        return True
    return any(k.endswith(suffix) for suffix in _IGNORED_KEY_SUFFIXES)


_MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("يناير", "كانون الثاني", "january", "jan"),
    2: ("فبراير", "شباط", "february", "feb"),
    3: ("مارس", "آذار", "march", "mar"),
    4: ("أبريل", "ابريل", "نيسان", "april", "apr"),
    5: ("مايو", "أيار", "may"),
    6: ("يونيو", "يونية", "حزيران", "june", "jun"),
    7: ("يوليو", "يولية", "تموز", "july", "jul"),
    8: ("أغسطس", "اغسطس", "آب", "august", "aug"),
    9: ("سبتمبر", "أيلول", "september", "sep", "sept"),
    10: ("أكتوبر", "اكتوبر", "تشرين الأول", "october", "oct"),
    11: ("نوفمبر", "تشرين الثاني", "november", "nov"),
    12: ("ديسمبر", "كانون الأول", "december", "dec"),
}
_PERIOD_KEYS = ("period_start", "period_end")
_EVIDENCE_BUCKETS = ("facts", "comparisons", "dimensions", "drivers", "summaries")
_ISO_DATE_IN_TEXT = re.compile(r"(?<![0-9])(\d{4})-(\d{2})-(\d{2})(?:[T ][0-9:.+Zz-]*)?(?![0-9])")


_MIDNIGHT = re.compile(r"[T ]00:00(?::00(?:\.0+)?)?(?:[+-]00:?00|Z|z)?$")


def _is_midnight(value: object) -> bool:
    """True when a period boundary is exactly midnight, or a bare date: an exclusive end."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(_MIDNIGHT.search(text)) or bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text))


def _previous_day(day: tuple[int, int, int]) -> tuple[int, int, int] | None:
    from datetime import date, timedelta

    try:
        prior = date(*day) - timedelta(days=1)
    except ValueError:
        return None
    return (prior.year, prior.month, prior.day)


def recorded_days_from_evidence(evidence: dict) -> set[tuple[int, int, int]]:
    """The days the shop recorded something (the server's own read), as (year, month, day).

    Kept apart from the period boundaries on purpose: a recorded day may be written without its
    year ("the last order was on 17 September"), but it never starts or ends a RANGE, so "from 1
    to 17 September" stays refused unless both ends are measured period boundaries."""
    found: set[tuple[int, int, int]] = set()
    for value in evidence.get("recorded_days") or []:
        match = _ISO_DATE_IN_TEXT.match(value.strip()) if isinstance(value, str) else None
        if match:
            found.add((int(match[1]), int(match[2]), int(match[3])))
    return found


def period_dates_from_evidence(
    evidence: dict, *, boundaries_only: bool = False
) -> set[tuple[int, int, int]]:
    """The calendar days the tools measured: every ``period_start``/``period_end`` they returned.

    Only these keys count. A date the model invents, or one a tool merely mentioned, is not a
    measured boundary and stays subject to the number gate.
    """
    found: set[tuple[int, int, int]] = set()

    def _add(value: object, *, is_end: bool = False) -> None:
        match = _ISO_DATE_IN_TEXT.match(value.strip()) if isinstance(value, str) else None
        if match:
            day = (int(match[1]), int(match[2]), int(match[3]))
            found.add(day)
            if is_end and _is_midnight(value):
                # The tools measure the half-open window [start, end): a period ending at
                # midnight stops BEFORE that day. "The last 14 days" is 1 to 15 November
                # 00:00, and the owner is told "1 to 14 November". The last day actually
                # covered is the one before the exclusive end, so it is a measured boundary.
                previous = _previous_day(day)
                if previous is not None:
                    found.add(previous)

    def _walk(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in _PERIOD_KEYS and isinstance(value, str):
                    _add(value, is_end=key == "period_end")
                else:
                    _walk(value)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                _walk(item)

    for bucket in _EVIDENCE_BUCKETS:
        _walk(evidence.get(bucket))
    # The days the shop recorded something, read once by the server for every answer (a plain list
    # of dates, no counts), so naming the last order never depends on the model having asked.
    if not boundaries_only:
        for day in evidence.get("recorded_days") or []:
            _add(day)
    # The data-status tool reports the first and last day each source was recorded. Those are
    # measured days too ("the last order was on 17 September"). Read ONLY from its own summary
    # shape, so a `first`/`last` key anywhere else never becomes a legal date.
    for summary in [] if boundaries_only else evidence.get("summaries") or []:
        sources = summary.get("sources") if isinstance(summary, dict) else None
        if isinstance(sources, list):
            for row in sources:
                if isinstance(row, dict) and isinstance(row.get("source"), str):
                    _add(row.get("first"))
                    _add(row.get("last"))
        # The customer-activity tool reports when each customer last wrote, read from the
        # messages themselves ("the last contact was on 19 September"). Only a row that names a
        # customer, inside that tool's own `entries` list, counts: the key anywhere else does not.
        entries = summary.get("entries") if isinstance(summary, dict) else None
        if isinstance(entries, list):
            for row in entries:
                if isinstance(row, dict) and isinstance(row.get("customer_id"), str):
                    _add(row.get("last_message_at"))
    return found


def _strip_period_dates(
    folded: str,
    dates: set[tuple[int, int, int]],
    yearless: set[tuple[int, int, int]] | None = None,
    recorded: set[tuple[int, int, int]] | None = None,
) -> str:
    """Remove whole dates that equal a measured period boundary; leave everything else.

    A date is matched as a unit (day, month, year together), so naming a real boundary never
    unlocks its digits elsewhere: "13 October 2026" is legal, a lone "13" still is not.
    """
    if not dates:
        return folded

    def _iso(match: re.Match[str]) -> str:
        key = (int(match[1]), int(match[2]), int(match[3]))
        return " " if key in dates else match[0]

    # A range that shares its month and year: "from 1 to 14 November 2026". Both ends must be
    # measured period boundaries of that same month and year, and any year written must be theirs.
    # It goes first so the lone "1" is never left behind for the single-date form to miss.
    bounds = sorted(yearless or ())
    for year, month, first in bounds:
        for year2, month2, last in bounds:
            if (year, month) != (year2, month2) or first >= last:
                continue
            for name in _MONTH_NAMES[month]:
                pattern = re.compile(
                    rf"(?<![0-9]){first:d}\s*(?:من|لـ?|إلى|الى|لحد|حتى|حتي|to|until|-|–)\s*"
                    rf"{last:d}\s+(?:من\s+)?(?:شهر\s+)?{re.escape(name)}(?![\w])"
                    rf"(?:\s*,?\s*{year}(?![0-9]))?(?!\s*,?\s*[0-9])",
                    re.IGNORECASE,
                )
                folded = pattern.sub(" ", folded)
    out = _ISO_DATE_IN_TEXT.sub(_iso, folded)
    for year, month, day in dates:
        for name in _MONTH_NAMES[month]:
            pattern = re.compile(
                rf"(?<![0-9]){day:d}\s+(?:من\s+)?(?:شهر\s+)?{re.escape(name)}\s*,?\s*{year}(?![0-9])",
                re.IGNORECASE,
            )
            out = pattern.sub(" ", out)
    # A whole day written as digits with its year, "17/9/2026" or "17-09-2026" (day first). Day,
    # month and year must all be a measured day, and no number may touch it.
    for year, month, day in dates:
        full = re.compile(
            rf"(?<![0-9])(?<![0-9][-/.])0?{day:d}\s*[-/]\s*0?{month:d}\s*[-/]\s*{year:d}(?![0-9])"
        )
        out = full.sub(" ", out)
    # The same day written as digits, "15-11" or "15/11" (day first, the way an Egyptian owner
    # writes it). Both numbers must be a measured PERIOD boundary's day and month, and nothing
    # numeric may touch it: "15-11-2025" has another year, "11-15" is the wrong order, "115-11"
    # and "15-112" are other numbers. Only the digits are removed, never a neighbour.
    for _year, month, day in sorted((yearless or set()) | (recorded or set())):
        numeric = re.compile(
            rf"(?<![0-9])(?<![0-9][-/.])0?{day:d}\s*[-/]\s*0?{month:d}(?![0-9])(?!\s*[-/.]\s*[0-9])"
        )
        out = numeric.sub(" ", out)
    # People write a measured period as "from 1 November to 14 November". Accept day + month with
    # no year only when it is a measured PERIOD boundary, and only when no other year follows it
    # (so "1 November 2025" is never read as the boundary of 2026).
    for _year, month, day in sorted((yearless or set()) | (recorded or set())):
        for name in _MONTH_NAMES[month]:
            pattern = re.compile(
                rf"(?<![0-9]){day:d}\s+(?:من\s+)?(?:شهر\s+)?{re.escape(name)}(?![\w])(?!\s*,?\s*[0-9])",
                re.IGNORECASE,
            )
            out = pattern.sub(" ", out)
    return out


_LIST_MARKER = re.compile(r"^([ \t]*)([1-9])([.)])[ \t]+(?=\S)", re.MULTILINE)


def _strip_list_markers(text: str) -> str:
    """Drop the 1. 2. 3. that number a list, so the gate does not read them as measured numbers.

    A marker is only a position, never a measurement, so it must not need a tool to vouch for it.
    The rule is narrow on purpose: a marker is one digit 1-9 at the start of a line followed by a
    dot or a bracket and a space, and a run of them must start at 1 and count up by one with no
    gap. A line that merely starts with a number (a list that began at 3, or a lone "5 ") is left
    as it is, so a real figure can never be hidden by looking like a bullet. A line of ordinary
    text ends a list, so a second list in the same answer starts again from 1.
    """
    out: list[str] = []
    expected = 1
    for line in text.split("\n"):
        m = _LIST_MARKER.match(line)
        if m and int(m.group(2)) == expected:
            out.append(line[: m.start(2)] + line[m.end() :])
            expected += 1
            continue
        if line.strip():
            expected = 1
        out.append(line)
    return "\n".join(out)


def validate_answer(
    text: str,
    allowed_numbers: set[str],
    findings: list[Finding],
    *,
    period_dates: set[tuple[int, int, int]] | None = None,
    yearless_dates: set[tuple[int, int, int]] | None = None,
    recorded_dates: set[tuple[int, int, int]] | None = None,
) -> list[str]:
    """§10.3 v1 — the deterministic gates on the model's answer.

    ``allowed_numbers`` are the digit runs the tools produced (the facts).
    Anything else digit-shaped in the answer is a free number → rejection.
    A hypothesis reaching HIGH is rejected by contract even here.
    Also executes `validate_response` on the synthesized AnswerDraft.
    """
    problems: list[str] = []
    folded = _strip_period_dates(
        text.translate(_ARABIC_INDIC),
        period_dates or set(),
        yearless_dates or set(),
        recorded_dates or set(),
    )
    folded = _strip_list_markers(folded)
    numeric_allowed = _numeric_forms(allowed_numbers)

    def _is_free(numeral: str) -> bool:
        return not _numeral_allowed(numeral, allowed_numbers, numeric_allowed)

    for numeral in free_numerals(folded):
        if _is_free(numeral):
            problems.append(f"free number in answer: {numeral}")
    for finding in findings:
        if finding.type == "HYPOTHESIS" and finding.confidence == "HIGH":
            problems.append("hypothesis reached HIGH confidence")

    # Contract gate: run validate_response to catch unrendered placeholders or free numbers
    draft = AnswerDraft(text=folded, findings=findings)
    for p in validate_response(draft, folded):
        if p.startswith("free number in answer: "):
            num = p.removeprefix("free number in answer: ").strip()
            if not _is_free(num):
                continue
        if p not in problems:
            problems.append(p)
    return problems


def _numeric_forms(allowed: set[str]) -> list[Decimal]:
    """The allowed digit runs as Decimals, for numeric-equality matching.

    "12,500" and "12500.00" are the same measurement in different formats;
    the string gate stays strict, the numeric fallback keeps an honest answer
    from bouncing to the safe response over punctuation alone.
    """
    out: list[Decimal] = []
    for candidate in allowed:
        try:
            out.append(Decimal(candidate.strip(".,%").replace(",", "")))
        except InvalidOperation:
            continue
    return out


def _numeral_allowed(numeral: str, allowed: set[str], numeric_allowed: list[Decimal]) -> bool:
    stripped = numeral.strip(".,%").replace(",", "")
    if numeral in allowed or stripped in allowed:
        return True
    try:
        value = Decimal(stripped)
    except InvalidOperation:
        return False
    return any(value == candidate for candidate in numeric_allowed)


def safe_response(findings: list[Finding], store_facts: dict[str, str]) -> str:
    """§10.4 — fully deterministic: top findings by materiality, rendered
    from evidence with fixed localized strings. No model call involved."""
    if not findings:
        return (
            f"{_SAFE_HEADER} مفيش نتيجة واضحة مدعومة بالبيانات حالياً. "
            "محتاجين فترة أطول أو بيانات إضافية عشان نقدر نحلل بأمان."
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
    lines.append("ملاحظة: ده ملخص آمن من النتايج المحسوبة — اسأل سؤال أدق للتحليل الكامل.")
    _ = store_facts
    return "\n".join(lines)


def allowed_numbers_from_facts(
    facts_payload: list[dict] | dict,
    findings: list[Finding] | None = None,
) -> set[str]:
    """Every digit run the tools and findings produced — the answer's ONLY legal numbers.

    Recursively scans the numeric payloads (fact values, deltas, breakdown
    buckets, driver contributions, summaries, findings statements). Provenance
    fields are excluded: a fact id, a period boundary or a computed-at stamp
    is not a measurement, and letting their digit runs into the allowed set
    is how a fabricated "16%" survives the gate on the back of a timestamp.
    """

    allowed: set[str] = set()

    def _extract_all_numbers(obj: object) -> None:
        if obj is None or isinstance(obj, bool):
            return
        if isinstance(obj, (int, float, Decimal)):
            allowed.update(_digit_runs(str(obj)))
            if isinstance(obj, float):
                allowed.update(_digit_runs(f"{obj:.1f}"))
                allowed.update(_digit_runs(f"{obj:.2f}"))
                allowed.update(_digit_runs(f"{obj:.0f}"))
        elif isinstance(obj, str):
            if not _is_provenance_string(obj):
                allowed.update(_digit_runs(obj))
        elif isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(key, str) and _should_ignore_key(key):
                    continue
                _extract_all_numbers(value)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                _extract_all_numbers(item)

    _extract_all_numbers(facts_payload)

    if findings:
        for f in findings:
            allowed.update(_digit_runs(f.statement))

    return allowed


def _digit_runs(text: str) -> list[str]:
    return re.findall(r"[0-9٠-٩][0-9٠-٩.,%]*", text)
