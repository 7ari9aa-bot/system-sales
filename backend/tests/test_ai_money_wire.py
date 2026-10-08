"""ADR-053/§47 — AI SPEND is money, so it crosses JSON as ``str(Decimal)``.

Three sites in the ``ai`` module still spelled money as a ``float``, and one
worker site still spelled the WRITE side that way:

1. ``gateway.enforce_budget`` — the read-only budget view answered 200 with
   ``{"spend": float(spend), "cap": float(cap)}`` while the very same function's
   budget-exceeded path (``:490``) already shipped ``str(spend)``/``str(cap)``.
   One function, two spellings of one amount: the number the merchant reads on
   the dashboard was not the number that blocks them.
2. ``router.usage_summary`` (``GET /ai/usage/summary``) — ``"cost": float(cost)``.
3. ``usage.record_usage`` — the port that feeds ``ai_usage.cost``, a
   ``Numeric(18,8)`` column widened SPECIFICALLY to hold sub-cent money, declared
   its ``cost`` as ``float`` and ``workers/message_worker.transcribe_inbound_voice``
   obliged by passing ``float(cost)``. That is the rounding the column was
   widened to remove, reintroduced one frame above the INSERT.

The line these tests hold is the project's line, not a preference: an AMOUNT is
a string, a RATIO/percentage/SHARE is a number. ``enforce_budget``'s ``ratio`` is
``spend / cap * 100`` — a percentage a client thresholds and sorts — so
stringifying it would be its own defect, and
``test_the_budget_percentage_stays_a_number_because_it_is_a_percentage`` exists
to prove nobody "fixes" it that way.

Why the spelling is ``str()`` and not ``marketing.analytics.wire_money``: the
marketing helper quantises to ``NUMERIC(14,2)``'s two places, and every one of
the amounts here lives in ``AI_COST = Numeric(18,8)`` whose whole purpose is the
eight sub-cent places. Quantising an AI spend to cents would zero it out — the
exact bug ``gateway.estimate_cost``'s docstring records. The idiom these paths
share is therefore the one ``orders/router.py`` and ``gateway``'s error path
already use, ``str(decimal)``.

Every case here is DB-free: the sessions are stubs and no
``DATABASE_URL_APP_ADMIN`` is needed, so these run for real on any checkout.
"""

from __future__ import annotations

import inspect
import json
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from fastapi.encoders import jsonable_encoder

from app.modules.ai import gateway as ai_gateway
from app.modules.ai.gateway import enforce_budget
from app.modules.ai.router import usage_summary
from app.modules.ai.usage import PLATFORM_BUCKET, record_usage
from app.workers import message_worker

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")

# ``AI_COST`` is Numeric(18,8): ten integer digits and eight places. This figure
# fills both halves, which is what makes it a probe — float64 has ~15-17
# significant decimal digits, so 18 of them cannot survive the round-trip.
SPEND = Decimal("9999999999.12345678")
CAP = Decimal("9999999999.87654321")


def _wire(payload: object) -> object:
    """What the client actually parses.

    Asserting on the returned dict alone is not enough: FastAPI's default
    response encoder resolves a bare ``Decimal`` by casting it to ``float``, so
    a route that never mentions ``float`` still ships one (the precedent is
    ``test_analytics_overview.test_revenue_summary_route_stringifies_its_aov``).
    Passing through ``jsonable_encoder`` is the real boundary.
    """
    return json.loads(json.dumps(jsonable_encoder(payload)))


class _Result:
    """The three shapes these read paths call on a ``Result``."""

    def __init__(self, *, rows: list = (), scalar: object = None, one: object = None) -> None:
        self._rows = rows
        self._scalar = scalar
        self._one = one

    def scalars(self) -> _Result:
        return self

    def all(self) -> list:
        return list(self._rows)

    def scalar_one(self) -> object:
        return self._scalar

    def one_or_none(self) -> object:
        return self._one

    def scalar_one_or_none(self) -> object:
        return self._one


class _BudgetSession:
    """Answers the two queries ``enforce_budget`` runs, by table name."""

    def __init__(self, *, policies: list, spend: Decimal) -> None:
        self._policies = policies
        self._spend = spend

    async def execute(self, statement, params=None) -> _Result:  # noqa: ANN001
        sql = str(statement)
        if "ai_budget_policies" in sql:
            return _Result(rows=self._policies)
        if "ai_usage" in sql:
            return _Result(scalar=self._spend)
        raise AssertionError(f"unexpected query: {sql}")


def _policy(*, hard_cap: Decimal, on_exceed: str = "block") -> SimpleNamespace:
    """A tenant-scoped BudgetPolicy stand-in (``agent_id`` None = tenant)."""
    return SimpleNamespace(agent_id=None, hard_cap=hard_cap, on_exceed=on_exceed)


# ---------------------------------------------------------------------------
# 1. enforce_budget — the read-only budget view
# ---------------------------------------------------------------------------


async def test_enforce_budget_ships_spend_and_cap_as_decimal_strings() -> None:
    """§47: the 200 response carries the same money shape as the error path."""
    payload = _wire(
        await enforce_budget(_BudgetSession(policies=[_policy(hard_cap=CAP)], spend=SPEND), TENANT)
    )

    assert isinstance(payload["spend"], str), f"spend left as {type(payload['spend'])}"
    assert isinstance(payload["cap"], str), f"cap left as {type(payload['cap'])}"
    assert payload["spend"] == "9999999999.12345678"
    assert payload["cap"] == "9999999999.87654321"
    # What float actually did to these figures, stated so the next reader can
    # check the claim rather than trust it.
    assert Decimal(str(float(SPEND))) != SPEND
    assert Decimal(str(float(CAP))) != CAP


async def test_the_budget_view_and_the_block_error_name_the_same_money() -> None:
    """One amount, one spelling, whichever way the function returns.

    ``on_exceed == "block"`` over the cap raises with ``details`` that already
    shipped ``str(spend)``/``str(cap)``; the 200 path shipped floats beside them.
    A client that reads both must never have to reconcile two representations of
    one figure.
    """
    session = _BudgetSession(policies=[_policy(hard_cap=CAP)], spend=CAP)
    with pytest.raises(ai_gateway.RateLimitExceededError) as raised:
        await enforce_budget(session, TENANT)
    blocked = _wire(raised.value.details)

    under_cap = _wire(
        await enforce_budget(_BudgetSession(policies=[_policy(hard_cap=CAP)], spend=SPEND), TENANT)
    )

    assert blocked["cap"] == under_cap["cap"] == "9999999999.87654321"
    assert blocked["spend"] == "9999999999.87654321"
    assert isinstance(blocked["spend"], str) and isinstance(under_cap["spend"], str)


async def test_the_budget_percentage_stays_a_number_because_it_is_a_percentage() -> None:
    """The money rule is about AMOUNTS. ``ratio`` is ``spend / cap * 100``.

    A client thresholds and sorts a percentage; turning it into a string is its
    own defect (§47 names counts, ratios, shares and durations as numbers). This
    assertion is the guard against an over-broad "stringify everything" fix.
    """
    payload = _wire(
        await enforce_budget(_BudgetSession(policies=[_policy(hard_cap=CAP)], spend=SPEND), TENANT)
    )

    assert isinstance(payload["ratio"], float), payload["ratio"]
    assert payload["ratio"] == pytest.approx(100.0)
    assert isinstance(payload["on_exceed"], str)


# ---------------------------------------------------------------------------
# 2. GET /ai/usage/summary — the cost column
# ---------------------------------------------------------------------------


class _UsageSession:
    """Answers the daily rollup query behind ``GET /ai/usage/summary``."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    async def execute(self, statement, params=None) -> _Result:  # noqa: ANN001
        assert "ai_usage" in str(statement), str(statement)
        return _Result(rows=self._rows)


def _usage_ctx(rows: list[tuple]) -> SimpleNamespace:
    return SimpleNamespace(session=_UsageSession(rows), tenant_id=TENANT)


async def test_the_usage_summary_route_ships_cost_as_a_decimal_string() -> None:
    """AI spend is money; the day it belongs to and its tokens are not."""
    payload = _wire(
        await usage_summary(
            _usage_ctx([(date(2026, 9, 1), 1200, 800, SPEND)]),  # type: ignore[arg-type]
            days=30,
        )
    )
    row = payload["summary"][0]

    assert isinstance(row["cost"], str), f"cost left as {type(row['cost'])}"
    assert row["cost"] == "9999999999.12345678"
    assert Decimal(row["cost"]) == SPEND
    # Counts stay counts (the other half of §47's line).
    assert row["tokens_in"] == 1200 and isinstance(row["tokens_in"], int)
    assert row["tokens_out"] == 800 and isinstance(row["tokens_out"], int)
    assert row["date"] == "2026-09-01"


async def test_a_zero_cost_day_reports_money_not_an_absent_field() -> None:
    """A quiet day answers 0 of money — in the money shape, never omitted."""
    payload = _wire(
        await usage_summary(
            _usage_ctx([(date(2026, 9, 2), 0, 0, Decimal("0.00000000"))]),  # type: ignore[arg-type]
            days=30,
        )
    )
    row = payload["summary"][0]

    assert isinstance(row["cost"], str), row["cost"]
    assert Decimal(row["cost"]) == Decimal("0")


# ---------------------------------------------------------------------------
# 3. The write side: record_usage feeds a Numeric(18,8) column
# ---------------------------------------------------------------------------


class _CapturingSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement, params=None):  # noqa: ANN001
        self.statement = statement
        return _Result()


async def test_record_usages_cost_port_is_a_decimal_not_a_float() -> None:
    """The port that writes ``ai_usage.cost`` may not speak float.

    ``AI_COST = Numeric(18,8)`` exists because a single call costs a fraction of
    a cent and rounding it to ``0.00`` made the monthly cap unreachable
    (``gateway.estimate_cost``). Declaring the parameter ``float`` invited every
    caller to widen it back.
    """
    hints = get_type_hints(record_usage)

    assert hints["cost"] is Decimal, hints["cost"]
    default = inspect.signature(record_usage).parameters["cost"].default
    assert isinstance(default, Decimal), f"the default cost is a {type(default)}"


async def test_record_usage_binds_the_decimal_the_column_holds() -> None:
    """Nothing between the caller and the INSERT re-derives the amount."""
    from sqlalchemy.dialects import postgresql

    session = _CapturingSession()
    await record_usage(session, TENANT, agent_id=PLATFORM_BUCKET, cost=SPEND)
    params = session.statement.compile(dialect=postgresql.dialect()).params

    bound = params["cost"]
    assert isinstance(bound, Decimal), type(bound)
    assert bound == SPEND
    assert params["cost_1"] == SPEND, "the ON CONFLICT increment lost precision"


async def test_the_voice_worker_books_the_decimal_estimate_not_a_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``transcribe_inbound_voice`` estimated its cost in Decimal and then handed
    the money port ``float(cost)`` — the write half of the same round-trip.
    """
    booked: list[object] = []

    async def fake_reserve(session, tenant_id, *, estimated_cost=None, **kwargs):  # noqa: ANN001, ARG001
        return uuid.uuid4()

    async def fake_settle(session, reservation_id):  # noqa: ANN001
        return None

    async def fake_record(session, tenant_id, *, cost=0.0, **kwargs):  # noqa: ANN001, ARG001
        booked.append(cost)

    async def fake_transcribe(session, tenant_id, **kwargs):  # noqa: ANN001, ARG001
        return SimpleNamespace(text="مرحبا", code=200)

    monkeypatch.setattr(message_worker, "reserve_budget", fake_reserve)
    monkeypatch.setattr(message_worker, "settle_reservation", fake_settle)
    monkeypatch.setattr(message_worker, "record_usage", fake_record)
    monkeypatch.setattr(message_worker, "stt_cost_estimate", lambda attachment: SPEND)
    monkeypatch.setattr(message_worker.VoiceService, "transcribe", staticmethod(fake_transcribe))

    attachment = SimpleNamespace(id=uuid.uuid4(), duration=45, transcription_status="pending")
    session = _VoiceNoteSession(attachment)
    text = await message_worker.transcribe_inbound_voice(session, TENANT, message_id=uuid.uuid4())

    assert text == "مرحبا"
    assert len(booked) == 1, booked
    assert isinstance(booked[0], Decimal), f"cost reached the money port as {type(booked[0])}"
    assert booked[0] == SPEND


class _VoiceNoteSession:
    """The session surface ``transcribe_inbound_voice`` actually touches.

    That is the pending-attachment lookup plus the commits its budget guard
    makes around reserve/settle/record — phase 2 of the worker opens no
    transaction of its own, so those commits are what makes the reservation and
    the transcript durable.
    """

    def __init__(self, attachment) -> None:  # noqa: ANN001
        self._attachment = attachment
        self.added: list = []
        self.commits = 0

    async def execute(self, statement, params=None) -> _Result:  # noqa: ANN001
        assert "FROM attachments" in str(statement), str(statement)
        return _Result(one=self._attachment)

    def add(self, instance) -> None:  # noqa: ANN001
        self.added.append(instance)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1
