"""G-08 — outbox claim semantics: who owns a row that is being published.

The relay claims rows with ``FOR UPDATE SKIP LOCKED`` (that part already
existed), so two relays cannot take the same *pending* row. What was missing
is any notion of a **claim instant**: there is no ``locked_at`` column, and the
safety net that re-queues rows stranded in ``publishing`` measured the lease
from ``created_at`` — the moment the event was *staged*, not the moment a relay
*taken* it. Any row older than the lease was therefore fair game while its
relay was still alive and working on it.

Concretely, the drain claimed a whole batch in one transaction and then
committed per row, so the first commit made every *remaining* row of the batch
durably ``publishing`` **and unlocked** while the same relay was still about to
publish it. A second relay's reclaim reset those rows to ``pending``, claimed
them, and published them a second time — concurrently.

Concurrent double publication is exactly the case the consumer-side dedupe does
NOT cover: the dedupe is a read-then-act (``workers/base.py`` SELECTs the
``processed_events`` marker, runs ``handle()``, and only then inserts the
marker), so two consumers running the same event at the same instant both see
"not processed" and both produce the side effect. Stable ``outbox_id`` dedupe
saves a *sequential* redelivery, not a simultaneous one.

The fix keeps Postgres as the lock manager instead of adding a column: a row is
claimed, published and marked in ONE transaction, so the row lock *is* the
lease (a live relay's row is locked and invisible, a crashed relay's claim
rolls back with it), and the reclaim scans with ``FOR UPDATE SKIP LOCKED`` so
it can never steal from a live relay at any age. The lease duration moves to
``settings.outbox_lease_seconds``.

DB-gated cases below need a real PostgreSQL and skip locally without
``DATABASE_URL_APP_ADMIN``; they are proven in CI. The two-connection race
follows ``tests/test_job_runner.py::test_two_connections_cannot_claim_the_same_job``.
"""

from __future__ import annotations

import asyncio
import contextvars
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.core.events.outbox import OutboxRelay


class RelayProcessDied(BaseException):
    """A relay killed mid-publish.

    A BaseException on purpose: it escapes every ``except Exception`` in the
    relay the way SIGKILL does, so the claim transaction is never committed —
    which is exactly the moment G-08 is about.
    """


BATCH = 50
MAX_ATTEMPTS = 5


class RecordingBus:
    """An EventBus that records every publish, optionally failing on command."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []
        self.raise_on_call: int | None = None
        self.gate: asyncio.Event | None = None
        self.entered: asyncio.Event | None = None
        self._calls = 0

    async def publish(self, stream, payload, meta=None) -> str:
        self._calls += 1
        if self._calls == 1 and self.entered is not None:
            self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.raise_on_call == self._calls:
            raise RelayProcessDied("relay process died")
        self.published.append({"outbox_id": (meta or {}).get("outbox_id"), "stream": stream})
        return f"{self._calls}-0"

    def ids(self) -> list[str]:
        return [p["outbox_id"] for p in self.published]


# --------------------------------------------------------------- DB-free -----


def test_reclaim_binds_the_configured_lease_instead_of_a_hardcoded_interval(
    monkeypatch,
):
    """G-08 (iv): the lease is a setting, threaded into the statement.

    The durations were three literals baked into SQL strings, so an operator
    could not shorten them and a test could not prove what the relay honours.
    """
    from app.core.events import outbox as outbox_module

    class _Settings:
        outbox_lease_seconds = 7.5
        outbox_failed_requeue_seconds = 12.5

    monkeypatch.setattr(outbox_module, "get_settings", lambda: _Settings())

    class _RecordingSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def execute(self, statement, parameters=None):  # noqa: ANN001
            self.calls.append((str(statement), dict(parameters or {})))
            return None

    session = _RecordingSession()
    relay = OutboxRelay(RecordingBus())  # type: ignore[arg-type]

    async def _run() -> None:
        await relay._reclaim_stranded(session)

    asyncio.run(_run())

    assert session.calls, "reclaim ran no statement"
    sql = "\n".join(s for s, _ in session.calls)
    params = [p for _, p in session.calls]
    assert "interval '" not in sql, "a duration is still baked into the SQL text"
    assert any(p.get("lease_seconds") == 7.5 for p in params), (
        f"the configured lease never reached the statement: {params}"
    )
    assert any(p.get("failed_requeue_seconds") == 12.5 for p in params), (
        f"the configured failed-row cool-down never reached the statement: {params}"
    )


# ---------------------------------------------------------------- DB-gated ---


@pytest.fixture
async def engine(db_url: str):
    eng = create_async_engine(
        db_url, pool_pre_ping=True, connect_args={"statement_cache_size": 0}
    )
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def relay_env(engine):
    """A committed tenant + a helper that stages real outbox rows.

    Rows are committed (not savepointed) because the whole point is that a
    second connection can see and race for them.
    """
    tenant_id = uuid.uuid4()
    made_ids: list[str] = []
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as seed, seed.begin():
        await seed.execute(
            text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'Claim race')"),
            {"id": str(tenant_id), "slug": f"g08-{uuid.uuid4().hex[:10]}"},
        )

    async def stage(count: int, *, age_seconds: int = 0, status: str = "pending") -> list[str]:
        ids: list[str] = []
        for n in range(count):
            values = _row_values(tenant_id=tenant_id, n=n, age_seconds=age_seconds)
            values["status"] = status
            ids.append(values["id"])
            made_ids.append(values["id"])
            async with factory() as s, s.begin():
                await bind_tenant(s, tenant_id)
                await s.execute(_INSERT_OUTBOX_SQL, values)
        return ids

    try:
        yield {"tenant_id": tenant_id, "stage": stage, "factory": factory}
    finally:
        async with factory() as clean, clean.begin():
            if made_ids:
                await clean.execute(
                    text("DELETE FROM outbox_events WHERE id = ANY(CAST(:ids AS uuid[]))"),
                    {"ids": made_ids},
                )
        async with factory() as clean, clean.begin():
            await clean.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})


_INSERT_OUTBOX_SQL = text(
    "INSERT INTO outbox_events "
    "(id, aggregate_type, aggregate_id, stream, payload, meta, status, created_at) "
    "VALUES (:id, 'order', :agg, 'order.events', "
    "        CAST(:payload AS jsonb), CAST(:meta AS jsonb), :status, "
    "        now() - make_interval(secs => :age))"
)


def _row_values(*, tenant_id: uuid.UUID, n: int, age_seconds: int) -> dict[str, Any]:
    """One staged row, derived from a SINGLE (row_id, agg_id, occurred_at).

    The columns and the §19 envelope in ``meta`` are built together so they
    cannot disagree — the relay reads the envelope, not the columns, and event_log
    keys on the row id. ``occurred_at`` is the row's own age, matching
    ``created_at``.
    """
    import json
    from datetime import UTC, datetime, timedelta

    row_id = uuid.uuid4()
    agg_id = uuid.uuid4()
    occurred_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return {
        "id": str(row_id),
        "agg": str(agg_id),
        "payload": json.dumps({"event_type": "order.created", "n": n}),
        "meta": json.dumps(
            {
                "type": "order.created",
                "schema_version": 2,
                "tenant_id": str(tenant_id),
                "aggregate_type": "order",
                "aggregate_id": str(agg_id),
                "occurred_at": occurred_at.isoformat(),
                # The consumer-inbox dedupe key the writer stamps (§127).
                "outbox_id": str(row_id),
            }
        ),
        "status": "pending",
        "age": age_seconds,
    }


async def _statuses(factory: async_sessionmaker, ids: list[str]) -> dict[str, str]:
    async with factory() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT id::text AS id, status, attempts FROM outbox_events "
                    "WHERE id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": ids},
            )
        ).mappings()
        return {r.id: r.status for r in rows}


def _sessions_per_task():
    """Route ``outbox.SessionLocal`` to a per-task sessionmaker.

    The relay opens its own session by name, so patching one factory gives every
    relay the same connection — and a claim race needs two real connections
    running at the same time. Each relay task carries its own factory in a
    ContextVar, which ``create_task`` copies into the task.
    """
    current: contextvars.ContextVar = contextvars.ContextVar("relay_sessions")

    class _Factory:
        def __call__(self):
            return current.get()()

    return current, _Factory()


@pytest.fixture
def relay_on_own_connection(monkeypatch):
    """Patch the relay's session factory so each task can be given its own."""
    from app.core.events import outbox as outbox_module

    current, factory = _sessions_per_task()
    monkeypatch.setattr(outbox_module, "SessionLocal", factory)
    return current


async def test_relay_that_dies_mid_batch_does_not_strand_its_other_rows(
    engine, relay_env, relay_on_own_connection
):
    """G-08 (i/iii): a claim must die with the relay that took it.

    The batch claim committed the whole batch at the first per-row commit, so
    every row the dead relay had NOT yet published stayed durably 'publishing'
    — invisible to the claim (which selects 'pending') and stranded until the
    lease expired. The correct outcome is the opposite: the event is never
    lost, because the crashed relay's claim rolls back and a live relay takes
    it immediately, with no lease wait and no double publish.
    """
    factory = relay_env["factory"]
    [first, second] = await relay_env["stage"](2, age_seconds=60)

    bus = RecordingBus()
    bus.raise_on_call = 2  # dies on the way to publishing the second row

    relay_on_own_connection.set(async_sessionmaker(engine, expire_on_commit=False))
    relay = OutboxRelay(bus)
    with pytest.raises(RelayProcessDied):
        await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    # The dead relay's unpublished row is NOT stranded in 'publishing'.
    statuses = await _statuses(factory, [first, second])
    assert statuses[first] == "published", "the completed publish was rolled back"
    assert statuses[second] == "pending", (
        f"a crashed relay's claim was committed: {statuses[second]!r}"
    )

    # A fresh relay publishes it at once — nothing was lost, and it is the
    # FIRST time this event goes out. Filtered to this test's own rows: the
    # claim has no tenant predicate, so a shared CI database may hold others.
    bus2 = RecordingBus()
    relay_on_own_connection.set(async_sessionmaker(engine, expire_on_commit=False))
    await OutboxRelay(bus2)._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    mine = {first, second}
    assert [i for i in bus2.ids() if i in mine] == [second]
    assert [i for i in bus.ids() if i in mine] == [first]
    assert sorted(i for i in bus.ids() + bus2.ids() if i in mine) == sorted(
        [first, second]
    ), "an event was published twice across the crash"


async def test_two_concurrent_relays_never_work_the_same_row(
    engine, relay_env, relay_on_own_connection
):
    """G-08 (i): a LIVE relay's in-flight row must not be taken by another.

    Relay A publishes with a blocking bus, so its claim transaction is still
    open while relay B drains the same table. B must move on: today its reclaim
    is a plain UPDATE with no SKIP LOCKED and an age predicate keyed on
    ``created_at``, so against a backlog of rows older than the lease it blocks
    on (and after the first batch commit, steals) A's in-flight rows.
    """
    ids = await relay_env["stage"](2, age_seconds=900)  # 15 min: past any lease

    bus_a = RecordingBus()
    bus_a.gate = asyncio.Event()
    bus_a.entered = asyncio.Event()
    bus_b = RecordingBus()

    task_a: asyncio.Task | None = None

    async def drain_a() -> int:
        relay_on_own_connection.set(async_sessionmaker(engine, expire_on_commit=False))
        return await OutboxRelay(bus_a)._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    async def drain_b() -> int:
        relay_on_own_connection.set(async_sessionmaker(engine, expire_on_commit=False))
        # B runs while A holds its claim open, and must return promptly.
        return await OutboxRelay(bus_b)._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    try:
        task_a = asyncio.create_task(drain_a())
        await asyncio.wait_for(bus_a.entered.wait(), timeout=10)

        published_b = await asyncio.wait_for(drain_b(), timeout=5)

        bus_a.gate.set()
        published_a = await asyncio.wait_for(task_a, timeout=10)

        factory = relay_env["factory"]
        statuses = await _statuses(factory, ids)
        assert statuses == {i: "published" for i in ids}, statuses
        # Both relays did real work while the other was in flight (B returned
        # inside its timeout instead of blocking on A's claim).
        assert published_a >= 1 and published_b >= 1, (published_a, published_b)
        # THE invariant: every staged event reached the stream exactly once,
        # with the two relays running over the same table at the same time.
        # Filtered to this test's rows — the claim has no tenant predicate.
        both = [i for i in bus_a.ids() + bus_b.ids() if i in set(ids)]
        assert sorted(both) == sorted(ids), f"duplicate or lost publish: {both}"
    finally:
        if bus_a.gate is not None:
            bus_a.gate.set()
        if task_a is not None and not task_a.done():
            task_a.cancel()
        await asyncio.gather(*(t for t in [task_a] if t is not None), return_exceptions=True)


async def test_lease_expiry_comes_from_config_and_requeues_a_stranded_row(
    engine, relay_env, relay_on_own_connection, monkeypatch
):
    """G-08 (ii): an expired lease is claimable again — at the CONFIGURED age.

    A row committed in 'publishing' with nothing holding it is a relay that
    died. With the lease at 60s a row stranded 90s ago goes back out and a row
    stranded 10s ago does not; a hardcoded 300s makes both statements false.
    """
    from app.core.events import outbox as outbox_module

    class _Settings:
        outbox_lease_seconds = 60.0
        outbox_failed_requeue_seconds = 60.0

    monkeypatch.setattr(outbox_module, "get_settings", lambda: _Settings())
    factory = relay_env["factory"]

    [stale] = await relay_env["stage"](1, age_seconds=90, status="publishing")
    [fresh] = await relay_env["stage"](1, age_seconds=10, status="publishing")

    relay_on_own_connection.set(async_sessionmaker(engine, expire_on_commit=False))
    bus = RecordingBus()
    await OutboxRelay(bus)._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    assert stale in bus.ids(), "a row past its lease was not made claimable again"
    assert fresh not in bus.ids(), "a row inside its lease was stolen"
    statuses = await _statuses(factory, [stale, fresh])
    assert statuses[fresh] == "publishing"


async def test_a_row_published_and_marked_done_is_never_republished(
    engine, relay_env, relay_on_own_connection
):
    """G-08 (iii) pin: 'published' is terminal — aging it must not resurrect it.

    This holds today and MUST keep holding: the reclaim and the claim may never
    select a completed row, or every lease expiry becomes a re-send.
    """
    factory = relay_env["factory"]
    [row_id] = await relay_env["stage"](1)

    relay_on_own_connection.set(async_sessionmaker(engine, expire_on_commit=False))
    bus = RecordingBus()
    await OutboxRelay(bus)._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)
    assert [i for i in bus.ids() if i == row_id] == [row_id]

    # Push it far past any lease and drain again with a fresh relay.
    async with factory() as s, s.begin():
        await s.execute(
            text("UPDATE outbox_events SET created_at = now() - interval '2 hours' "
                 "WHERE id = :i"),
            {"i": row_id},
        )

    relay_on_own_connection.set(async_sessionmaker(engine, expire_on_commit=False))
    bus2 = RecordingBus()
    await OutboxRelay(bus2)._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    assert [i for i in bus2.ids() if i == row_id] == [], "a published row was re-published"
    assert (await _statuses(factory, [row_id]))[row_id] == "published"
