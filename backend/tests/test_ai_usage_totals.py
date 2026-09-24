"""§55 — the AI usage screen may not do the arithmetic the API can do.

`docs/spec/ARCHITECTURE_SPEC_1-124.txt` §55 (l.1946-1964) is explicit: "لا تجعل
browser يعمل business aggregation". `GET /ai/usage/summary` answers one row per
UTC day, and the AI screen closed the period by adding those rows itself
(`frontend/src/app/(dash)/ai/page.tsx`, `sumDecimals(usage.map(r => r.cost))`).
That is a rollup computed on the client from a partial payload — the shape §55
names, and the reason the money-sweep's own `sumDecimals` docstring had to
apologise for it ("a browser totals money only as a last resort").

The route already holds every term, in Decimal, after SQL has done the daily
grouping; summing the days is exact arithmetic on values it has already read. So
the totals belong here and the client renders them.

Two claims, both DB-free (the session is a stub answering the rollup query):

* the response carries its own period totals;
* and the money total keeps `Numeric(18,8)`'s eight places across the JSON wire —
  which is the part that fails if someone writes `float(...)` anywhere in it.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from fastapi.encoders import jsonable_encoder

from app.modules.ai.router import usage_summary

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _RollupSession:
    """Answers the daily rollup behind `GET /ai/usage/summary`."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    async def execute(self, statement, params=None) -> _Result:  # noqa: ANN001
        assert "ai_usage" in str(statement), str(statement)
        return _Result(self._rows)


def _ctx(rows: list[tuple]) -> SimpleNamespace:
    return SimpleNamespace(session=_RollupSession(rows), tenant_id=TENANT)


def _wire(payload: object) -> object:
    """FastAPI's encoder casts a bare `Decimal` to float, so assert after it."""
    return json.loads(json.dumps(jsonable_encoder(payload)))


async def test_the_route_reports_its_own_period_totals() -> None:
    payload = _wire(
        await usage_summary(
            _ctx(
                [
                    (date(2026, 9, 1), 1200, 800, Decimal("1.25000000")),
                    (date(2026, 9, 2), 100, 50, Decimal("0.75000001")),
                    (date(2026, 9, 3), 0, 0, Decimal("0")),
                ]  # type: ignore[list-item]
            ),
            days=30,
        )
    )

    totals = payload["totals"]
    assert Decimal(totals["cost"]) == Decimal("2.00000001"), totals
    # Counts beside the money stay counts.
    assert totals["tokens_in"] == 1300 and isinstance(totals["tokens_in"], int)
    assert totals["tokens_out"] == 850 and isinstance(totals["tokens_out"], int)


async def test_the_cost_total_is_a_decimal_string_not_a_float_masquerading() -> None:
    """The 18th significant digit is the probe: float64 cannot carry it.

    `Numeric(18,8)` holds ten integer digits and eight places; `9999999999.12345678`
    fills both halves. A `float()` anywhere in this path rounds it, so this
    assertion is the one that dies if the money contract is broken again.
    """
    payload = _wire(
        await usage_summary(
            _ctx(
                [
                    (date(2026, 9, 1), 1, 1, Decimal("9999999999.12345678")),
                    (date(2026, 9, 2), 1, 1, Decimal("0.00000002")),
                ]  # type: ignore[list-item]
            ),
            days=30,
        )
    )

    cost = payload["totals"]["cost"]
    assert isinstance(cost, str), f"total cost left as {type(cost)}"
    assert Decimal(cost) == Decimal("9999999999.12345680"), cost


async def test_an_empty_period_still_answers_a_total_of_money() -> None:
    """No rows is zero money — stated, not absent, so the client adds no branch."""
    payload = _wire(await usage_summary(_ctx([]), days=30))  # type: ignore[arg-type]

    assert payload["summary"] == []
    assert Decimal(payload["totals"]["cost"]) == Decimal("0")
    assert payload["totals"]["tokens_in"] == 0
