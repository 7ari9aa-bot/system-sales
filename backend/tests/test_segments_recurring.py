"""§82 closure — a producer for the `segments.materialize` job handler.

The measurement (2026-09-24): the handler was REAL (``job_runner`` registers
``segments.materialize`` and the ``JobRunner`` service polls the ``jobs``
table), and marketing consumes segments at read time — but NOTHING ever
INSERTED a row of that kind. ``JobService.create`` had zero production callers;
the only ``segments.materialize`` jobs in existence were the ones the tests
built. In production the recompute had never run and could not: the exact
"built, tested in isolation, never called" failure named in
docs/ROADMAP_TO_90.md Wave C.

The fix is one recurring sweep in the scheduler's OFFICIAL recurring-job
table (``RECURRING_JOBS``, seeded per tenant by ``ensure_recurring_jobs``):
``segments.recompute`` ENQUEUES a ``segments.materialize`` job — it does not
do the heavy work itself, because that belongs to the §84 Job system where
progress, retries and the operations job views apply. It also refuses to pile
a second pending job on top of an unfinished one.

Registry assertions are DB-free (they fail locally); the enqueue behaviour
needs ``DATABASE_URL_APP_ADMIN`` and is proven in CI.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.modules.platform.models import Job
from app.workers.job_runner import registered_job_kinds
from app.workers.scheduler_worker import _HANDLERS, RECURRING_JOBS

SWEEP = "segments.recompute"
HEAVY_KIND = "segments.materialize"


# ---------------------------------------------------------------------------
# 1. DB-free: the sweep exists and is wired end-to-end.
# ---------------------------------------------------------------------------


def test_segment_recompute_is_a_recurring_sweep() -> None:
    assert SWEEP in RECURRING_JOBS, (
        "§82's recompute is only real if something schedules it — "
        "RECURRING_JOBS is the scheduler's official sweep table"
    )


def test_segment_recompute_has_a_registered_handler() -> None:
    assert SWEEP in _HANDLERS, f"{SWEEP} is in RECURRING_JOBS but has no handler"


def test_the_sweep_enqueues_a_kind_the_job_runner_actually_handles() -> None:
    """The producer must speak the consumer's vocabulary, not a new string."""
    assert HEAVY_KIND in registered_job_kinds(), (
        "job_runner no longer registers 'segments.materialize' — the sweep "
        "would enqueue jobs nothing runs"
    )


# ---------------------------------------------------------------------------
# 2. DB-backed (CI): the sweep creates real, claimable job rows.
# ---------------------------------------------------------------------------


async def _jobs_for(db, tenant_id) -> list[Job]:
    return list(
        (
            await db.execute(
                select(Job).where(Job.tenant_id == tenant_id, Job.kind == HEAVY_KIND)
            )
        )
        .scalars()
        .all()
    )


async def test_the_sweep_enqueues_a_queued_materialize_job(db, tenant_ctx) -> None:
    result = await _HANDLERS[SWEEP](db, tenant_ctx.tenant_id, {})

    assert result.get("kind") == HEAVY_KIND
    jobs = await _jobs_for(db, tenant_ctx.tenant_id)
    assert len(jobs) == 1, f"expected one enqueued job, got {jobs}"
    assert jobs[0].status == "queued", "the runner claims queued rows"
    assert str(jobs[0].id) == result["job_id"]


async def test_a_pending_run_is_not_doubled_up(db, tenant_ctx) -> None:
    """Six hours later the sweep fires again; an unfinished job must not stack."""
    await _HANDLERS[SWEEP](db, tenant_ctx.tenant_id, {})
    second = await _HANDLERS[SWEEP](db, tenant_ctx.tenant_id, {})

    assert second.get("skipped") == "pending"
    assert len(await _jobs_for(db, tenant_ctx.tenant_id)) == 1


async def test_a_finished_run_is_followed_by_a_new_job(db, tenant_ctx) -> None:
    first = await _HANDLERS[SWEEP](db, tenant_ctx.tenant_id, {})
    job = (
        await db.execute(select(Job).where(Job.id == uuid.UUID(first["job_id"])))
    ).scalar_one()
    job.status = "completed"
    await db.flush()

    again = await _HANDLERS[SWEEP](db, tenant_ctx.tenant_id, {})
    assert "skipped" not in again
    assert len(await _jobs_for(db, tenant_ctx.tenant_id)) == 2
