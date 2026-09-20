"""Job runner (spec §84) — the executor for the Job control surface.

``jobs`` is the durable record and the control surface only: the API lists,
retries and cancels a job, but for a long time nothing ever RAN one, so every
job a user started sat ``queued`` forever. This worker is the missing runner:
it claims queued rows, dispatches to a handler registered by ``kind``, and
writes ``progress`` / ``status`` / ``result`` / ``last_error`` back.

Claiming
--------
Two workers must never run the same job. The claim is a ``SELECT ... FOR UPDATE
SKIP LOCKED`` over the candidate rows followed by a conditional ``UPDATE ...
WHERE status IN (...) RETURNING`` inside the SAME transaction. The row lock
makes the two statements a single atomic claim — a second worker skips the
locked rows and then finds them already ``processing`` — and the conditional
update re-checks the status so even a lost-lock race cannot double-claim. This
is the mechanism ``message_worker`` uses for QUEUED -> SENDING, for the same
reason: a read-then-write guard lets two concurrent deliveries of one event
both pass and both act.

Transactions — why the claim and the outcome are NOT one transaction
--------------------------------------------------------------------
The claim commits on its own, then each job is executed in a fresh
transaction. A handler that raises a *database* error (an ``IntegrityError``,
say) aborts its transaction; if that transaction also held the claim, the
``attempts`` increment would roll back with it and the job would re-queue
forever at ``attempts=0``. Separating them means the attempt survives the
failure. Inside the execution transaction the handler additionally runs in a
SAVEPOINT, so a poisoned session is rolled back to the savepoint and the
failure can still be written — the same pattern ``message_worker`` uses to
survive a duplicate ``ProcessedEvent`` insert.

Tenancy and RLS
---------------
``jobs`` is tenant-scoped and FORCE RLS, so a cross-tenant SELECT sees nothing
without the tenant GUC bound. Like the retention worker (§125) the runner
enumerates active tenants and claims per tenant, binding ``app.tenant_id`` for
each. A tenant whose lifecycle state forbids automation is skipped through
``defer_unless_tenant_allows`` — its jobs stay ``queued`` and resume if the
tenant is reactivated, rather than being failed or run while suspended.

Status vocabulary (read from the model — no new values)
-------------------------------------------------------
    queued | processing | completed | failed | retrying | cancelled

``queued`` and ``retrying`` are claimable. A handler failure moves the job to
``retrying`` while attempts remain and to ``failed`` once ``max_attempts`` is
reached. A ``kind`` with no registered handler fails immediately with a clear
error instead of sitting queued forever. A cancelled job is never overwritten
with a success: the terminal write is conditional on the row still being
``processing``.

Retries
-------
``jobs`` deliberately has no ``next_attempt_at`` column (that is
``scheduled_jobs``' job), so the runner cannot schedule a durable backoff.
Retries are bounded by ``max_attempts`` and spaced by the poll interval: a
failed job is claimed at most once per poll, so the budget is consumed across
polls rather than in a tight loop.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, bind_tenant
from app.core.events.bus import Event
from app.modules.platform.models import Job
from app.workers.base import (
    DeferredError,
    StreamWorker,
    defer_unless_tenant_allows,
)

logger = logging.getLogger(__name__)

# Statuses the runner may claim. ``retrying`` is the model's own value for a job
# whose previous attempt failed but whose budget is not spent; without it a
# failed job could never be picked up again.
_CLAIMABLE_STATUSES = ("queued", "retrying")

# The tenant capability a job needs. Jobs are background work, so the gate is
# the same one automations use: suspended / offboarding / deleted tenants must
# not have jobs run, and their jobs stay queued instead of failing.
_REQUIRED_CAPABILITY = "allows_automation"

JobHandler = Callable[[AsyncSession, Job], Awaitable[dict | None]]

# kind -> handler. Populated by @register_job_handler at import time, so a new
# job kind is added WITHOUT editing this runner.
_JOB_HANDLERS: dict[str, JobHandler] = {}


def register_job_handler(kind: str) -> Callable[[JobHandler], JobHandler]:
    """Register the handler for a job ``kind``.

    Used as a decorator next to the handler definition — see
    ``_materialize_segments`` below for the one real kind::

        @register_job_handler("segments.materialize")
        async def _materialize_segments(session, job) -> dict | None: ...

    The handler receives the session (tenant GUC already bound) and the claimed
    ``Job`` row, and returns a JSON-serialisable ``dict`` result or ``None``.
    Handlers may set ``job.progress`` (0-100) to report partial progress; they
    must NOT set ``status`` — the runner owns the status transitions.
    """

    def _register(fn: JobHandler) -> JobHandler:
        _JOB_HANDLERS[kind] = fn
        return fn

    return _register


def get_job_handler(kind: str) -> JobHandler | None:
    """The handler registered for ``kind``, or None when there is no runner yet."""
    return _JOB_HANDLERS.get(kind)


def registered_job_kinds() -> frozenset[str]:
    """Every job kind that currently has a handler."""
    return frozenset(_JOB_HANDLERS)


def failure_status(attempts: int, max_attempts: int) -> str:
    """Terminal status for a failed attempt: ``retrying`` until the budget is spent.

    Pure and session-free so the retry rule is testable without a database.
    """
    return "failed" if attempts >= max_attempts else "retrying"


def error_text(exc: BaseException) -> str:
    """A bounded, type-tagged message — a bare ``str(exc)`` loses the class."""
    return f"{type(exc).__name__}: {exc}"[:500]


def _clamp_progress(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, number))


# ------------------------------------------------------------- handlers ----


@register_job_handler("segments.materialize")
async def _materialize_segments(session: AsyncSession, job: Job) -> dict:
    """Recompute every active segment for the tenant (spec §82).

    A segment's DSL compiles to an aggregate query over ``customers`` (orders
    count, lifetime value, recency). A tenant with many segments wants to
    start the recompute and watch it, not block a request on it — exactly the
    long-running operation ``jobs`` exists for. Evaluation goes through the
    existing ``SegmentService`` (which also stamps ``last_count`` /
    ``last_evaluated_at``), and progress is reported per segment.
    """
    from app.modules.segments.service import Segment, SegmentService

    segments = (
        await session.execute(
            select(Segment).where(
                Segment.tenant_id == job.tenant_id, Segment.is_active.is_(True)
            )
        )
    ).scalars().all()

    total = len(segments)
    counts: dict[str, int] = {}
    for index, segment in enumerate(segments, start=1):
        matched = await SegmentService.evaluate(session, job.tenant_id, segment)
        counts[segment.name] = len(matched)
        # Real, observable progress: persisted so a job that later fails still
        # shows how far it got.
        job.progress = index * 100 // total
        await session.flush()

    return {"segments": total, "counts": counts}


# -------------------------------------------------------------- claiming ----


async def claim_jobs(session: AsyncSession, tenant_id: uuid.UUID, limit: int) -> list[Job]:
    """Atomically claim up to ``limit`` claimable jobs for one tenant.

    Lock the candidate rows with SKIP LOCKED, then conditionally flip them to
    ``processing`` (incrementing ``attempts``) in the same transaction. The
    explicit ``tenant_id`` predicate is belt-and-suspenders on top of RLS; the
    status re-check in the UPDATE is what makes the claim conditional rather
    than a blind write.
    """
    candidate_ids = (
        await session.execute(
            select(Job.id)
            .where(Job.tenant_id == tenant_id, Job.status.in_(_CLAIMABLE_STATUSES))
            .order_by(Job.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    if not candidate_ids:
        return []

    claimed_ids = (
        await session.execute(
            update(Job)
            .where(
                Job.id.in_(candidate_ids),
                Job.tenant_id == tenant_id,
                Job.status.in_(_CLAIMABLE_STATUSES),
            )
            .values(
                status="processing",
                attempts=Job.attempts + 1,
                progress=0,
                updated_at=func.now(),
            )
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        )
    ).scalars().all()
    if not claimed_ids:
        return []

    return (
        await session.execute(
            select(Job)
            .where(Job.id.in_(claimed_ids))
            .order_by(Job.created_at)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()


async def finalize_job(
    session: AsyncSession,
    job: Job,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    progress: int | None = None,
) -> bool:
    """Write the terminal (or retrying) outcome, unless the job moved on.

    The UPDATE is conditional on the row still being ``processing``. If a user
    cancelled the job while the handler ran, the row is ``cancelled`` and this
    write is refused — a cancelled job is never overwritten with a success.
    Returns True when the outcome was written.
    """
    values: dict = {"status": status, "last_error": error, "updated_at": func.now()}
    if result is not None:
        values["result"] = result
    if progress is not None:
        values["progress"] = _clamp_progress(progress)

    written = (
        await session.execute(
            update(Job)
            .where(
                Job.id == job.id,
                Job.tenant_id == job.tenant_id,
                Job.status == "processing",
            )
            .values(**values)
            .returning(Job.id)
            .execution_options(synchronize_session=False)
        )
    ).scalar_one_or_none() is not None
    if not written:
        logger.info(
            "job_runner.terminal_write_skipped job=%s intended=%s", job.id, status
        )
    # Keep the passed ORM row consistent with the row the database now holds
    # (including the "someone cancelled it" case the caller may want to assert).
    await session.refresh(job)
    return written


class JobRunner(StreamWorker):
    """Runs alongside the stream consumers: polls ``jobs`` for claimable work."""

    stream = "platform.events"  # participates in the worker process lifecycle
    group = "job-runners"
    name = "job-runner"
    poll_interval = 5.0
    batch_size = 10

    async def handle(self, event: Event) -> None:
        # The runner does not consume stream events; run() drives polling.
        return

    async def run(self) -> None:  # noqa: D102 — override: poll loop, no streams
        logger.info("job_runner.started consumer=%s", self.name)
        self._running = True
        while self._running:
            try:
                processed = await self.poll_once()
            except Exception:  # noqa: BLE001 — the runner must survive anything
                logger.exception("job_runner.poll_failed")
                processed = 0
            if not processed:
                await asyncio.sleep(self.poll_interval)

    async def poll_once(self) -> int:
        """One sweep: enumerate active tenants, claim, then execute each job.

        Claim and execution are separate transactions per tenant (see the
        module docstring): a handler that poisons its own transaction must not
        be able to roll the claim — and its ``attempts`` increment — back.
        """
        processed = 0
        for tenant_id in await self._active_tenant_ids():
            if not self._running:
                break
            for job_id in await self._claim_phase(tenant_id):
                if not self._running:
                    break
                if await self._execute_phase(tenant_id, job_id):
                    processed += 1
        return processed

    async def _active_tenant_ids(self) -> list[uuid.UUID]:
        """Tenants worth looking at — the coarse operational flag (§48).

        ``jobs`` is RLS-scoped, so there is no cross-tenant read to find work
        from; enumerating tenants is the §125 pattern the retention worker uses.
        The fine-grained lifecycle gate is re-applied per tenant below.
        """
        from app.modules.identity.models import Tenant

        async with SessionLocal() as session:
            rows = await session.execute(select(Tenant.id).where(Tenant.is_active))
            return list(rows.scalars().all())

    async def _claim_phase(self, tenant_id: uuid.UUID) -> list[uuid.UUID]:
        """Claim a batch in its own short transaction; commit, return the ids."""
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                jobs = await self.claim_for_tenant(session, tenant_id)
                return [job.id for job in jobs]

    async def _execute_phase(self, tenant_id: uuid.UUID, job_id: uuid.UUID) -> bool:
        """Execute one already-claimed job in its own transaction."""
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                return await self.execute_claimed(session, tenant_id, job_id)

    async def claim_for_tenant(
        self, session: AsyncSession, tenant_id: uuid.UUID
    ) -> list[Job]:
        """Claim this tenant's next batch, or nothing when the tenant is deferred.

        Runs in the caller's transaction (mirrors ``RetentionWorker.run_once``),
        so the transactional-session tests can drive it directly.
        """
        try:
            await defer_unless_tenant_allows(session, tenant_id, _REQUIRED_CAPABILITY)
        except DeferredError as exc:
            # Not a failure: the jobs stay queued and resume on reactivation.
            logger.info("job_runner.tenant_deferred tenant=%s reason=%s", tenant_id, exc)
            return []
        return await claim_jobs(session, tenant_id, self.batch_size)

    async def execute_claimed(
        self, session: AsyncSession, tenant_id: uuid.UUID, job_id: uuid.UUID
    ) -> bool:
        """Run one claimed job, re-reading it so a cancel that landed first wins.

        Returns False when the job is gone or no longer ``processing`` (for
        example it was cancelled between the claim and this execution).
        """
        job = (
            await session.execute(
                select(Job).where(Job.tenant_id == tenant_id, Job.id == job_id)
            )
        ).scalar_one_or_none()
        if job is None or job.status != "processing":
            logger.info(
                "job_runner.execute_skipped job=%s status=%s",
                job_id,
                getattr(job, "status", None),
            )
            return False
        await self.execute_job(session, job)
        return True

    async def execute_job(self, session: AsyncSession, job: Job) -> None:
        """Dispatch one claimed job and record its outcome.

        The handler runs in a SAVEPOINT: a database error it raises is rolled
        back to the savepoint, leaving the surrounding transaction usable so
        the failure (and the claim's ``attempts`` increment) can still be
        written. An unknown ``kind`` fails the job with a clear error — it must
        not sit queued forever, and it must not look like a transient failure.
        """
        handler = get_job_handler(job.kind)
        if handler is None:
            logger.warning("job_runner.no_handler job=%s kind=%s", job.id, job.kind)
            await finalize_job(
                session,
                job,
                status="failed",
                error=f"no handler registered for job kind {job.kind!r}",
            )
            return

        try:
            async with session.begin_nested():
                result = await handler(session, job)
        except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
            logger.exception(
                "job_runner.handler_failed job=%s kind=%s attempt=%s",
                job.id,
                job.kind,
                job.attempts,
            )
            await finalize_job(
                session,
                job,
                status=failure_status(job.attempts, job.max_attempts),
                error=error_text(exc),
                progress=_clamp_progress(getattr(job, "progress", 0)),
            )
            return

        await finalize_job(
            session, job, status="completed", result=result or {}, progress=100
        )
