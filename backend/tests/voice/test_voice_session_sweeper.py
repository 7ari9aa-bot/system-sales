"""Nothing may leave a voice session CONFIGURING or ACTIVE for ever.

The ending of a call is written by the socket that carried it. A replaced worker,
a closed tab, a provider that never answered — none of them run that ``finally``,
and the row they leave says the call is still going. On the owner's database that
was 30 sessions, every one CONFIGURING, none ever ended.

These tests pin the sweep that answers for those rows, without a database:

* ``ending_for`` is the decision, as a pure function — expiry, then the short
  CONFIGURING grace, then the generous ACTIVE silence budget, and nothing at all
  for a state this sweep does not own;
* the per-tenant service ends the rows the decision names, with the reason it
  named, and survives a row whose write blows up;
* the service never commits (the worker owns the transaction) and the worker
  binds every tenant and never lets one shop stop the rest;
* the sweep is actually CALLED — registered in ``GLOBAL_SWEEPERS`` — because new
  code nobody calls is how the sessions stayed stuck in the first place.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.voice.application import session_sweeper
from app.modules.voice.application.session_sweeper import (
    CONNECT_TIMEOUT,
    CONNECTION_LOST,
    DEFAULT_CONFIGURING_GRACE,
    DEFAULT_STALE_AFTER,
    EXPIRED,
    EXPIRED_BEFORE_CONNECT,
    SweepOutcome,
    ending_for,
    sweep_tenant_sessions,
)
from app.modules.voice.domain.states import VoiceSessionState

TENANT = uuid.uuid4()
NOW = dt.datetime(2026, 11, 28, 12, 0, tzinfo=dt.UTC)


# --------------------------------------------------------------- the decision ---


@pytest.mark.parametrize(
    ("state", "expires_in", "touched_minutes_ago", "expected"),
    [
        # A call past its own lifetime is over whatever the row says.
        ("ACTIVE", -1, 0, ("close", EXPIRED)),
        # It never reached the provider and its capability expired: say which half died.
        ("CONFIGURING", -1, 0, ("fail", EXPIRED_BEFORE_CONNECT)),
        # Still inside its lifetime but silent far past the start grace.
        ("CONFIGURING", 3600, 6, ("fail", CONNECT_TIMEOUT)),
        # An ACTIVE call that stopped moving is a lost media path, not a hangup.
        ("ACTIVE", 3600, 31, ("fail", CONNECTION_LOST)),
        # A call that is still being touched is still real: leave it alone.
        ("ACTIVE", 3600, 1, None),
        ("CONFIGURING", 3600, 1, None),
        # This sweep owns two states and no others: a terminal row is not resurrected,
        # and a handoff a person is holding is not closed under them.
        ("CLOSED", -1, 999, None),
        ("FAILED", -1, 999, None),
        ("HANDOFF_PENDING", -1, 999, None),
        ("HUMAN_ACTIVE", -1, 999, None),
    ],
)
def test_ending_for_says_what_a_stale_row_has_earned(
    state, expires_in, touched_minutes_ago, expected
) -> None:
    ending = ending_for(
        state,
        expires_at=NOW + dt.timedelta(seconds=expires_in),
        updated_at=NOW - dt.timedelta(minutes=touched_minutes_ago),
        now=NOW,
    )
    if expected is None:
        assert ending is None
    else:
        assert (ending.action, ending.reason) == expected


def test_a_naive_timestamp_is_read_as_utc_not_as_never() -> None:
    """A driver or a test can hand back a naive datetime; it is still a real moment."""
    ending = ending_for(
        VoiceSessionState.ACTIVE,
        expires_at=(NOW - dt.timedelta(minutes=1)).replace(tzinfo=None),
        updated_at=NOW,
        now=NOW,
    )
    assert ending is not None and ending.reason == EXPIRED


def test_a_row_that_was_never_touched_is_treated_as_silent_not_immortal() -> None:
    ending = ending_for(VoiceSessionState.ACTIVE, expires_at=None, updated_at=None, now=NOW)
    assert ending is not None and ending.reason == CONNECTION_LOST


def test_the_configuring_grace_is_shorter_than_the_active_silence_budget() -> None:
    """A start that never reached the provider is worth ending long before a live call."""
    assert DEFAULT_CONFIGURING_GRACE < DEFAULT_STALE_AFTER


# ---------------------------------------------------------------- the service ---


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeSession:
    """Enough of an AsyncSession to see what the sweep asks for and writes."""

    def __init__(self, rows):
        self.rows = rows
        self.statements: list = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.rows)

    async def flush(self):
        return None

    async def commit(self):  # pragma: no cover - the service must never call it
        raise AssertionError("a sweep service must not commit; the worker owns the transaction")


class _RecordingManager:
    def __init__(self, *, explode_on: uuid.UUID | None = None):
        self.closed: list[tuple[uuid.UUID, str]] = []
        self.failed: list[tuple[uuid.UUID, str]] = []
        self._explode_on = explode_on

    async def close(self, session_id, *, reason="caller_hangup", tenant_id=None):
        if session_id == self._explode_on:
            raise RuntimeError("the row this one touches is broken")
        self.closed.append((session_id, reason))

    async def fail(self, session_id, *, reason):
        if session_id == self._explode_on:
            raise RuntimeError("the row this one touches is broken")
        self.failed.append((session_id, reason))


def _row(state: str, *, expires_in: int, touched_minutes_ago: int):
    return SimpleNamespace(
        id=uuid.uuid4(),
        state=state,
        expires_at=NOW + dt.timedelta(seconds=expires_in),
        updated_at=NOW - dt.timedelta(minutes=touched_minutes_ago),
    )


async def _sweep(monkeypatch, rows, *, explode_on=None):
    manager = _RecordingManager(explode_on=explode_on)
    monkeypatch.setattr(session_sweeper, "_manager", lambda session: manager)
    session = _FakeSession(rows)
    outcome = await sweep_tenant_sessions(session, TENANT, now=NOW)
    return session, manager, outcome


async def test_the_sweep_ends_exactly_the_rows_that_earned_it(monkeypatch) -> None:
    expired_active = _row("ACTIVE", expires_in=-1, touched_minutes_ago=0)
    dead_configuring = _row("CONFIGURING", expires_in=3600, touched_minutes_ago=10)
    lost_active = _row("ACTIVE", expires_in=3600, touched_minutes_ago=60)
    live_active = _row("ACTIVE", expires_in=3600, touched_minutes_ago=1)

    _session, manager, outcome = await _sweep(
        monkeypatch, [expired_active, dead_configuring, lost_active, live_active]
    )

    # A call that ran its course closes; a call that never connected, and one that
    # lost its media path, are failures — each with the reason the decision named.
    assert manager.closed == [(expired_active.id, EXPIRED)]
    assert manager.failed == [
        (dead_configuring.id, CONNECT_TIMEOUT),
        (lost_active.id, CONNECTION_LOST),
    ]
    # The live call was scanned and left exactly as it was.
    assert outcome == SweepOutcome(scanned=4, closed=1, failed=2)
    assert outcome.ended == 3


async def test_one_broken_session_does_not_stop_the_rest(monkeypatch) -> None:
    """A row whose write blows up must cost that row, not the shop's other calls."""
    broken = _row("ACTIVE", expires_in=-1, touched_minutes_ago=0)
    healthy = _row("ACTIVE", expires_in=-1, touched_minutes_ago=0)

    _session, manager, outcome = await _sweep(monkeypatch, [broken, healthy], explode_on=broken.id)

    assert manager.closed == [(healthy.id, EXPIRED)]
    assert outcome.closed == 1


async def test_the_service_flushes_and_never_commits(monkeypatch) -> None:
    """The worker owns the transaction; a service that commits would break RLS rebinding."""
    _session, _manager, _outcome = await _sweep(
        monkeypatch, [_row("ACTIVE", expires_in=-1, touched_minutes_ago=0)]
    )
    source = session_sweeper.__file__
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert ".commit(" not in text


async def test_the_select_locks_rows_so_two_replicas_cannot_end_the_same_call(
    monkeypatch,
) -> None:
    session, _manager, _outcome = await _sweep(monkeypatch, [])

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "voice_sessions" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    # Bound by the tenant, so a sweep cannot read another shop's calls even by accident.
    assert "voice_sessions.tenant_id =" in sql


# ------------------------------------------------------------- the caller ---


def test_the_sweep_is_registered_where_the_scheduler_will_call_it() -> None:
    from app.workers import scheduler_worker

    interval, handler = scheduler_worker.GLOBAL_SWEEPERS["voice.session_sweep"]
    assert interval == dt.timedelta(minutes=5)
    assert handler is scheduler_worker._sweep_voice_sessions  # noqa: SLF001 — the registry
    # The handler is what actually reaches the worker module: a registration that
    # names a function nobody can call is the same as no registration.
    assert handler.__module__ == "app.workers.scheduler_worker"


class _AsyncContext:
    def __init__(self, value=None):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc_info):
        return False


class _WorkerSession(_FakeSession):
    def __init__(self, tenant_ids):
        super().__init__([])
        self.tenant_ids = tenant_ids

    async def execute(self, statement):
        return _Result(list(self.tenant_ids))

    def begin(self):
        return _AsyncContext()


async def test_the_worker_sweeps_every_tenant_and_survives_one_that_fails(monkeypatch) -> None:
    from app.workers import voice_session_sweeper

    first, second = uuid.uuid4(), uuid.uuid4()
    sessions: list[_WorkerSession] = []

    def factory():
        if not sessions:
            sessions.append(_WorkerSession([first, second]))
        else:
            sessions.append(_WorkerSession([]))
        return _AsyncContext(sessions[-1])

    bound: list[uuid.UUID] = []

    async def fake_bind(session, tenant_id):
        bound.append(tenant_id)

    async def fake_sweep(session, tenant_id, **kwargs):
        if tenant_id == first:
            raise RuntimeError("this shop's table is broken")
        return SweepOutcome(scanned=2, closed=1, failed=1)

    monkeypatch.setattr(voice_session_sweeper, "SessionLocal", factory)
    monkeypatch.setattr(voice_session_sweeper, "bind_tenant", fake_bind)
    monkeypatch.setattr(voice_session_sweeper, "sweep_tenant_sessions", fake_sweep)

    ended = await voice_session_sweeper.sweep_stale_voice_sessions(now=NOW)

    # The broken shop is logged and skipped; the healthy one is still swept.
    assert bound == [first, second]
    assert ended == 2
