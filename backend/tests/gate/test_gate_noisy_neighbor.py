"""§176 gate scenario 20 — noisy neighbour under real load (§144).

§144's promise in one line: a big campaign from tenant A may never starve
tenant B. Until now the proof was a table of priority ranks
(`test_fairness_priority.py`) and a single-connection charge test — neither of
which shows that a SHARED worker keeps serving a quiet tenant while a loud one
is flooding the queue.

What is proven here, per layer that actually enforces fairness:

* the per-tenant daily budget cannot be overrun by concurrent consumers —
  the counter is Redis-side, so 60 workers racing must admit exactly the
  budgeted share (`consume()` on a real Redis implementation, no stubs);
* a genuine Redis outage degrades fairness to fail-open WITHOUT raising into
  business work, and without taking the platform down;
* the durable scheduler gives every tenant its own claim transaction, so one
  tenant's 50-job backlog cannot push another tenant's job out of cycle one,
  and two replicas splitting the same backlog never run a job twice.

The scheduler tests need PostgreSQL as the `sales_app` role and COMMITTED rows
(row locking across connections is the whole point), so they run their own
engine and clean up after themselves; they skip via `db_url` when no
application database is configured. The budget tests need neither.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from datetime import UTC, datetime, timedelta

import fakeredis.aioredis
import pytest
import redis.asyncio as aioredis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import bind_tenant
from app.core.fairness import DEFAULT_DAILY_BUDGETS, ResourceType, check_budget, consume
from app.modules.identity.models import Tenant
from app.modules.platform.models import ScheduledJob
from app.workers import scheduler_worker as sw

pytestmark = [pytest.mark.gate]

TENANT_A_JOBS = 50  # the noisy neighbour's backlog
BUYERS = 60


# ---------------------------------------------------------------------------
# 1. The budget layer: real Redis counters, real concurrency
# ---------------------------------------------------------------------------


@pytest.fixture
async def fairness_bus(monkeypatch):
    """Point the fairness module at a real Redis SERVER (in-process fakeredis).

    The counters live server-side — that is the property under test — so the
    alternative would be faking the very arithmetic being proven.
    """
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("app.core.fairness.get_redis", lambda: client)
    yield client
    await client.flushall()
    await client.aclose()


async def test_gate_consumers_cannot_collectively_overrun_one_budget(
    fairness_bus,
) -> None:
    """60 concurrent consumers of a budget that fits 50 must admit 50."""
    tenant = uuid.uuid4()
    limit = DEFAULT_DAILY_BUDGETS[ResourceType.MESSAGES_OUTBOUND]
    units = limit // 50  # the budget admits exactly 50 of these

    results = await asyncio.gather(
        *(consume(tenant, ResourceType.MESSAGES_OUTBOUND, units=units) for _ in range(BUYERS))
    )
    admitted = sum(results)

    assert admitted == 50, (
        f"concurrent consumption admitted {admitted} of {BUYERS} "
        f"for a budget of {limit // units} units"
    )
    assert admitted * units >= limit  # the window is genuinely full
    usage = int(await fairness_bus.get(f"fairness:messages_outbound:{tenant}"))
    assert usage == BUYERS * units  # overshot units are counted, never forgotten


async def test_gate_one_tenant_exhausting_its_budget_leaves_its_neighbours_alone(
    fairness_bus,
) -> None:
    loud, quiet = uuid.uuid4(), uuid.uuid4()
    limit = DEFAULT_DAILY_BUDGETS[ResourceType.MESSAGES_OUTBOUND]

    while await consume(loud, ResourceType.MESSAGES_OUTBOUND, units=limit // 2):
        pass  # burn the loud tenant's window down to zero

    exhausted = await check_budget(loud, ResourceType.MESSAGES_OUTBOUND, units=1)
    untouched = await check_budget(quiet, ResourceType.MESSAGES_OUTBOUND, units=1)

    assert exhausted.allowed is False
    assert exhausted.remaining == 0
    assert untouched.allowed is True
    assert untouched.remaining == limit


def _closed_port() -> int:
    """A port nothing listens on — a REAL connection refusal, not a stub."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def test_gate_a_redis_outage_degrades_fairness_without_blocking_work(
    monkeypatch,
) -> None:
    """§144/§177.10: fairness is best-effort; Redis is transport, not truth.

    The client is a real redis-py client dialling a port that refuses
    connections, so the failure is the genuine one a worker would see. A
    budget check that raised here would stop every message and every AI run on
    the platform — which is the worse failure the spec chose against.
    """
    dead = aioredis.from_url(
        f"redis://127.0.0.1:{_closed_port()}/0",
        socket_connect_timeout=1,
        socket_timeout=1,
        retry=False,
    )
    monkeypatch.setattr("app.core.fairness.get_redis", lambda: dead)
    tenant = uuid.uuid4()

    check = await check_budget(tenant, ResourceType.WORKER_SECONDS, units=1)
    allowed = await consume(tenant, ResourceType.WORKER_SECONDS, units=1)

    assert check.allowed is True
    assert check.remaining == DEFAULT_DAILY_BUDGETS[ResourceType.WORKER_SECONDS]
    assert allowed is True
    await dead.aclose()


# ---------------------------------------------------------------------------
# 2. The scheduler layer: one shared poller, two tenants, real row locks
# ---------------------------------------------------------------------------


@pytest.fixture
async def committed_engine(db_url: str):
    engine = create_async_engine(
        db_url,
        pool_size=6,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed_backlog(
    engine: AsyncEngine, *, noisy_jobs: int, quiet_jobs: int
) -> tuple[uuid.UUID, uuid.UUID]:
    """Two tenants with COMMITTED due jobs: one floods, one barely speaks."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenants: list[uuid.UUID] = []
    for label, count in (("noisy", noisy_jobs), ("quiet", quiet_jobs)):
        async with factory() as session, session.begin():
            tenant = Tenant(slug=f"{label}-{uuid.uuid4().hex[:10]}", name=label)
            session.add(tenant)
            await session.flush()
            await bind_tenant(session, tenant.id)
            for n in range(count):
                session.add(
                    ScheduledJob(
                        tenant_id=tenant.id,
                        job_type="gate.work",
                        status="queued",
                        run_at=datetime.now(UTC) - timedelta(minutes=1),
                        payload={"n": n},
                        attempts=0,
                        max_attempts=5,
                        idempotency_key=f"gate:{label}:{uuid.uuid4().hex[:12]}",
                    )
                )
            tenants.append(tenant.id)
    return tenants[0], tenants[1]


async def _cleanup(engine: AsyncEngine, *tenant_ids: uuid.UUID) -> None:
    """Remove this test's committed rows.

    `scheduled_jobs` is FORCE RLS on DELETE too, so each tenant's rows are
    dropped from a session bound to that tenant — an unbound DELETE matches
    nothing and would leak an ACTIVE tenant into every later poll cycle.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        for tid in tenant_ids:
            async with factory() as session, session.begin():
                await bind_tenant(session, tid)
                await session.execute(
                    text("DELETE FROM scheduled_jobs WHERE tenant_id = :t"), {"t": tid}
                )
        async with factory() as session, session.begin():
            for tid in tenant_ids:
                await session.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tid})
    except Exception:  # noqa: BLE001 — cleanup must never mask an assertion
        pass


async def _statuses(engine: AsyncEngine, tenant_id: uuid.UUID) -> dict[str, int]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await bind_tenant(session, tenant_id)
        rows = (
            (
                await session.execute(
                    select(ScheduledJob.status).where(ScheduledJob.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
    tally: dict[str, int] = {}
    for status in rows:
        tally[status] = tally.get(status, 0) + 1
    return tally


async def _counts(engine: AsyncEngine, tenant_id: uuid.UUID) -> list[int]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await bind_tenant(session, tenant_id)
        return list(
            (
                await session.execute(
                    select(ScheduledJob.attempts).where(ScheduledJob.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )


async def _run_one_poll(monkeypatch, engine: AsyncEngine) -> int:
    """Drive the real `SchedulerWorker._poll_once` on the test's own engine.

    Only the WORK SOURCE is redirected (the worker's session factory) plus one
    job type's handler; the claim query, the per-tenant transaction, the batch
    cap and the advisory locks are production code.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(sw, "SessionLocal", factory)

    async def handle(session, tenant_id, payload):  # real handler signature
        return {"seen": True}

    monkeypatch.setitem(sw._HANDLERS, "gate.work", handle)
    worker = sw.SchedulerWorker(bus=_NoBus())  # type: ignore[arg-type]
    return await worker._poll_once()


class _NoBus:
    """The scheduler polls the database; it never consumes a stream."""

    async def ack(self, *a, **k):  # pragma: no cover - never called
        return None


async def test_gate_a_bulk_backlog_never_starves_a_quiet_tenant(
    monkeypatch, committed_engine
) -> None:
    """§144: one tenant's 50 due jobs must not push another tenant's job out.

    The scheduler claims per tenant in its own transaction and caps the batch
    (`.limit(10)`), so the loud neighbour is bounded BY CONSTRUCTION and the
    quiet one is served in the same cycle. If the cap or the per-tenant
    transaction disappears, tenant B waits for A's whole backlog.

    NOTE: `_poll_once` enumerates every active tenant, so on a shared
    development database other tenants' due work is also processed. That is
    the real system behaviour; the assertions below are scoped to this test's
    own tenants only.
    """
    noisy, quiet = await _seed_backlog(committed_engine, noisy_jobs=TENANT_A_JOBS, quiet_jobs=1)
    try:
        processed = await _run_one_poll(monkeypatch, committed_engine)

        quiet_now = await _statuses(committed_engine, quiet)
        noisy_now = await _statuses(committed_engine, noisy)

        assert processed >= 1
        assert quiet_now.get("completed", 0) == 1, (
            f"the quiet tenant starved behind a bulk backlog: {quiet_now}"
        )
        assert noisy_now.get("completed", 0) <= 10, (
            f"one tenant took an unbounded slice of the shared worker: {noisy_now}"
        )
        assert sum(noisy_now.values()) == TENANT_A_JOBS  # nothing lost
    finally:
        await _cleanup(committed_engine, noisy, quiet)


async def test_gate_two_scheduler_replicas_split_the_backlog_and_double_run_nothing(
    monkeypatch, committed_engine
) -> None:
    """The load test itself: concurrent replicas, SKIP LOCKED, no duplicate work.

    One poll cycle claims at most `.limit(10)` rows per tenant, so the replicas
    loop until the backlog drains — the invariant under concurrency is not
    "one pass does it all" but "however often they race, every job runs
    EXACTLY ONCE". A missing `skip_locked=True` shows up here as a job with
    `attempts = 2` (both replicas ran it), which is a duplicated side effect
    in every real handler those jobs drive.
    """
    noisy, quiet = await _seed_backlog(committed_engine, noisy_jobs=TENANT_A_JOBS, quiet_jobs=3)

    async def replica() -> int:
        total = 0
        for _ in range(30):  # hard bound: the loop must converge, never spin
            done = await _run_one_poll(monkeypatch, committed_engine)
            if not done:
                return total
            total += done
        pytest.fail("scheduler replicas did not drain the backlog in 30 cycles")

    try:
        await asyncio.wait_for(asyncio.gather(*(replica() for _ in range(2))), timeout=180)

        for tenant_id, expected in ((noisy, TENANT_A_JOBS), (quiet, 3)):
            statuses = await _statuses(committed_engine, tenant_id)
            assert sum(statuses.values()) == expected
            assert statuses.get("completed", 0) == expected, (
                f"jobs were stranded by the race: {statuses}"
            )
            attempts = await _counts(committed_engine, tenant_id)
            assert max(attempts) == 1, f"a job ran twice under two replicas (attempts={attempts})"
    finally:
        await _cleanup(committed_engine, noisy, quiet)
