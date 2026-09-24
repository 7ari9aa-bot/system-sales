"""ADR-001/§47 (ADR-053) — an attribution CREDIT is money, so it is a STRING.

``AttributionService.attribution_report`` is the campaign rollup behind
``GET /api/v1/marketing/attribution?campaign_id=...``, and it is the second half
of the same money the marketing read models already ship as Decimal strings
(``marketing/analytics.wire_money``, pinned by ``test_roas.py`` and
``test_marketing_read_models.py``). Until this file it shipped its two credited
amounts through ``float()`` — a merchant's credited revenue put through binary
floating point by the client's JSON parser before the screen ever saw it.

The two fields are amounts, so they are strings. The fields beside them are NOT:
``conversions`` is a count and ``days`` is a window length, so stringifying them
would be its own bug (``weight`` on the conversion view is a share, also a
number). That line is what these tests hold.

Every case here is pure-function: no database, no ``DATABASE_URL_APP_ADMIN``.
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import uuid
from decimal import Decimal

import pytest

from app.modules.marketing.attribution_service import AttributionService

_CAMPAIGN = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _report(*rows: tuple[str, int, Decimal]) -> dict:
    return AttributionService.attribution_report(
        campaign_id=_CAMPAIGN,
        days=30,
        model_rows=list(rows),
    )


def _wire(payload: object) -> object:
    """What a client actually parses: the JSON document, not the Python object.

    Asserting on the dict alone can be satisfied by a ``Decimal`` the encoder
    would then cast to a float on the way out. This is the boundary.
    """
    return json.loads(json.dumps(payload))


# ---------------------------------------------------------------------------
# 1. The rule on the wire
# ---------------------------------------------------------------------------


def test_a_credited_amount_leaves_the_report_as_a_decimal_string_not_a_float() -> None:
    """§47: money crosses JSON as ``str(Decimal)``, at its money scale."""
    report = _wire(
        _report(
            ("first_touch", 1, Decimal("200.00")),
            ("last_touch", 1, Decimal("200.00")),
        )
    )

    assert isinstance(report["revenue"], str), report["revenue"]
    assert report["revenue"] == "200.00"
    # The scale travels: a float collapsed 200.00 to 200.0, so a client could no
    # longer tell an amount from a count by looking at it.
    for view in report["alternative_views"]:
        assert isinstance(view["credited_revenue"], str), view
        assert view["credited_revenue"] == "200.00"
    assert Decimal(report["revenue"]) == Decimal("200.00")


def test_a_count_in_the_report_stays_a_number_because_it_is_not_money() -> None:
    """The money rule is about AMOUNTS; a count stringified is a new bug."""
    report = _wire(
        _report(
            ("last_touch", 7, Decimal("200.00")),
        )
    )

    assert report["conversions"] == 7
    assert isinstance(report["conversions"], int)
    assert isinstance(report["days"], int)
    for view in report["alternative_views"]:
        assert isinstance(view["conversions"], int), view
        assert view["never_sum_with_other_views"] is True


def test_a_twelve_figure_credit_keeps_the_cent_a_float_would_round_away() -> None:
    """NUMERIC(14,2) lets a merchant credit 999,999,999,999.99.

    Summing campaign rows into a total is the point of a rollup, and a client
    holding two float64s cannot do that sum and trust the cents:
    ``999999999999.99 - 999999999999.98`` in float64 answers
    ``0.010009765625``, not ``0.01``. The string leaves the arithmetic in
    Decimal, where the cent is still a cent.
    """
    report = _wire(
        _report(
            ("first_touch", 1, Decimal("999999999999.98")),
            ("last_touch", 1, Decimal("999999999999.99")),
        )
    )

    first = next(v for v in report["alternative_views"] if v["model"] == "first_touch")
    assert report["revenue"] == "999999999999.99"
    assert first["credited_revenue"] == "999999999999.98"
    assert Decimal(report["revenue"]) - Decimal(first["credited_revenue"]) == Decimal("0.01")
    # The hazard this removes, stated so the next reader can check it: parsing
    # the same two figures as float64 loses the cent.
    assert float(report["revenue"]) - float(first["credited_revenue"]) != pytest.approx(
        0.01, abs=1e-9
    )


def test_an_absent_credit_reports_zero_as_money_not_as_an_absent_field() -> None:
    """A report with no rows still answers 0.00 of money — in the money shape."""
    report = _wire(_report())

    assert report["canonical_model"] is None
    assert report["revenue"] == "0.00"
    assert report["alternative_views"] == []


# ---------------------------------------------------------------------------
# 2. The guard: this module's float is a SHARE, never an amount
# ---------------------------------------------------------------------------


def test_the_attribution_report_casts_no_amount_to_float() -> None:
    """``attribution_report``/``get_campaign_attribution`` may not emit a float.

    Scoped to the two functions that shape the payload on purpose:
    ``compute_weights`` legitimately returns float SHARES, and
    ``split_credited_value`` turns them back into Decimal money. The distinction
    is the rule, so the guard draws it in the same words.
    """
    path = pathlib.Path(inspect.getfile(AttributionService))
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name not in {"attribution_report", "get_campaign_attribution"}:
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "float":
                offenders.append(f"{node.name}():line {call.lineno}")
    assert not offenders, "amount cast to float for the wire: " + ", ".join(offenders)
