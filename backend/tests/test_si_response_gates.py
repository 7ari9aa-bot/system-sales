"""SI response gates (pure, no DB) — the answer's number gate and rendering.

Pins the ways an HONEST answer used to bounce to the safe response
(Arabic-Indic digits, thousands separators, an unstatable window) and the
ways a DISHONEST one used to pass (digit runs leaked from fact ids and
timestamps).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.modules.ai.agents.sales_intelligence.response import (
    allowed_numbers_from_facts,
    safe_response,
    validate_answer,
)
from app.modules.ai.chat.turns import build_structured_blocks


def _fact_payload(**overrides) -> dict:
    base = {
        "metric": "revenue",
        "value": "1250.00",
        "unit": "EGP",
        "filters": {},
    }
    base.update(overrides)
    return base


def test_arabic_indic_numerals_are_grounded():
    allowed = allowed_numbers_from_facts([_fact_payload()])
    assert validate_answer("الإيراد ١٢٥٠ جنيه", allowed, []) == []


def test_arabic_indic_free_number_still_rejected():
    allowed = allowed_numbers_from_facts([_fact_payload()])
    assert validate_answer("الإيراد ٩٩ جنيه", allowed, []) != []


def test_provenance_digits_do_not_become_allowed():
    # 16 and 2026 exist ONLY inside the id and the period/computed stamps —
    # the old scan let a fabricated "16%" pass on the back of a timestamp.
    payload = _fact_payload(
        id="f3a9b2c1-0000-4000-8000-000000000016",
        period_start="2026-09-16T00:00:00+00:00",
        period_end="2026-10-16T00:00:00+00:00",
        computed_at="2026-10-16T12:00:00+00:00",
        data_as_of="2026-10-16T12:00:00+00:00",
    )
    allowed = allowed_numbers_from_facts([payload])
    assert validate_answer("زاد 16% خلال 2026", allowed, []) != []
    # The measurement itself is still quotable.
    assert validate_answer("الإيراد 1250", allowed, []) == []


def test_thousands_separator_is_the_same_number():
    allowed = allowed_numbers_from_facts([_fact_payload(value="12500.00")])
    assert validate_answer("المبيعات 12,500 جنيه", allowed, []) == []
    assert validate_answer("المبيعات 12,501 جنيه", allowed, []) != []


def test_window_length_rides_the_fact():
    from app.modules.ai.agents.sales_intelligence.tools import _fact_payload as payload_of

    end = datetime(2026, 10, 16, tzinfo=UTC)
    fact = SimpleNamespace(
        id="F1",
        metric="orders_placed",
        value=Decimal(5),
        unit="count",
        filters={},
        period=SimpleNamespace(start=end - timedelta(days=30), end=end),
        maturity_status=SimpleNamespace(value="immediate"),
        data_as_of=end,
        computed_at=end,
    )
    payload = payload_of(fact)
    assert payload["window"] == "30d"
    allowed = allowed_numbers_from_facts([payload])
    assert validate_answer("آخر 30 يوم", allowed, []) == []


def test_kpi_block_window_falls_back_to_period_bounds():
    result = SimpleNamespace(
        answer="تمام",
        facts=[
            _fact_payload(
                period_start="2026-09-16T00:00:00+00:00",
                period_end="2026-10-16T00:00:00+00:00",
            )
        ],
        findings=[],
        data_quality=SimpleNamespace(status=SimpleNamespace(value="COMPLETE")),
        guardrail_reason=None,
        saved_evidence_id=None,
        run_id=None,
    )
    kpi = next(b for b in build_structured_blocks(result) if b["type"] == "kpi")
    assert kpi["window"] == "2026-09-16..2026-10-16"


def test_kpi_block_prefers_the_tool_window():
    result = SimpleNamespace(
        answer="تمام",
        facts=[_fact_payload(window="30d")],
        findings=[],
        data_quality=SimpleNamespace(status=SimpleNamespace(value="COMPLETE")),
        guardrail_reason=None,
        saved_evidence_id=None,
        run_id=None,
    )
    kpi = next(b for b in build_structured_blocks(result) if b["type"] == "kpi")
    assert kpi["window"] == "30d"


def test_safe_response_wording_is_clean_arabic():
    # Regression pin: the no-findings variant used to read "نقدر نحليل آمن".
    text = safe_response([], {})
    assert "نحلل بأمان" in text
    assert "نحليل" not in text
