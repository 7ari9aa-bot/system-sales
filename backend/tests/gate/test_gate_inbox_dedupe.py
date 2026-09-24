"""Consumer-inbox dedupe is a CLAIM, not a read-then-act (§127, ADR-058).

``StreamWorker._process_event`` deduped by SELECTing the ``processed_events``
marker, running ``handle()``, and only then INSERTing the marker. Two workers
holding the same stream entry at the same instant — the shape a Redis-side
``XAUTOCLAIM``/PEL reclaim produces against a slow handler — both saw "not
processed" and both ran the effect. A sequential redelivery was absorbed; a
concurrent one was not.

The invariant pinned here: **for one event id, at most one worker runs the
effect.** The claim is exclusive BEFORE the effect (an advisory transaction
lock keyed on (consumer, event id); see ADR-058), the marker is written inside
the same transaction, and a contended claimer neither runs the effect nor acks
— the entry stays in the PEL until the winner commits (marker → skip) or dies
(lock → claimable again).

Two harnesses, deliberately:

* The ``pure_*`` tests drive ``_process_event`` against a small model of the
  Postgres properties the claim depends on — committed-row visibility,
  transaction-scoped advisory locks, rollback releasing the claim — with
  statement-level yields that force the two racers to interleave exactly where
  the old read-then-act lost the race. They run anywhere and they fail against
  the pre-fix code.
* The ``gate_*`` tests are the real proof: independent connections against a
  real PostgreSQL (harness idiom copied from ``test_gate_oversell.py``). They
  skip (loudly, via the ``db_url`` fixture) when no application database URL is
  configured — in this checkout there is none, so CI is the venue that can
  publish their verdict and run the mutation (revert ``base.py`` to
  read-then-act and ``test_gate_concurrent_workers_run_the_effect_once`` fails
  with one effect per racer).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.events.bus import Event
from app.workers.base import StreamWorker

pytestmark = [pytest.mark.gate]

RACERS = 4  # independent connections, comfortably above one default pool
YIELD_S = 0.01  # per-statement yield in the fake: forces the race to interleave
EFFECT_S = 0.15  # how long the modelled effect takes (pure tests)
GATE_EFFECT_S = 1.5  # ... and on the real DB, wide enough for any CI box


def _event() -> Event:
    """A bus event as the relay delivers it: a stable outbox_id dedupe key."""
    return Event(
        id=str(uuid.uuid4()),
        stream="inbox.dedupe.gate",
        payload={"k": "v"},
        meta={"outbox_id": str(uuid.uuid4())},
    )


class _RecordingBus:
    def __init__(self) -> None:
        self.acked: list[str] = []
        self.dlq: list[tuple[str, str, str]] = []

    async def ack(self, stream: str, group: str, event: Event) -> None:
        self.acked.append(event.id)

    async def send_to_dlq(self, stream: str, event: Event, reason: str) -> None:
        self.dlq.append((stream, event.id, reason))


class _CountingWorker(StreamWorker):
    """A worker whose effect is a timestamped append (+ optional failure)."""

    stream = "inbox.dedupe.gate"
    group = "inbox-dedupe-gate"

    def __init__(
        self,
        bus: _RecordingBus,
        effects: list[str],
        *,
        consumer: str,
        delay: float = EFFECT_S,
        exc: Exception | None = None,
    ) -> None:
        super().__init__(bus)  # type: ignore[arg-type]
        self.name = consumer
        self._effects = effects
        self._delay = delay
        self._exc = exc

    async def handle(self, event: Event) -> None:
        self._effects.append(self.name)
        await asyncio.sleep(self._delay)
        if self._exc is not None:
            raise self._exc


# --------------------------------------------------------------------------
# The model of Postgres the pure tests race against.
#
# Three properties, faithfully: a SELECT sees only COMMITTED rows (so a
# marker inserted inside a still-open transaction is invisible — exactly the
# window the old code raced through); ``pg_try_advisory_xact_lock`` fails while
# another OPEN transaction holds the key and succeeds once that transaction
# commits or rolls back; a rollback undoes the transaction's inserts.
# --------------------------------------------------------------------------


class _Result:
    def __init__(self, first: Any = None, scalar: Any = None) -> None:
        self._first = first
        self._scalar = scalar

    def first(self) -> Any:
        return self._first

    def scalar(self) -> Any:
        return self._scalar


class _FakeTxn:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.active = True
        self.pending: set[tuple[str, str]] = set()

    def __await__(self):  # `tx = await session.begin()` (the claim path)
        async def _start() -> _FakeTxn:
            return self

        return _start().__await__()

    async def __aenter__(self) -> _FakeTxn:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # `async with session.begin():`
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()
        return False

    async def commit(self) -> None:
        if self.active:
            self._session.db._finish(self, commit=True)

    async def rollback(self) -> None:
        if self.active:
            self._session.db._finish(self, commit=False)


class _FakeSession:
    def __init__(self, db: _FakeInboxDb) -> None:
        self.db = db
        self._txn: _FakeTxn | None = None

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        await self.close()
        return False

    def begin(self) -> _FakeTxn:
        self._txn = _FakeTxn(self)
        return self._txn

    def _require_txn(self) -> _FakeTxn:
        if self._txn is None or not self._txn.active:
            self._txn = _FakeTxn(self)
        return self._txn

    async def execute(self, statement, parameters: dict[str, Any] | None = None):  # noqa: ANN001
        return await self.db.execute(self._require_txn(), str(statement), dict(parameters or {}))

    async def close(self) -> None:
        if self._txn is not None and self._txn.active:
            await self._txn.rollback()


class _FakeInboxDb:
    def __init__(self) -> None:
        self.rows: set[tuple[str, str]] = set()  # committed (consumer, event_id)
        self.locks: dict[int, _FakeTxn] = {}
        self.sessions: list[_FakeSession] = []

    def new_session(self) -> _FakeSession:
        session = _FakeSession(self)
        self.sessions.append(session)
        return session

    async def execute(self, txn: _FakeTxn, sql: str, params: dict[str, Any]) -> _Result:
        norm = " ".join(sql.split()).lower()
        # Every statement's effect is applied atomically BEFORE the yield —
        # the sleep only simulates latency during which the other racer runs.
        if norm.startswith("select pg_try_advisory_xact_lock"):
            key = int(params["key"])
            holder = self.locks.get(key)
            if holder is not None and holder.active and holder is not txn:
                await asyncio.sleep(YIELD_S)
                return _Result(scalar=False)
            self.locks[key] = txn
            await asyncio.sleep(YIELD_S)
            return _Result(scalar=True)
        if norm.startswith("select 1 from processed_events"):
            seen = (params["consumer"], params["eid"]) in self.rows
            await asyncio.sleep(YIELD_S)
            return _Result(first=(1,) if seen else None)
        if norm.startswith("insert into processed_events"):
            row = (params["consumer"], params["eid"])
            if row not in self.rows:  # ON CONFLICT (consumer_name, event_id) DO NOTHING
                txn.pending.add(row)
            await asyncio.sleep(YIELD_S)
            return _Result()
        raise AssertionError(f"unexpected statement in the fake inbox db: {sql}")

    def _finish(self, txn: _FakeTxn, *, commit: bool) -> None:
        if commit:
            self.rows |= txn.pending
        txn.pending = set()
        txn.active = False
        for key, holder in list(self.locks.items()):
            if holder is txn:
                del self.locks[key]


@pytest.fixture
def fake_inbox(monkeypatch) -> _FakeInboxDb:  # noqa: ANN001
    """Route every session the worker runtime opens to the modelled inbox.

    Patched at BOTH names the code could resolve — the module attribute
    ``app.workers.base.SessionLocal`` and ``app.core.db.get_sessionmaker`` (the
    old code re-imported ``SessionLocal`` inside the function, so a mutation
    run against the pre-fix loop must hit the same fake, not the real engine).
    """
    db = _FakeInboxDb()
    factory = db.new_session
    monkeypatch.setattr("app.workers.base.SessionLocal", factory)
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: factory)
    return db


# ---------------------------------------------------------- pure (no DB) ----


async def test_pure_concurrent_workers_run_the_effect_once(fake_inbox):
    """THE regression: three workers, one stream entry, same instant.

    Against the pre-fix loop both racers' pre-check SELECTs run before any
    marker exists (statement yields force the interleave), so all three run
    the effect — that is the RED this test was written against. With the claim
    exclusive before the effect, exactly one holds the advisory lock, the
    others find it contended and stand down WITHOUT acking (the entry stays in
    the PEL for a later reclaim, which will then see the committed marker).
    """
    bus = _RecordingBus()
    effects: list[str] = []
    event = _event()
    consumer = "gate-dedupe-pure"
    workers = [_CountingWorker(bus, effects, consumer=consumer) for _ in range(3)]

    await asyncio.gather(*(w._process_event(event) for w in workers))

    assert len(effects) == 1, (
        f"the effect ran {len(effects)} times for one event id — the inbox "
        "claim is still a read-then-act"
    )
    assert len(bus.acked) == 1, "a contended claimer must NOT ack (the winner owns the entry)"
    assert (consumer, event.meta["outbox_id"]) in fake_inbox.rows


async def test_pure_failed_effect_leaves_no_claim(fake_inbox):
    """A crash/failure between claim and effect costs nothing.

    The claim dies with the transaction: no marker survives a failed handler,
    so the staged retry can run the effect again. (This is what distinguishes
    the advisory-lock claim from an insert-before-effect claim, which would
    have to remember to delete its marker.)
    """
    bus = _RecordingBus()
    effects: list[str] = []
    event = _event()
    consumer = "gate-dedupe-pure-fail"

    failing = _CountingWorker(bus, effects, consumer=consumer, exc=RuntimeError("transient"))
    await failing._process_event(event)

    assert len(effects) == 1, "the attempt itself must have run"
    assert fake_inbox.rows == set(), "a failed effect must not leave an inbox claim behind"
    assert len(fake_inbox.locks) == 0, "a failed effect must release the advisory lock"

    healthy = _CountingWorker(bus, effects, consumer=consumer)
    await healthy._process_event(event)

    assert len(effects) == 2, "the retry must be able to run the effect again"
    assert (consumer, event.meta["outbox_id"]) in fake_inbox.rows


async def test_pure_committed_marker_suppresses_the_effect(fake_inbox):
    """A sequential redelivery (the case the old code already handled) still
    hits the marker and is acked-and-skipped, never re-run."""
    bus = _RecordingBus()
    effects: list[str] = []
    event = _event()
    consumer = "gate-dedupe-pure-seen"

    first = _CountingWorker(bus, effects, consumer=consumer)
    await first._process_event(event)
    second = _CountingWorker(bus, effects, consumer=consumer)
    await second._process_event(event)

    assert len(effects) == 1
    assert bus.acked == [event.id, event.id], "the skip must still ack the entry"


def test_pure_lock_key_contract():
    """The advisory key is deterministic, pair-scoped and fits a signed bigint.

    Different events for the same consumer must not collide (they may run in
    parallel — dedupe is per event), and the same event for different consumers
    must not collide either (different pools legitimately handle one event).
    """
    from app.workers.base import _inbox_lock_key

    lo, hi = 0, 2**63 - 1
    a = _inbox_lock_key("worker-a", "11111111-1111-1111-1111-111111111111")
    assert lo <= a <= hi
    assert a == _inbox_lock_key("worker-a", "11111111-1111-1111-1111-111111111111")
    assert a != _inbox_lock_key("worker-a", "22222222-2222-2222-2222-222222222222")
    assert a != _inbox_lock_key("worker-b", "11111111-1111-1111-1111-111111111111")


# --------------------------------------------------------------- DB-gated ----


@pytest.fixture
async def race_engine(db_url: str):
    engine = create_async_engine(
        db_url,
        pool_size=RACERS + 2,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def race_db(monkeypatch, race_engine):
    """Point the worker runtime's own sessions at the race engine.

    Patched at both resolution sites (see ``fake_inbox``) so the mutation —
    reverting base.py to the read-then-act loop — runs the OLD logic against
    this same real database, not against an unreachable default URL.
    """
    factory = async_sessionmaker(race_engine, expire_on_commit=False)
    monkeypatch.setattr("app.workers.base.SessionLocal", factory)
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: factory)
    return factory


def _consumer(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"  # consumer_name is varchar(63)


async def _marker_count(factory, consumer: str, event_id: str) -> int:
    async with factory() as s:
        return (
            await s.execute(
                text(
                    "SELECT count(*) FROM processed_events "
                    "WHERE consumer_name = :c AND event_id = :e"
                ),
                {"c": consumer, "e": event_id},
            )
        ).scalar_one()


async def _cleanup(factory, consumer: str) -> None:
    """Best-effort removal so a shared dev/CI database is not littered."""
    try:
        async with factory() as s, s.begin():
            await s.execute(
                text("DELETE FROM processed_events WHERE consumer_name = :c"),
                {"c": consumer},
            )
    except Exception:  # noqa: BLE001 — cleanup must never mask the real assertion
        pass


async def test_gate_concurrent_workers_run_the_effect_once(race_db):
    """RACERS workers × RACERS independent connections × one event id.

    Mutation: if the pre-effect exclusive claim is removed (base.py back to
    SELECT-then-handle-then-INSERT), every racer's pre-check reads "not
    processed" before any marker commits, and this test fails with
    ``effects == RACERS`` and RACERS acks. That mutation cannot be run here
    (no application database in this checkout) — CI is its only venue.
    """
    bus = _RecordingBus()
    effects: list[str] = []
    event = _event()
    consumer = _consumer("dedupe-gate-race")
    workers = [
        _CountingWorker(bus, effects, consumer=consumer, delay=GATE_EFFECT_S)
        for _ in range(RACERS)
    ]
    barrier = asyncio.Barrier(RACERS)

    try:
        async def racer(w: _CountingWorker) -> None:
            await barrier.wait()  # all connections open, THEN they collide
            await w._process_event(event)

        await asyncio.wait_for(
            asyncio.gather(*(racer(w) for w in workers)), timeout=30
        )

        assert len(effects) == 1, (
            f"the effect ran {len(effects)} times for one event id — two workers "
            "were inside the effect at once"
        )
        assert len(bus.acked) == 1, "only the claim winner may ack the contended entry"
        assert await _marker_count(race_db, consumer, event.meta["outbox_id"]) == 1
    finally:
        await _cleanup(race_db, consumer)


async def test_gate_reclaim_after_a_live_claim_is_absorbed(race_db):
    """The exact Redis-side scenario: XAUTOCLAIM hands a STILL-RUNNING entry
    to another worker. The late claimer must neither run the effect nor ack;
    when it comes back after the winner commits, the marker absorbs it."""
    slow_bus = _RecordingBus()
    late_bus = _RecordingBus()
    effects: list[str] = []
    event = _event()
    consumer = _consumer("dedupe-gate-reclaim")

    try:
        slow = _CountingWorker(slow_bus, effects, consumer=consumer, delay=GATE_EFFECT_S)
        late = _CountingWorker(late_bus, effects, consumer=consumer)
        slow_task = asyncio.create_task(slow._process_event(event))
        await asyncio.sleep(0.4)  # mid-flight: the "reclaim" arrives

        await asyncio.wait_for(late._process_event(event), timeout=5)
        assert len(effects) == 1, "the reclaim raced the live handler and lost — as designed"
        assert late_bus.acked == [], (
            "a contended claimer must leave the entry in the PEL, not ack someone "
            "else's in-flight work"
        )

        await asyncio.wait_for(slow_task, timeout=15)
        assert slow_bus.acked == [event.id]

        # The PEL reclaim comes back for it after the winner committed.
        after_bus = _RecordingBus()
        after = _CountingWorker(after_bus, effects, consumer=consumer)
        await asyncio.wait_for(after._process_event(event), timeout=15)
        assert len(effects) == 1, "the committed marker must suppress the late replay"
        assert after_bus.acked == [event.id], "and the skip must ack, draining the PEL"
        assert await _marker_count(race_db, consumer, event.meta["outbox_id"]) == 1
    finally:
        await _cleanup(race_db, consumer)


async def test_gate_failed_effect_leaves_no_marker_to_poison_the_retry(race_db):
    """The other half of the invariant: a claim must not outlive its effect.

    Handler fails → the claim transaction rolls back with it → zero rows in
    processed_events → the staged retry can run. An insert-before-effect claim
    (ADR-058 shape (a)) fails this test unless every failure path remembers to
    delete its marker — and a hard crash would leak one anyway.
    """
    bus = _RecordingBus()
    effects: list[str] = []
    event = _event()
    consumer = _consumer("dedupe-gate-fail")
    eid: str = event.meta["outbox_id"]

    try:
        failing = _CountingWorker(
            bus, effects, consumer=consumer, delay=0.1, exc=RuntimeError("transient outage")
        )
        await asyncio.wait_for(failing._process_event(event), timeout=15)
        assert len(effects) == 1
        assert await _marker_count(race_db, consumer, eid) == 0, (
            "a failed effect must not leave a claim that suppresses the retry"
        )

        healthy = _CountingWorker(bus, effects, consumer=consumer, delay=0.1)
        await asyncio.wait_for(healthy._process_event(event), timeout=15)
        assert len(effects) == 2, "the retry must run"
        assert await _marker_count(race_db, consumer, eid) == 1, "and then stick"
    finally:
        await _cleanup(race_db, consumer)


async def test_gate_uses_a_separate_connection_per_racer(race_db):
    """Guard the guard: the race above is only meaningful with distinct
    Postgres backends. If someone 'simplifies' the harness onto one shared
    session, the dedupe tests would pass vacuously."""
    barrier = asyncio.Barrier(RACERS)

    async def backend_pid() -> int:
        async with race_db() as session:
            async with session.begin():
                pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                await barrier.wait()  # hold every transaction open at once
                return pid

    pids = await asyncio.gather(*(backend_pid() for _ in range(RACERS)))
    assert len(set(pids)) == RACERS, f"racers shared connections: {pids}"
