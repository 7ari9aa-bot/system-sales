"""ADR-053/§47 — ``customers.lifetime_value`` is money, and its TWO readers
disagreed about it.

``customers/router.py`` already ships ``str(customer.lifetime_value)`` for the
human reads (``_customer_summary`` and the detail route), and
``customers/timeline.py`` ships ``str(_dec(customer.lifetime_value))`` for the
360 record. ``Customer360Query.get_360`` — the raw-SQL customer context — shipped
``float(...)``. Same NUMERIC(14,2) column, two wire types, and the float one is
the one an AI/segment-shaped consumer reads.

The column is ``MONEY = Numeric(14, 2)``, so 12 integer digits plus two places:
``999999999999.99`` is a value the schema can hold and float64 cannot
round-trip. ``test_a_twelve_figure_ltv_survives_the_wire_exactly`` uses exactly
that amount.

The consumer question the change has to answer, and
``test_segments_thresholds_the_column_in_sql_not_in_json`` pins the answer:
the SEGMENTS DSL filters ``lifetime_value`` by compiling to
``customers.lifetime_value`` in a WHERE clause with a bound parameter
(``segments/service.py:_field_sql``/``_compile_where``). It never reads this
payload, so no threshold comparison can be affected by the JSON type — a segment
rule like ``{"field": "lifetime_value", "op": "gt", "value": 500}`` compares
against the column in Postgres, in NUMERIC, whatever the read model ships.

DB-free: the sessions are stubs, so this runs without ``DATABASE_URL_APP_ADMIN``.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.encoders import jsonable_encoder

from app.core.errors import NotFoundError
from app.modules.customers.router import _customer_summary
from app.modules.customers.service import Customer360Query
from app.modules.segments.service import _compile_where, _field_sql

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
CUSTOMER = uuid.UUID("33333333-3333-3333-3333-333333333333")

# NUMERIC(14,2) at the top of its range: the cent here is what a float64 drops.
LTV = Decimal("999999999999.99")


def _wire(payload: object) -> object:
    """The document a client parses, including FastAPI's default encoder.

    A bare ``Decimal`` in a returned dict is not safe either — the encoder
    resolves it by casting to ``float`` — so this is the boundary as it really is.
    """
    return json.loads(json.dumps(jsonable_encoder(payload)))


def _row(**columns) -> SimpleNamespace:  # noqa: ANN003
    """A ``text()`` result row: the code reads ``row._mapping``."""
    return SimpleNamespace(_mapping=dict(columns))


class _ContextSession:
    """Answers the four raw-SQL reads of ``Customer360Query.get_360`` by table."""

    def __init__(self, *, lifetime_value: object) -> None:
        self._lifetime_value = lifetime_value

    async def execute(self, statement, params=None) -> SimpleNamespace:  # noqa: ANN001
        sql = str(statement)
        if "FROM customers" in sql:
            return SimpleNamespace(
                one_or_none=lambda: _row(
                    id=str(CUSTOMER),
                    name="فاتن",
                    phone="+201000000000",
                    email=None,
                    is_blocked=False,
                    lifetime_value=self._lifetime_value,
                    created_at=None,
                    updated_at=None,
                )
            )
        if "FROM orders" in sql or "FROM conversations" in sql or "FROM memories" in sql:
            return SimpleNamespace(all=lambda: [])
        raise AssertionError(f"unexpected query: {sql}")


async def _context(lifetime_value: object) -> dict:
    return _wire(
        await Customer360Query.get_360(
            _ContextSession(lifetime_value=lifetime_value),  # type: ignore[arg-type]
            TENANT,
            CUSTOMER,
        )
    )


# ---------------------------------------------------------------------------
# 1. The rule on the wire
# ---------------------------------------------------------------------------


async def test_the_customer_context_ships_lifetime_value_as_a_decimal_string() -> None:
    """§47: an amount crosses JSON as ``str(Decimal)`` — LTV included."""
    payload = await _context(LTV)

    assert isinstance(payload["lifetime_value"], str), (
        f"lifetime_value crossed as {type(payload['lifetime_value'])}"
    )
    assert payload["lifetime_value"] == "999999999999.99"
    assert Decimal(payload["lifetime_value"]) == LTV


async def test_a_twelve_figure_ltv_survives_the_wire_exactly() -> None:
    """The cent a float64 cannot hold, stated as the hazard it removes.

    ``999999999999.99`` and ``999999999999.98`` are both storable in
    NUMERIC(14,2). Parsed as floats they are the SAME number to two decimals and
    differ by more than a cent in binary — so an LTV sum over a page of customers
    stops adding up. As strings the arithmetic stays in Decimal.
    """
    high = await _context(LTV)
    low = await _context(Decimal("999999999999.98"))

    assert Decimal(high["lifetime_value"]) - Decimal(low["lifetime_value"]) == Decimal("0.01")
    # Exactly the drift the string rule exists to prevent:
    assert float(high["lifetime_value"]) - float(low["lifetime_value"]) != 0.01


async def test_a_zero_ltv_reports_money_in_the_money_shape_not_as_an_integer() -> None:
    """``0`` is a valid LTV; shipping it as ``0`` (an int) erases the money scale.

    The old ``float(... or 0)`` folded "no money" into a bare number, so a client
    could not tell an amount from a count by looking at it.
    """
    for value in (Decimal("0.00"), None):
        payload = await _context(value)
        assert isinstance(payload["lifetime_value"], str), value
        assert Decimal(payload["lifetime_value"]) == Decimal("0")


async def test_both_readers_of_the_ltv_column_ship_the_same_string() -> None:
    """The disagreement this file closes, pinned.

    ``_customer_summary`` (the human list/detail read) and ``get_360`` (the
    customer context) read ONE column and must not answer it two ways.
    """
    customer = SimpleNamespace(
        id=CUSTOMER,
        name="فاتن",
        phone="+201000000000",
        email=None,
        lifetime_value=LTV,
        is_blocked=False,
    )

    human_read = _wire(_customer_summary(customer))
    context_read = await _context(LTV)

    assert human_read["lifetime_value"] == context_read["lifetime_value"] == "999999999999.99"


# ---------------------------------------------------------------------------
# 2. The consumer that THRESHOLDS this value
# ---------------------------------------------------------------------------


def test_segments_thresholds_the_column_in_sql_not_in_json() -> None:
    """A segment rule on ``lifetime_value`` never sees the read model.

    ``{"field": "lifetime_value", "op": "gt", "value": 500}`` compiles to the
    column expression with a monotonic bind param, so the comparison happens in
    Postgres NUMERIC. Changing the JSON shape of a DIFFERENT payload therefore
    cannot silently change who matches a segment — and the DSL's value stays a
    number on its own path, because that is a literal bound into SQL, not money
    crossing an API response.
    """
    assert _field_sql("lifetime_value") == "customers.lifetime_value"

    params: dict = {}
    where = _compile_where(
        {"field": "lifetime_value", "op": "gt", "value": 500},
        params,
    )

    assert where == "(customers.lifetime_value > :p0)"
    assert params == {"p0": 500}
    assert isinstance(params["p0"], int)


async def test_missing_customer_still_raises_rather_than_reporting_zero_money() -> None:
    """Guard on the refactor: the not-found path is unchanged by the money fix."""

    class _Gone:
        async def execute(self, statement, params=None):  # noqa: ANN001
            return SimpleNamespace(one_or_none=lambda: None)

    with pytest.raises(NotFoundError):
        await Customer360Query.get_360(_Gone(), TENANT, uuid.uuid4())
