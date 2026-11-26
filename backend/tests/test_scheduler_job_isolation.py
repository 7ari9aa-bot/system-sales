"""One failing job must not stop the rest of its per-tenant batch.

Production symptom this pins: ``scheduled_jobs`` held 836 rows (44 tenants x 19
recurring sweeps) all at ``status='queued'``, ``attempts=0`` and an EMPTY
``last_error``, while the worker logged ``scheduler.poll_failed`` every ~7s with
``InFailedSQLTransactionError`` on ``pg_try_advisory_xact_lock``.

Cause: the whole batch ran in ONE transaction. A handler that raised a database
error aborted that transaction, so the next job's advisory lock died with
"current transaction is aborted", the outer ``session.begin()`` rolled back, and
nothing at all was recorded — no attempts, no error, no progress. Every poll
re-claimed the same broken job first and failed identically, forever.

The fix is a SAVEPOINT per job: the failing job's work rolls back alone, its
``last_error``/``attempts`` are kept, and the remaining jobs still run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import ScheduledJob
from app.workers import scheduler_worker as sw


class _NoBus:
    def __getattr__(self, name):  # pragma: no cover - defensive stub
        async def _noop(*a, **k):
            return None

        return _noop


async def _due_job(
    db: AsyncSession, tenant_id: uuid.UUID, job_type: str, key: str
) -> ScheduledJob:
    job = ScheduledJob(
        tenant_id=tenant_id,
        job_type=job_type,
        status="queued",
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        payload={},
        attempts=0,
        max_attempts=5,
        idempotency_key=f"isolation:{key}:{tenant_id}",
    )
    db.add(job)
    await db.flush()
    return job


async def test_a_database_error_in_one_job_does_not_stop_the_batch(
    db: AsyncSession, tenant_ctx
) -> None:
    broken, healthy = "probe.broken_sweep", "probe.healthy_sweep"

    async def _broken(session, tenant_id, payload):
        # A real DB error, not a Python one: this is what aborted the transaction.
        await session.execute(text("SELECT * FROM table_that_does_not_exist"))
        return {}

    async def _healthy(session, tenant_id, payload):
        return {"ok": True}

    sw._HANDLERS[broken] = _broken
    sw._HANDLERS[healthy] = _healthy
    try:
        bad = await _due_job(db, tenant_ctx.tenant_id, broken, "bad")
        good = await _due_job(db, tenant_ctx.tenant_id, healthy, "good")
        worker = sw.SchedulerWorker(bus=_NoBus())  # type: ignore[arg-type]

        assert await worker._drain_tenant(db, tenant_ctx.tenant_id) == 2

        rows = {
            r.id: r
            for r in (
                await db.execute(
                    select(ScheduledJob)
                    .where(ScheduledJob.id.in_([bad.id, good.id]))
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        }
        assert rows[bad.id].last_error, "the failing job's error must be persisted"
        assert rows[bad.id].attempts == 1
        assert rows[bad.id].status == "retrying"
        assert rows[good.id].status == "completed", rows[good.id].last_error
        assert rows[good.id].result == {"ok": True}
    finally:
        sw._HANDLERS.pop(broken, None)
        sw._HANDLERS.pop(healthy, None)
