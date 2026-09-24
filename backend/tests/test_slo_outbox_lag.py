"""§168 / ``outbox_lag`` — the SLO query named a column that does not exist.

``_outbox_lag_compliance`` shipped as raw SQL over a schema it had not checked::

    SELECT EXTRACT(EPOCH FROM (now() - MAX(created_at)))
    FROM outbox_events WHERE relayed_at IS NULL

Two independent defects, both invisible to every test that existed:

1. **``relayed_at`` is not a column of ``outbox_events``.** ``OutboxEvent``
   (:mod:`app.modules.platform.models`) models the relay's state as
   ``status`` (``pending|publishing|published|failed``) plus ``published_at``;
   nothing in the schema has ever been called ``relayed_at``. So Postgres
   rejects the statement with ``UndefinedColumnError`` on *every* call. The
   observable damage splits by route: ``GET /sla/slos/{name}`` ran the
   statement straight through ``measure_slo`` and answered 500, while
   ``GET /sla/slos/measure`` wraps each measurement in ``except Exception`` —
   so there the SLO reported a permanent ``status="error"`` at 0% compliance
   and the real cause was swallowed. Either way an operator never saw an
   outbox backlog, because the query could not run at all.

2. **``MAX(created_at)`` measures the wrong end of the backlog.** The metric
   is publish *lag* — the SLO spec says it "measures the relay's ability to
   drain the backlog" and the function's own docstring says "seconds since the
   *oldest* unrelayed outbox event". The oldest event is ``MIN(created_at)``.
   ``MAX`` reports the age of the *newest* row instead, which is ~0 whenever a
   relay is busy staging traffic: a stuck backlog of hundred-minute events
   reads as perfectly healthy. That half of the bug would have survived fix
   (1) silently, which is the worse failure mode — a green gauge over a red
   system.

The correct shape already existed in the codebase, in the platform health
check ``_outbox_subsystem`` (:mod:`app.modules.platform.router`): "Age of the
oldest unpublished outbox event — the relay's backlog", written as
``MIN(created_at)`` over ``status = 'pending'``. This module now agrees with
it, and the same claim predicate the relay itself drains with
(``_CLAIM_ONE_SQL``, :mod:`app.core.events.outbox`).

Why these tests are DB-free (they are the only kind that run locally — the
Postgres-backed suite skips without ``DATABASE_URL_APP_ADMIN``):

* the SQL the service emits is captured from a stub session, exactly like
  ``tests/test_ai_usage_totals.py`` captures the rollup statement;
* the statement is parsed by **pglast, the real PostgreSQL parser**, and every
  ``ColumnRef`` it yields is resolved against ``OutboxEvent.__table__.columns``
  — derived from the model class, never hand-typed, so a rename or a new
  column on ``OutboxEvent`` re-targets the pin automatically instead of
  letting it rot;
* and ``MIN`` vs ``MAX`` is read off the parse tree's aggregate calls, so it
  cannot be satisfied by a comment or a rename.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.operations.slo_service import measure_all_slos, measure_slo
from app.modules.platform.models import OutboxEvent

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")

#: The column set the pin resolves against — read from the model, not typed here.
OUTBOX_COLUMNS: frozenset[str] = frozenset(OutboxEvent.__table__.columns.keys())


def _outbox_columns_from_the_model() -> frozenset[str]:
    """Re-derive the schema truth, so a hand-edited constant cannot drift.

    Fails loudly if ``OutboxEvent`` ever stops being the source for
    ``outbox_events`` — the pin is worthless if it points at another table.
    """
    assert OutboxEvent.__tablename__ == "outbox_events", OutboxEvent.__tablename__
    assert "status" in OUTBOX_COLUMNS and "created_at" in OUTBOX_COLUMNS, OUTBOX_COLUMNS
    return OUTBOX_COLUMNS


# ------------------------------------------------------- the stub session ----


class UndefinedColumn(Exception):
    """What psycopg raises as ``errors.UndefinedColumn`` / sqlstate 42703.

    Reproduced locally so the failure mode is provable without a Postgres:
    the real driver aborts the statement the moment it names a column the
    schema has not got, and nothing downstream can tell that apart from any
    other DB error.
    """


class _StubResult:
    """Enough of a SQLAlchemy Result for both shapes the SLO handlers use."""

    def __init__(self, scalar: Any, pair: tuple[int, int]) -> None:
        self._scalar = scalar
        self._pair = pair

    def scalar_one(self) -> Any:
        return self._scalar

    def one(self) -> tuple[int, int]:
        return self._pair


class _RecordingSession:
    """Captures every statement the SLO framework emits; answers with fixed data.

    ``lag_seconds`` is what ``outbox_lag`` reads back; the ``pair`` answers the
    ``(total, met)`` handlers so ``measure_all_slos`` can be driven end to end
    without a database.

    ``strict`` makes it behave like the server for the outbox table: a
    statement naming a column ``OutboxEvent`` does not have is rejected before
    it can answer, which is what turns the schema defect into a measured
    behaviour rather than a string comparison.
    """

    def __init__(self, *, lag_seconds: float = 5.0, strict: bool = False) -> None:
        self.sql: list[str] = []
        self._lag_seconds = lag_seconds
        self._strict = strict

    async def execute(self, statement, parameters=None):  # noqa: ANN001
        sql = str(statement)
        self.sql.append(sql)
        if "outbox_events" in sql:
            if self._strict:
                bare = {r for r in _column_refs(sql) if "." not in r}
                ghost = sorted(bare - _outbox_columns_from_the_model())
                if ghost:
                    raise UndefinedColumn(
                        f'column "{ghost[0]}" does not exist\nLINE 1: {sql}'
                    )
            return _StubResult(self._lag_seconds, (1, 1))
        return _StubResult(0, (10, 10))

    @property
    def outbox_sql(self) -> str:
        hits = [s for s in self.sql if "outbox_events" in s]
        assert len(hits) == 1, f"expected exactly one outbox statement, got {hits!r}"
        return hits[0]


async def _captured_outbox_lag_sql(*, lag_seconds: float = 5.0) -> str:
    """The SQL the *production call path* sends for the ``outbox_lag`` SLO.

    Reached through ``measure_slo`` rather than by importing the private
    handler, so this is the statement the ``/sla/slos/{name}`` route runs.
    """
    session = _RecordingSession(lag_seconds=lag_seconds)
    await measure_slo(session, TENANT, "outbox_lag")  # type: ignore[arg-type]
    return session.outbox_sql


# --------------------------------------------- pglast: real Postgres parse ---


def _parse(sql: str) -> list[Any]:
    pytest.importorskip("pglast", reason="pglast is a dev-only parser")
    from pglast import parse_sql

    return [stmt.stmt for stmt in parse_sql(sql)]


def _column_refs(sql: str) -> list[str]:
    """Every column the statement names, via the real PostgreSQL parser."""
    from pglast.visitors import Visitor

    class _Collector(Visitor):
        def __init__(self) -> None:
            self.refs: list[str] = []

        def visit_ColumnRef(self, ancestors, node) -> None:  # noqa: ANN001
            self.refs.append(".".join(f.sval for f in node.fields))

    collector = _Collector()
    for stmt in _parse(sql):
        collector(stmt)
    return collector.refs


def _aggregates(sql: str) -> list[tuple[str, tuple[str, ...]]]:
    """``(aggregate function, columns it wraps)`` for each call in the statement."""
    from pglast.ast import ColumnRef
    from pglast.visitors import Visitor

    class _Collector(Visitor):
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[str, ...]]] = []

        def visit_FuncCall(self, ancestors, node) -> None:  # noqa: ANN001
            name = ".".join(f.sval for f in node.funcname)
            if name not in {"min", "max", "count", "sum", "avg"}:
                return
            wrapped = tuple(
                f.sval for arg in node.args if isinstance(arg, ColumnRef) for f in arg.fields
            )
            self.calls.append((name, wrapped))

    collector = _Collector()
    for stmt in _parse(sql):
        collector(stmt)
    return collector.calls


# ------------------------------------------------------------------ tests ----


def test_the_model_has_no_relayed_at_column():
    """The premise of the bug, pinned where it can be re-checked cheaply.

    Everything below follows from this: the query filtered on a column the
    schema does not have, so it could never have run.
    """
    columns = _outbox_columns_from_the_model()
    assert "relayed_at" not in columns, columns
    # The relay's real state columns.
    assert {"status", "published_at", "not_before"} <= columns, columns


async def test_the_outbox_lag_query_only_names_columns_the_model_has() -> None:
    """Every column reference must resolve against ``OutboxEvent``.

    A Postgres ``UndefinedColumnError`` is what the route used to raise; the
    resolver reproduces it without a server, and against the model class as
    the single source of truth.
    """
    sql = await _captured_outbox_lag_sql()
    referenced = [ref for ref in _column_refs(sql) if "." not in ref]
    assert referenced, f"the parser found no columns in {sql!r} — did the query shape change?"
    unknown = sorted(set(referenced) - _outbox_columns_from_the_model())
    assert not unknown, (
        f"outbox_lag names column(s) {unknown} that OutboxEvent does not have; "
        f"Postgres answers UndefinedColumnError and the SLO never measures. SQL: {sql}"
    )


async def test_outbox_lag_ages_the_oldest_unpublished_event_not_the_newest() -> None:
    """MIN, not MAX: the gauge is backlog age, and the newest row is ~zero.

    ``MAX(created_at)`` makes the metric report the *freshest* un-published
    event, so a relay that is actively staging rows reads 'no lag' no matter
    how far behind it has fallen. The SLO spec's own words — "the relay's
    ability to drain the backlog" — and the health check it must agree with
    both mean the oldest.
    """
    sql = await _captured_outbox_lag_sql()
    aggregates = _aggregates(sql)
    assert aggregates, f"the lag gauge is no longer an aggregate over the backlog: {sql}"

    lagged = [fn for fn, wrapped in aggregates if "created_at" in wrapped]
    assert lagged, f"nothing aggregates created_at for the lag: {aggregates} / {sql}"
    assert "max" not in lagged, (
        f"lag is measured from MAX(created_at) — the NEWEST event, which "
        f"reports a healthy relay over an unstuck backlog: {sql}"
    )
    assert "min" in lagged, (
        f"lag must age the OLDEST un-published event (MIN(created_at)): {sql}"
    )


async def test_the_backlog_is_selected_by_status_not_a_missing_relayed_at() -> None:
    """The un-published predicate must use a real column — the status enum.

    ``published_at IS NULL`` would also resolve, but the relay drains on
    ``status = 'pending'`` (``_CLAIM_ONE_SQL``) and the platform health check
    reports the backlog the same way; two definitions of 'un-relayed' across
    the two screens is how a green SLO and a red health page coexist.
    """
    sql = (await _captured_outbox_lag_sql()).lower()
    assert "relayed_at" not in sql, sql
    assert "status" in sql, (
        f"the un-published filter no longer uses the outbox status enum, so it "
        f"must be naming a timestamp column instead: {sql}"
    )
    assert "pending" in sql, (
        f"the backlog must be defined the way the relay drains it "
        f"(status='pending'), matching _outbox_subsystem: {sql}"
    )


async def test_a_stuck_backlog_reports_a_breach_not_a_healthy_gauge() -> None:
    """Behaviour after the fix: 90 minutes of backlog is not 0 seconds of lag.

    With the old ``MAX`` the answer was the newest row's age, so this is also
    the regression guard on the semantics, end to end through the route's own
    call.
    """
    session = _RecordingSession(lag_seconds=5_400.0)
    result = await measure_slo(session, TENANT, "outbox_lag")  # type: ignore[arg-type]
    assert result.met == 0, f"a 90-minute backlog was scored as drained: {result}"
    assert result.status == "breach", result


async def test_a_drained_backlog_reports_healthy() -> None:
    session = _RecordingSession(lag_seconds=5.0)
    result = await measure_slo(session, TENANT, "outbox_lag")  # type: ignore[arg-type]
    assert result.met == 1 and result.status == "healthy", result


async def test_the_single_slo_route_path_lets_the_statement_answer() -> None:
    """``GET /sla/slos/outbox_lag`` ran the statement unshielded, so it 500ed.

    With the session rejecting unknown columns the way Postgres does, the
    ``UndefinedColumnError`` propagates out of ``measure_slo`` untouched —
    which is what the route returned. After the fix the same call is a
    measurement.
    """
    session = _RecordingSession(lag_seconds=5.0, strict=True)
    result = await measure_slo(session, TENANT, "outbox_lag")  # type: ignore[arg-type]
    assert result.name == "outbox_lag" and result.total == 1, result


async def test_the_bulk_measurement_no_longer_swallows_the_outbox_failure() -> None:
    """The masked symptom: ``measure_all_slos`` hid the SQL error as 0% error.

    That ``except Exception`` is deliberate — one bad SLO must not blank the
    dashboard — which is exactly why the outbox query's failure was invisible.
    Driven against a session that rejects the statement the way the server
    does, the aggregate view used to answer ``status="error"`` at 0% for
    ``outbox_lag`` while reporting the other six healthy. It has to carry a
    real measurement now.
    """
    session = _RecordingSession(lag_seconds=5.0, strict=True)
    results = await measure_all_slos(session, TENANT)  # type: ignore[arg-type]
    outbox = next(r for r in results if r.name == "outbox_lag")
    assert outbox.status != "error", (
        "outbox_lag is failing and the dashboard hides it as 0% error "
        f"(its except-Exception mask): {outbox}"
    )
    assert outbox.window_since, "an unmeasured SLO has no window; a measured one must"

