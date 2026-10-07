"""P-02 — the failed-row cool-down must be durable, not a staging-time artifact.

Retry scheduling for an outbox row is ``OutboxEvent.not_before``: ``_CLAIM_ONE_SQL``
refuses a row whose ``not_before`` is still in the future, so it is THE durable
scheduling column. But a failed row never earns one — ``_MARK_FAILED_SQL`` sets
``status = 'failed'`` and nothing else — while the cool-down that looks like it
protects a dead dependency lives entirely inside ``_RECLAIM_FAILED_SQL``'s wake
predicate on ``COALESCE(published_at, created_at)``.

That predicate reads the row's STAGING time. ``published_at`` is never set on a
failed row, so it lands on ``created_at`` — a value frozen the moment the event
was staged. The very first re-queue therefore makes the row older than the
cool-down forever: ``_reclaim_stranded`` flips it back to ``pending`` WITHOUT a
``not_before``, and on the next drain the claim honours nothing and retries it.
Against a bus that stays down, the poisoned row is hammered about once per drain,
and because the claim is ``ORDER BY created_at`` it also starves every row behind
it. That is the defect.

The shape the module already points at (see the NOTE above ``_RECLAIM_FAILED_SQL``)
is: **the cool-down belongs in ``not_before``, stamped when the row fails** and
**preserved by the reclaim instead of reset**, so the claim honours it directly:

* ``_MARK_FAILED_SQL`` schedules the next try: a bounded exponential ``not_before``
  derived from ``attempts`` (the per-processing-failure count the claim just
  incremented). ``now() + LEAST(base * 2^(attempts-1), ceiling)`` seconds.
* ``_RECLAIM_FAILED_SQL`` wakes on that ``not_before`` rather than the immutable
  staging clock, and PRESERVES it — a re-queued failed row keeps its earned
  cool-down, so no hot loop. A not-yet-due failed row is simply left alone.
* ``_RECLAIM_STRANDED_SQL``'s publishing arm CLEARS ``not_before``: a stranded
  row was never marked failed, so it earned no cool-down and deserves a prompt,
  fresh-budget retry.

The two intents stay separate and neither undoes 897fb6f: ``attempts`` remains a
per-processing-failure budget that EVERY re-queue resets (the P-01 guards below
still hold for both reclaims), while the cool-down — "do not hammer a dependency
that is down" — is carried by ``not_before``, which the failed reclaim preserves.

DB-free proof is the whole point here: DB-backed tests skip locally without
``DATABASE_URL_APP_ADMIN`` and only run in CI, so the durable claims are pinned
from the compiled SQL shape and from a stub-session drain (see
``tests/test_ai_usage_totals.py`` for the shape-pin idiom). A real-rows gate
scenario closes the behavioural loop in CI.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

from app.core.events.outbox import OutboxRelay

# --------------------------------------------------------------- harness -----

BATCH = 50
MAX_ATTEMPTS = 5


class _StubResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = list(rows or [])

    def scalars(self) -> _StubResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def mappings(self) -> _StubResult:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _RecordingSession:
    """Captures the SQL the relay runs, with the parameters it bound."""

    def __init__(self, claim_rows: list[Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._claim_rows = list(claim_rows or [])

    async def execute(self, statement, parameters=None):  # noqa: ANN001
        sql = " ".join(str(statement).split())
        self.calls.append((sql, dict(parameters or {})))
        # Only the claim RETURNs rows; every other statement yields nothing the
        # relay inspects, so return the queued claimable row for the claim only.
        if "attempts + 1" in sql:
            return _StubResult(self._claim_rows)
        return _StubResult([])

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _SessionContext:
    def __init__(self, session: _RecordingSession) -> None:
        self._session = session

    async def __aenter__(self) -> _RecordingSession:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _AlwaysFailingBus:
    """A bus that is down: every publish raises, exactly like a Redis outage."""

    def __init__(self) -> None:
        self.publishes = 0

    async def publish(self, stream, payload, meta=None) -> str:  # noqa: ANN001
        self.publishes += 1
        raise ConnectionError("redis is down")


def _settings_stub(**overrides: Any) -> Any:
    class _Settings:
        outbox_lease_seconds = overrides.get("outbox_lease_seconds", 7.5)
        outbox_failed_requeue_seconds = overrides.get("outbox_failed_requeue_seconds", 300.0)
        worker_max_attempts = overrides.get("worker_max_attempts", MAX_ATTEMPTS)

    return _Settings()


def _stmt(name: str) -> str:
    """The compiled SQL of a module-level statement, whitespace-normalised."""
    from app.core.events import outbox as outbox_module

    return " ".join(str(getattr(outbox_module, name)).split())


def _set_clause(sql: str) -> str:
    """Text between the first SET and the following WHERE (the reclaim/UPDATEs)."""
    m = re.search(r"\bSET\b(.*?)\bWHERE\b", sql, re.IGNORECASE | re.DOTALL)
    assert m, f"no parseable SET clause: {sql}"
    return m.group(1)


def _drain_bound_max_backoff(outbox_module: Any) -> float:
    """Run one drain and return the ``backoff_max_seconds`` actually bound to the
    failed mark — the value that really reaches Postgres, not a constant copy."""
    original_settings = outbox_module.get_settings
    original_session = outbox_module.SessionLocal
    claim_row = {
        "id": uuid.uuid4(),
        "stream": "order.events",
        "payload": "{}",
        "meta": "{}",
        "aggregate_type": "order",
        "aggregate_id": uuid.uuid4(),
        "created_at": None,
    }
    session = _RecordingSession(claim_rows=[claim_row])
    outbox_module.get_settings = lambda: _settings_stub()
    outbox_module.SessionLocal = lambda: _SessionContext(session)
    try:
        asyncio.run(
            OutboxRelay(_AlwaysFailingBus())._drain_once(  # type: ignore[arg-type]
                batch=BATCH, max_attempts=MAX_ATTEMPTS
            )
        )
    finally:
        outbox_module.get_settings = original_settings
        outbox_module.SessionLocal = original_session
    marks = [p for sql, p in session.calls if "status = 'failed'" in sql and "last_error" in sql]
    assert marks, "the drain never ran the failed mark"
    return float(marks[0]["backoff_max_seconds"])


# ------------------------------------------------- P-01 invariants (must hold) -----


def test_mark_failed_and_the_reclaims_still_respect_the_p01_attempt_budget():
    """897fb6f guard: every RE-QUEUE resets attempts; a failed MARK does not.

    ``_MARK_FAILED_SQL`` must NOT be one of the re-queueing statements (it writes
    'failed', not 'pending'), and both reclaims keep zeroing the counter, so
    nothing about P-02 may strand a row 'pending' at the claim cap. This pins the
    boundary the P-02 fix must not cross.
    """
    stranded = _stmt("_RECLAIM_STRANDED_SQL")
    failed = _stmt("_RECLAIM_FAILED_SQL")

    for name, sql in (("stranded", stranded), ("failed", failed)):
        assert "status = 'pending'" in sql, f"{name} no longer re-queues"
        assert "attempts = 0" in _set_clause(sql), (
            f"{name} re-queues without resetting attempts (P-01 regression)"
        )

    mark = _stmt("_MARK_FAILED_SQL")
    assert "status = 'failed'" in mark, "the failed mark must not write 'pending'"


# ------------------------------------------------------- P-02: the mark ----------


def test_mark_failed_schedules_a_durable_not_before():
    """The cool-down moves into ``not_before`` — the column the claim honours.

    The defect is that a failed row earns no ``not_before``, so the claim retries
    it every drain. The fix stamps one when marking failed. RED today because
    ``_MARK_FAILED_SQL`` touches only status and last_error.
    """
    set_clause = _set_clause(_stmt("_MARK_FAILED_SQL"))
    assert "not_before" in set_clause, (
        "marking a row failed must schedule its next try via not_before, or the "
        "claim retries it once per drain (the P-02 hot loop): " + set_clause
    )


def test_mark_failed_backoff_is_exponential_in_attempts_and_bounded():
    """``not_before`` is a bounded exponential in ``attempts``, computed in SQL.

    The cool-down must grow with the attempt count (so a poisoned row that keeps
    failing backs off), and it MUST be clamped by a ceiling (LEAST/GREATEST) so
    the interval cannot run away across a long outage. It is expressed with
    ``make_interval`` off the transaction's ``now()`` so it works under the
    connection pooler — the same idiom ``_CLAIM_ONE_SQL``/``_RECLAIM_*`` already
    use, never a Python-side timestamp.
    """
    sql = _stmt("_MARK_FAILED_SQL")
    m = re.search(r"not_before\s*=(.+?)(?:\bWHERE\b)", sql, re.IGNORECASE | re.DOTALL)
    assert m, f"no not_before assignment to inspect: {sql}"
    expr = m.group(1)

    assert "now()" in expr, "the schedule must be stamped off the DB clock, not a literal"
    assert "make_interval" in expr, "duration must be a pooler-safe interval expression"
    # exponential in attempts
    assert "attempts" in expr, "the backoff must derive from the attempt count"
    assert "power(" in expr.lower() or "2 ^" in expr or "**" in expr or "exp(" in expr.lower(), (
        f"the backoff must grow exponentially with attempts: {expr}"
    )
    # bounded
    assert "least(" in expr.lower(), f"the backoff must be clamped by a ceiling: {expr}"


def test_backoff_constants_are_a_bounded_ladder_and_the_drain_uses_them():
    """The module's exposed ceiling really is the value the drain binds.

    A pure shape pin (``LEAST(`` present) could pass on a nonsense expression, so
    cross-check the two SOURCES of the number: the ceiling constant the module
    exposes and the parameter ``_drain_once`` actually threads into
    ``_MARK_FAILED_SQL``. They must agree, the ceiling must be finite, and the SQL
    must clamp the growing power term to that bound — not to the raw ``attempts``
    product, which is unbounded.
    """
    import math

    from app.core.events import outbox as outbox_module

    ceiling = float(outbox_module.OUTBOX_BACKOFF_CEILING_SECONDS)
    assert math.isfinite(ceiling) and ceiling > 0, "the ceiling must be a finite bound"

    # The exponent is on the row's own attempts and the whole product is the
    # first argument of LEAST — the ceiling is the bound, never the raw product.
    expr = re.search(
        r"not_before\s*=(.+?)\bWHERE\b", _stmt("_MARK_FAILED_SQL"), re.IGNORECASE | re.DOTALL
    ).group(1)
    assert "power(2, greatest(attempts - 1, 0))" in expr.lower().replace("  ", " "), (
        f"the ladder must double per attempt off a non-negative exponent: {expr}"
    )
    assert "least(" in expr.lower() and "backoff_max_seconds" in expr.lower(), (
        f"the growing term must be clamped by the ceiling bind param: {expr}"
    )

    # The drain binds exactly that ceiling — no divergence between the exposed
    # number and the one actually sent to Postgres.
    assert _drain_bound_max_backoff(outbox_module) == ceiling, (
        "the drain bound a different ceiling than the module exposes"
    )


# ------------------------------------------- P-02: the failed reclaim wakes right --


def test_failed_reclaim_wakes_on_not_before_not_the_immutable_staging_clock():
    """The failed reclaim must honour the durable schedule, not ``created_at``.

    Keying the wake on ``COALESCE(published_at, created_at)`` is the second half
    of the bug: once the row is past that staging-age bound it is eligible on
    EVERY drain, so the cool-down evaporates after the first re-queue. The claim
    already reads ``not_before``; the reclaim must wake on the same column.
    """
    sql = _stmt("_RECLAIM_FAILED_SQL")
    where = sql.split("WHERE", 1)[1] if "WHERE" in sql else sql
    assert "not_before" in where, (
        "the failed-row reclaim must wake on not_before, not the immutable "
        "staging clock that made the cool-down a one-shot: " + where
    )


def test_failed_reclaim_preserves_not_before_so_a_woken_row_keeps_its_cooldown():
    """A re-queued failed row must NOT have its earned cool-down wiped.

    If the reclaim zeroed or cleared not_before, the next claim would fire
    immediately and the hot loop returns. Only status + attempts reset here; the
    schedule survives to be recomputed (longer) on the next failure.
    """
    set_clause = _set_clause(_stmt("_RECLAIM_FAILED_SQL"))
    assert "not_before = NULL" not in set_clause, (
        "the failed reclaim must preserve not_before, not clear it: " + set_clause
    )
    # It must not reset not_before to a past/instant value either.
    m = re.search(r"not_before\s*=(.+?)(?:$|WHERE)", set_clause, re.IGNORECASE | re.DOTALL)
    assert not m, (
        "the failed reclaim should not rewrite not_before at all — preserving it "
        "is what stops the retry storm: " + set_clause
    )


def test_stranded_publishing_reclaim_clears_not_before_for_a_prompt_retry():
    """A row stranded in 'publishing' never failed, so it earned no cool-down.

    This is the OTHER reclaim intent: the fresh-budget re-queue must clear any
    stale not_before so the claim can take it promptly. Conflating the two requeues
    (clearing not_before on failed rows too) would undo the P-02 fix.
    """
    set_clause = _set_clause(_stmt("_RECLAIM_STRANDED_SQL"))
    assert "not_before = NULL" in set_clause, (
        "the publishing-strand reclaim must clear not_before so a fresh-budget "
        "retry is not blocked by a schedule it never earned: " + set_clause
    )


# ---------------------------------------------- P-02 drain behaviour (DB-free) -----


def test_drain_marks_a_failing_row_failed_with_a_future_not_before(monkeypatch):
    """End-to-end wiring without a database: a publish failure stamps not_before.

    Drives the real ``_drain_once`` with one claimable row and an always-failing
    bus, and captures what the relay actually bound into ``_MARK_FAILED_SQL`` —
    proving the cool-down reaches the statement that writes it, with the bounded
    base/ceiling threaded in, not a hardcoded literal.
    """
    from app.core.events import outbox as outbox_module

    monkeypatch.setattr(outbox_module, "get_settings", lambda: _settings_stub())

    row_id = uuid.uuid4()
    claim_row = {
        "id": row_id,
        "stream": "order.events",
        "payload": "{}",
        "meta": "{}",
        "aggregate_type": "order",
        "aggregate_id": uuid.uuid4(),
        "created_at": None,
    }
    session = _RecordingSession(claim_rows=[claim_row])
    monkeypatch.setattr(outbox_module, "SessionLocal", lambda: _SessionContext(session))

    async def _run() -> int:
        return await OutboxRelay(_AlwaysFailingBus())._drain_once(  # type: ignore[arg-type]
            batch=BATCH, max_attempts=MAX_ATTEMPTS
        )

    asyncio.run(_run())

    # The mark is the statement that writes last_error — the failed-row reclaim
    # also contains `status = 'failed'`, but only in its WHERE clause.
    marks = [
        (sql, p) for sql, p in session.calls if "status = 'failed'" in sql and "last_error" in sql
    ]
    assert marks, f"the relay never marked the failed row: {session.calls}"
    sql, params = marks[0]
    assert "not_before" in sql, "the failed mark the relay ran still carries no schedule"
    assert "attempts" not in params, (
        "not_before must be stamped in SQL from the row's own attempts, not "
        "recomputed Python-side from a stale count"
    )
    assert "backoff_base_seconds" in params and "backoff_max_seconds" in params, (
        f"the bounded backoff was not threaded into the mark: {params}"
    )
    assert params["backoff_max_seconds"] >= params["backoff_base_seconds"] > 0, params


def test_drain_does_not_hardcode_the_backoff_duration(monkeypatch):
    """The durations are settings, not literals baked into the SQL text.

    Same discipline as the lease/requeue pins in ``test_outbox_claim``: a literal
    interval in the statement is invisible to operators and untestable.
    """
    from app.core.events import outbox as outbox_module

    monkeypatch.setattr(outbox_module, "get_settings", lambda: _settings_stub())
    row_id = uuid.uuid4()
    claim_row = {
        "id": row_id,
        "stream": "order.events",
        "payload": "{}",
        "meta": "{}",
        "aggregate_type": "order",
        "aggregate_id": uuid.uuid4(),
        "created_at": None,
    }
    session = _RecordingSession(claim_rows=[claim_row])
    monkeypatch.setattr(outbox_module, "SessionLocal", lambda: _SessionContext(session))

    asyncio.run(
        OutboxRelay(_AlwaysFailingBus())._drain_once(  # type: ignore[arg-type]
            batch=BATCH, max_attempts=MAX_ATTEMPTS
        )
    )

    sql = "\n".join(s for s, _ in session.calls)
    assert "interval '" not in sql, "a backoff duration is baked into the SQL text"
