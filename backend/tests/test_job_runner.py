"""Job runner tests (§84) — the executor behind the Job control surface.

Three groups:

* **DB-free** — the handler registry contract (including that a REAL handler is
  registered, so the runner is not inert) and the pure retry/error rules.
* **DB-backed** — the claim is exclusive across connections, a job runs to
  completion and records its result, a cancelled job is never overwritten, an
  unknown kind fails, and a *database* error from a handler still records the
  failure and still increments the attempt counter.
* **The real handler** — ``segments.materialize`` actually recomputes segments
  and writes a real result, so the registry is demonstrably non-empty.

Handlers are registered per-test; an autouse fixture snapshots and restores the
module registry so a test can never leak a handler into another (and the real
handler survives every test).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import bind_tenant
from app.modules.platform.models import Job
from app.modules.platform.service import JobService
from app.workers.job_runner import (
    _JOB_HANDLERS,
    JobRunner,
    claim_jobs,
    error_text,
    failure_status,
    get_job_handler,
    register_job_handler,
    registered_job_kinds,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Restore the global handler registry after every test."""
    saved = dict(_JOB_HANDLERS)
    yield
    _JOB_HANDLERS.clear()
    _JOB_HANDLERS.update(saved)


def _runner() -> JobRunner:
    return JobRunner(bus=None)


# ------------------------------------------------------- registry (DB-free) --


def test_the_runner_has_a_real_handler_registered() -> None:
    """The registry must not be empty, or the pool can only ever fail work."""
    assert registered_job_kinds(), "no handler is registered — the runner is inert"
    assert "segments.materialize" in registered_job_kinds()


def test_registering_a_handler_makes_it_resolvable() -> None:
    @register_job_handler("test.registry")
    async def _handler(session, job):  # pragma: no cover - not executed here
        return {"ok": True}

    assert get_job_handler("test.registry") is _handler
    assert "test.registry" in registered_job_kinds()


def test_an_unknown_kind_has_no_handler() -> None:
    """The runner must be able to tell "not implemented" from "transient"."""
    assert get_job_handler("test.no.such.kind") is None


def test_a_later_registration_replaces_the_earlier_one() -> None:
    @register_job_handler("test.replace")
    async def _first(session, job):  # pragma: no cover
        return None

    @register_job_handler("test.replace")
    async def _second(session, job):  # pragma: no cover
        return None

    assert get_job_handler("test.replace") is _second


def test_the_job_pool_is_registered() -> None:
    from app.workers.run import POOLS

    assert POOLS["jobs"] is JobRunner


# ---------------------------------------------------------- rules (DB-free) --


def test_a_failure_retries_until_the_budget_is_spent() -> None:
    assert failure_status(1, 3) == "retrying"
    assert failure_status(2, 3) == "retrying"
    assert failure_status(3, 3) == "failed"
    # Never retry past the budget even if attempts somehow overshoots.
    assert failure_status(4, 3) == "failed"
    assert failure_status(1, 1) == "failed"


def test_error_text_names_the_exception_type_and_is_bounded() -> None:
    assert error_text(ValueError("boom")) == "ValueError: boom"
    assert len(error_text(ValueError("x" * 5000))) == 500


# ------------------------------------------------------- helpers (DB-backed) --


def _job(tenant_id: uuid.UUID, kind: str, **overrides) -> Job:
    return Job(tenant_id=tenant_id, kind=kind, **overrides)


async def _reload(db: AsyncSession, job_id: uuid.UUID) -> Job:
    return (
        await db.execute(
            select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_job_service_creates_a_queued_job(db, tenant_ctx):
    """A Job row must be creatable — otherwise nothing can ever be run."""
    job = await JobService.create(
        db,
        tenant_ctx.tenant_id,
        kind="segments.materialize",
        actor_user_id=tenant_ctx.user.id,
    )
    await db.flush()

    assert job.status == "queued"
    assert job.progress == 0
    assert job.attempts == 0
    assert job.actor_user_id == tenant_ctx.user.id


async def test_a_queued_job_runs_to_completion_and_records_its_result(db, tenant_ctx):
    @register_job_handler("test.echo")
    async def _echo(session, job):
        return {"echo": str(job.id)}

    job = await JobService.create(db, tenant_ctx.tenant_id, kind="test.echo")
    await db.flush()

    runner = _runner()
    claimed = await runner.claim_for_tenant(db, tenant_ctx.tenant_id)
    assert [j.id for j in claimed] == [job.id]
    assert await runner.execute_claimed(db, tenant_ctx.tenant_id, job.id) is True

    stored = await _reload(db, job.id)
    assert stored.status == "completed"
    assert stored.progress == 100
    assert stored.attempts == 1
    assert stored.result == {"echo": str(job.id)}
    assert stored.last_error is None


async def test_a_cancelled_job_is_not_marked_successful(db, tenant_ctx):
    """The cancel lands WHILE the handler runs — the real race, not a setup."""

    @register_job_handler("test.cancel_during")
    async def _cancel_during(session, job):
        # A user cancels the job mid-run, then the handler finishes anyway.
        await session.execute(
            update(Job).where(Job.id == job.id).values(status="cancelled")
        )
        return {"finished": True}

    job = await JobService.create(db, tenant_ctx.tenant_id, kind="test.cancel_during")
    await db.flush()

    runner = _runner()
    claimed = await runner.claim_for_tenant(db, tenant_ctx.tenant_id)
    assert claimed[0].status == "processing"

    # The handler cancels during execution and returns success; the runner must
    # NOT overwrite the cancellation with "completed".
    await runner.execute_job(db, claimed[0])

    stored = await _reload(db, job.id)
    assert stored.status == "cancelled"
    assert stored.result is None


async def test_an_unknown_kind_fails_rather_than_staying_queued(db, tenant_ctx):
    job = await JobService.create(db, tenant_ctx.tenant_id, kind="test.unimplemented")
    await db.flush()

    runner = _runner()
    claimed = await runner.claim_for_tenant(db, tenant_ctx.tenant_id)
    await runner.execute_job(db, claimed[0])

    stored = await _reload(db, job.id)
    assert stored.status == "failed"
    assert stored.last_error is not None
    assert "no handler" in stored.last_error


async def test_a_database_error_is_recorded_and_still_counts_as_an_attempt(
    db, tenant_ctx
):
    """A handler that poisons its transaction must not re-queue at attempts=0.

    The handler raises a genuine DB-level error (a duplicate primary key). If
    the claim shared the handler's transaction, the IntegrityError would abort
    it and roll the ``attempts`` increment back — the job would be re-claimed
    forever at ``attempts=0``. The claim commits separately and the handler runs
    in a savepoint, so the attempt survives and the failure is written.
    """

    @register_job_handler("test.db_error")
    async def _db_error(session, job):
        await session.execute(
            text("INSERT INTO jobs (id, tenant_id, kind) VALUES (:id, :tid, 'dup')"),
            {"id": str(job.id), "tid": str(job.tenant_id)},
        )

    job = await JobService.create(
        db, tenant_ctx.tenant_id, kind="test.db_error", max_attempts=2
    )
    await db.flush()

    runner = _runner()

    # First attempt: the DB error is caught, recorded, and the attempt counted.
    claimed = await runner.claim_for_tenant(db, tenant_ctx.tenant_id)
    assert claimed[0].attempts == 1
    await runner.execute_job(db, claimed[0])  # must NOT raise
    stored = await _reload(db, job.id)
    assert stored.attempts == 1, "the attempt was lost — job would re-queue forever"
    assert stored.status == "retrying"
    assert stored.last_error is not None
    assert "IntegrityError" in stored.last_error

    # Second attempt exhausts the budget and stops — it does not loop.
    claimed = await runner.claim_for_tenant(db, tenant_ctx.tenant_id)
    assert claimed[0].attempts == 2
    await runner.execute_job(db, claimed[0])
    stored = await _reload(db, job.id)
    assert stored.attempts == 2
    assert stored.status == "failed"

    assert await claim_jobs(db, tenant_ctx.tenant_id, 10) == []


async def test_a_suspended_tenant_job_is_deferred_not_run(db, tenant_ctx):
    from app.modules.identity.models import Tenant

    @register_job_handler("test.suspended")
    async def _handler(session, job):  # pragma: no cover - must not run
        raise AssertionError("a suspended tenant's job must not run")

    job = await JobService.create(db, tenant_ctx.tenant_id, kind="test.suspended")
    await db.flush()

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    tenant.lifecycle_state = "suspended"
    await db.flush()

    assert await _runner().claim_for_tenant(db, tenant_ctx.tenant_id) == []

    stored = await _reload(db, job.id)
    assert stored.status == "queued"
    assert stored.attempts == 0


# --------------------------------------------------- the real handler --------


async def test_the_segment_handler_recomputes_and_records_a_real_result(db, tenant_ctx):
    """Prove the registered handler does real work, not just return a stub."""
    from app.modules.customers.models import Customer
    from app.modules.segments.service import Segment, SegmentService

    db.add(
        Customer(
            tenant_id=tenant_ctx.tenant_id, name="Ada", email="ada@example.com"
        )
    )
    await db.flush()
    segment = await SegmentService.create(
        db,
        tenant_ctx.tenant_id,
        name="Has email",
        definition={"all": [{"field": "has_email", "op": "eq", "value": True}]},
    )
    job = await JobService.create(
        db, tenant_ctx.tenant_id, kind="segments.materialize"
    )
    await db.flush()

    runner = _runner()
    claimed = await runner.claim_for_tenant(db, tenant_ctx.tenant_id)
    assert [j.id for j in claimed] == [job.id]
    await runner.execute_job(db, claimed[0])

    stored = await _reload(db, job.id)
    assert stored.status == "completed"
    assert stored.progress == 100
    assert stored.result == {"segments": 1, "counts": {"Has email": 1}}

    # The handler called the real service, which stamped the evaluation.
    refreshed = (
        await db.execute(
            select(Segment)
            .where(Segment.id == segment.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.last_count == 1
    assert refreshed.last_evaluated_at is not None


# ------------------------------------------------- claim exclusivity ---------


async def test_two_connections_cannot_claim_the_same_job(db_url):
    """The claim is exclusive across connections, not merely within one session.

    Two independent connections race for one committed job. The first holds the
    row lock (its transaction is still open); the second's claim must SKIP the
    locked row and return nothing rather than blocking. Without ``FOR UPDATE
    SKIP LOCKED`` the second claim blocks on the lock forever, so the timeout
    turns that regression into a failure instead of a hung suite.
    """
    engine = create_async_engine(
        db_url, pool_pre_ping=True, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    try:
        # Seed a committed tenant + queued job (RLS needs the tenant to exist).
        async with factory() as seed:
            async with seed.begin():
                await seed.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name) "
                        "VALUES (:id, :slug, 'Claim race')"
                    ),
                    {"id": str(tenant_id), "slug": f"claim-{tenant_id.hex[:12]}"},
                )
                await bind_tenant(seed, tenant_id)
                await seed.execute(
                    text(
                        "INSERT INTO jobs "
                        "(id, tenant_id, kind, status, progress, attempts, max_attempts) "
                        "VALUES (:id, :tid, 'test.race', 'queued', 0, 0, 3)"
                    ),
                    {"id": str(job_id), "tid": str(tenant_id)},
                )

        conn_a = await engine.connect()
        conn_b = await engine.connect()
        try:
            session_a = async_sessionmaker(bind=conn_a, expire_on_commit=False)()
            session_b = async_sessionmaker(bind=conn_b, expire_on_commit=False)()
            await session_a.begin()
            await session_b.begin()
            await bind_tenant(session_a, tenant_id)
            await bind_tenant(session_b, tenant_id)

            # A claims and holds the row lock (transaction not committed).
            claimed_a = await claim_jobs(session_a, tenant_id, 10)
            assert [j.id for j in claimed_a] == [job_id]

            # B must skip the locked row rather than block on it.
            claimed_b = await asyncio.wait_for(
                claim_jobs(session_b, tenant_id, 10), timeout=5
            )
            assert claimed_b == []
        finally:
            await session_a.rollback()
            await session_b.rollback()
            await session_a.close()
            await session_b.close()
            await conn_a.close()
            await conn_b.close()
    finally:
        async with factory() as cleanup:
            async with cleanup.begin():
                await bind_tenant(cleanup, tenant_id)
                await cleanup.execute(
                    text("DELETE FROM jobs WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
                await cleanup.execute(
                    text("DELETE FROM tenants WHERE id = :t"), {"t": str(tenant_id)}
                )
        await engine.dispose()
