"""Durable scheduler poller (spec §154).

Claims due ScheduledJob rows (FOR UPDATE SKIP LOCKED), executes the
registered handler, records attempts/error/result. Handlers register by
job_type; re-check conditions at execution time (spec: customer may have
replied / order changed / consent revoked since scheduling).

Recurring jobs (reconcile sweeps) are self-rescheduling: on completion the
handler path inserts the NEXT occurrence via a stable idempotency key, so a
crash between completion and re-schedule re-runs the sweep idempotently.

RLS: `scheduled_jobs` is **FORCE ROW LEVEL SECURITY** with a `tenant_isolation`
policy on BOTH `USING` and `WITH CHECK`. This docstring used to claim the table
was "RLS-exempt (system plumbing)" and that the claim query ran "before any
tenant context exists" — the schema says otherwise, and that false assumption
was the bug: an INSERT without `app.tenant_id` bound is rejected by WITH CHECK,
and a SELECT without it matches ZERO rows. So this worker enumerates active
tenants and runs ONE TRANSACTION PER TENANT with the GUC bound, the same
cross-tenant pattern as `retention_worker`. Before that fix the table was empty
in production and no recurring sweep had ever run.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.db import SessionLocal, bind_tenant
from app.core.events.bus import Event
from app.modules.platform.models import ScheduledJob
from app.workers.base import StreamWorker

logger = logging.getLogger(__name__)

_HANDLERS: dict[str, Callable] = {}

# Recurring sweeps: job_type -> (interval, default payload)
RECURRING_JOBS: dict[str, tuple[timedelta, dict]] = {
    "reconcile_unknown_messages": (timedelta(minutes=5), {"threshold_minutes": 15}),
    "reconcile_payments": (timedelta(minutes=15), {"threshold_minutes": 15}),
    # §188: ledger ≟ projection — a discrepancy becomes a finding row, never
    # a silent fix. Half-hourly is cheap: the checks are two indexed queries.
    "reconcile_inventory": (timedelta(minutes=30), {}),
    "expire_reservations": (timedelta(minutes=5), {}),
    # §135: a PENDING approval past its TTL must not stay decidable forever —
    # the parked run would hang indefinitely otherwise.
    "expire_approvals": (timedelta(minutes=10), {}),
    # §46: without a sweep a deadline is decorative — nothing ever notices it
    # passing, so "SLA risk" would never turn into "breached".
    "sla.sweep": (timedelta(minutes=5), {}),
    # §52: retention only happens if something runs it. The worker existed but
    # was not in POOLS and nothing ever scheduled it, so no tenant's
    # RetentionPolicy was ever enforced.
    "retention.run": (timedelta(hours=24), {}),
    # §56: a monthly partition must exist BEFORE the month it belongs to. The
    # migration pre-creates a horizon; without a sweep that horizon simply runs
    # out and rows start falling into the DEFAULT partition, where retention
    # cannot reach them month-by-month.
    "partition.ensure_months": (timedelta(days=1), {"months_ahead": 3}),
    # §57: the destructive half, and deliberately the slowest sweep here — a
    # dropped month cannot be un-dropped. Safe to run from every tenant's row
    # because the consent gate it consults is global: `ai_usage` is partitioned
    # by month, not by tenant (spec §56), so the act either applies to all
    # tenants or to none. `partitioning_purge_month` takes an advisory lock on
    # (parent, month), so two workers racing the same month cannot both drop it.
    "retention.purge_partitions": (timedelta(days=1), {}),
    # §82: the `segments.materialize` job handler existed with NO producer —
    # `JobService.create` had zero production callers, so in production the
    # recompute could never run ("built, tested in isolation, never called").
    # This sweep is that producer: per tenant, it ENQUEUES the runner job.
    "segments.recompute": (timedelta(hours=6), {}),
}


async def _deliver_password_reset_email() -> int:
    from app.modules.identity.email_delivery import PasswordResetEmailDelivery

    return await PasswordResetEmailDelivery.run_once()


async def _deliver_email_verification_email() -> int:
    # Same pre-GUC possession pattern as the reset sweep: the delivery worker
    # claims leased verification-token rows by token hash, so it binds no
    # tenant/user GUC and must run as a global sweeper.
    from app.modules.identity.email_delivery import EmailVerificationEmailDelivery

    return await EmailVerificationEmailDelivery.run_once()


async def _purge_expired_offboarding_tenants() -> int:
    from app.workers.retention_worker import OffboardingWorker

    return await OffboardingWorker.sweep_expired()


# Global maintenance tasks cannot be represented as ScheduledJob rows because
# that table is tenant-scoped and recurring-job seeding only sees active
# tenants. Each function owns its own durable claim/transaction semantics.
async def _sweep_vision_product_indexing() -> int:
    from app.modules.ai.agents.customer.vision.indexer import (
        sweep_unindexed_product_images,
    )

    return await sweep_unindexed_product_images()


GLOBAL_SWEEPERS: dict[str, tuple[timedelta, Callable[[], object]]] = {
    "password_reset_email": (timedelta(seconds=5), _deliver_password_reset_email),
    "email_verification_email": (timedelta(seconds=5), _deliver_email_verification_email),
    "offboarding.purge": (timedelta(hours=1), _purge_expired_offboarding_tenants),
    # 6.3: product image embeddings lived only behind a manual CLI — prod sat
    # at images=1/embeddings=0 and vision matched nothing. Hourly, idempotent,
    # only-missing selection doubles as backfill, reconciliation, and the
    # model-change re-index.
    "vision.product_indexing": (timedelta(hours=1), _sweep_vision_product_indexing),
}


def register_job_handler(job_type: str, fn: Callable) -> None:
    """fn signature: async fn(session, tenant_id, payload) -> dict|None"""
    _HANDLERS[job_type] = fn


async def _handle_reconcile_messages(session, tenant_id, payload: dict) -> dict:
    from app.modules.conversations.service import ConversationService

    minutes = int(payload.get("threshold_minutes", 15))
    reconciled = await ConversationService.reconcile_unknown_messages(
        session, tenant_id, stuck_threshold_minutes=minutes
    )
    return {"count": len(reconciled), "items": reconciled}


register_job_handler("reconcile_unknown_messages", _handle_reconcile_messages)


async def _handle_reconcile_payments(session, tenant_id, payload: dict) -> dict:
    from app.modules.orders.service import OrderService

    minutes = int(payload.get("threshold_minutes", 15))
    reconciled = await OrderService.reconcile_stuck_payments(
        session, tenant_id, stuck_threshold_minutes=minutes
    )
    return {"count": len(reconciled), "items": reconciled}


register_job_handler("reconcile_payments", _handle_reconcile_payments)


async def _handle_reconcile_inventory(session, tenant_id, payload: dict) -> dict:
    from app.modules.inventory.reconciliation import InventoryReconciliationService

    return await InventoryReconciliationService.reconcile_tenant(session, tenant_id)


register_job_handler("reconcile_inventory", _handle_reconcile_inventory)


async def _handle_expire_reservations(session, tenant_id, payload: dict) -> dict:
    from app.modules.inventory.service import InventoryReservationService

    expired = await InventoryReservationService.expire_stale(session, tenant_id)
    return {"count": expired}


register_job_handler("expire_reservations", _handle_expire_reservations)


async def _handle_expire_approvals(session, tenant_id, payload: dict) -> dict:
    """§135: expire PENDING approvals past their TTL.

    Nothing called expire_stale() before, so an undecided approval stayed
    PENDING forever and its parked run never resolved either way.
    """
    from app.modules.ai.approvals import ApprovalService

    expired = await ApprovalService.expire_stale(session, tenant_id)
    return {"count": expired}


register_job_handler("expire_approvals", _handle_expire_approvals)


async def _handle_sla_sweep(session, tenant_id, payload: dict) -> dict:
    """§46: mark first-response SLAs whose deadline has passed as breached."""
    from app.modules.operations.sla import SlaService

    return await SlaService.sweep(session, tenant_id)


register_job_handler("sla.sweep", _handle_sla_sweep)


async def _handle_retention(session, tenant_id, payload: dict) -> dict:
    """§52: enforce the tenant's RetentionPolicy rows.

    The caller (this scheduler) already bound the tenant GUC, which is what
    RetentionWorker.run_once expects.
    """
    from app.workers.retention_worker import RetentionWorker

    return await RetentionWorker.run_once(session, tenant_id)


register_job_handler("retention.run", _handle_retention)


async def _handle_partition_ensure(session, tenant_id, payload: dict) -> dict:
    """§56: make sure the next months' partitions exist.

    The DDL cannot be issued by this process: `sales_app` has no CREATE on
    schema public, so `app.core.partitioning` calls the SECURITY DEFINER
    maintenance functions the migration installs. A missing grant or a lagging
    migration therefore raises `PartitionMaintenanceUnavailable` and shows up in
    `scheduled_jobs.last_error` — which is the point. Silently reporting "0
    created" on a database where nothing can be created is how this repo's
    sweeps stayed dead for their whole life.
    """
    from app.core.partitioning import ensure_month_partitions

    months_ahead = int(payload.get("months_ahead", 3))
    created = await ensure_month_partitions(session, months_ahead=months_ahead)
    return {"created": created, "months_ahead": months_ahead}


register_job_handler("partition.ensure_months", _handle_partition_ensure)


async def _handle_retention_purge(session, tenant_id, payload: dict) -> dict:
    """§57: drop whole months, but only after every active tenant chose it.

    Deliberately one call, into the module that owns the decision. It must not
    reach for `partitioning.purge_month` directly: the consent gate is the only
    thing separating this from the `archive_old_rows` that was deleted for
    having no policy behind it.
    """
    from app.modules.analytics.retention import purge_expired_partitions

    return await purge_expired_partitions(session, tenant_id)


register_job_handler("retention.purge_partitions", _handle_retention_purge)


async def _handle_segments_recompute(session, tenant_id, payload: dict) -> dict:
    """§82: enqueue this tenant's segment recompute as a §84 Job.

    Deliberately NOT a direct recompute: the heavy DSL evaluation belongs to
    `job_runner`'s `segments.materialize` handler, where progress, retries and
    the operations job views apply — the scheduler row is only the wake-up.
    A still-pending job is not doubled: the sweep re-fires every 6 hours and
    a stalled runner must not turn it into a queue pile-up.
    """
    from app.modules.platform.models import Job
    from app.modules.platform.service import JobService

    pending = (
        await session.execute(
            select(Job.id)
            .where(
                Job.tenant_id == tenant_id,
                Job.kind == "segments.materialize",
                Job.status.in_(["queued", "processing", "retrying"]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if pending is not None:
        return {"skipped": "pending", "job_id": str(pending)}
    job = await JobService.create(session, tenant_id, kind="segments.materialize")
    return {"job_id": str(job.id), "kind": job.kind}


register_job_handler("segments.recompute", _handle_segments_recompute)


async def _handle_journey_resume(session, tenant_id, payload: dict) -> dict:
    """§175: continue a journey run whose DELAY step has elapsed.

    The producer is ``marketing.journey._handle_delay``, which creates this
    row and parks the run at ``waiting_delay``. Until this handler existed the
    row had no handler at all: every delayed journey step was claimed, then
    written back ``failed / "no handler for journey.resume"``, so a journey
    stopped dead at its first wait and the merchant saw a run stuck in
    ``waiting_delay`` forever. That is this repo's named failure mode —
    built, unit-tested, never called — one level down from a whole worker.

    ``resume_after_delay`` owns the step bookkeeping (it is the journey
    module's own invariant, not the scheduler's); this handler only unmarshals
    the payload and reports what the run did next.
    """
    from uuid import UUID

    from app.core.errors import ValidationError
    from app.modules.marketing.journey import JourneyExecutionService

    run_id = payload.get("run_id")
    if not run_id:
        raise ValidationError("journey.resume payload carries no run_id")
    run = await JourneyExecutionService.resume_after_delay(session, tenant_id, UUID(str(run_id)))
    if run is None:
        return {"skipped": "not waiting", "run_id": str(run_id)}
    return {"run_id": str(run.id), "status": run.status, "step": run.current_step}


register_job_handler("journey.resume", _handle_journey_resume)


async def ensure_recurring_jobs() -> None:
    """Insert the recurring sweep jobs (per active tenant) if absent.

    Runs at scheduler start; ON CONFLICT DO NOTHING on the idempotency key
    makes it safe to call on every boot and from multiple replicas.

    ONE TRANSACTION PER TENANT with the GUC bound first. `scheduled_jobs` is
    FORCE RLS with `tenant_isolation` on both USING and WITH CHECK, so an INSERT
    with no `app.tenant_id` is rejected outright. The previous version read the
    tenant list and inserted every row inside one UNBOUND transaction, so every
    insert was rejected — which is exactly why the table was empty in production
    and no recurring sweep had ever run.
    """
    from sqlalchemy import select as sa_select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.modules.identity.models import Tenant

    # `tenants` itself carries no RLS, so the enumeration needs no context.
    async with SessionLocal() as session:
        tenant_ids = (
            (await session.execute(sa_select(Tenant.id).where(Tenant.is_active))).scalars().all()
        )

    now = datetime.now(UTC)
    for tenant_id in tenant_ids:
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                for job_type, (_interval, payload) in RECURRING_JOBS.items():
                    # Insert-if-absent is the right key because a recurring sweep
                    # has exactly ONE logical occurrence per (job_type, tenant):
                    # there is no schedule table of future rows, the row IS the
                    # schedule and `_reschedule_recurring` re-arms THIS row in
                    # place after each run. So the row is made unique by its
                    # stable idempotency_key (`recurring:{job_type}:{tenant_id}`),
                    # backed by the uq_scheduled_jobs_idem UNIQUE constraint — a
                    # duplicate `(job_type, tenant)` pair is meaningless, there can
                    # only ever be one next-run. ON CONFLICT DO NOTHING on that key
                    # therefore makes this idempotent across boots and replicas:
                    # a restart never multiplies the sweep, and two workers racing
                    # at boot converge on a single row.
                    stmt = (
                        pg_insert(ScheduledJob)
                        .values(
                            tenant_id=tenant_id,
                            job_type=job_type,
                            status="queued",
                            run_at=now,
                            payload=payload,
                            attempts=0,
                            max_attempts=5,
                            idempotency_key=f"recurring:{job_type}:{tenant_id}",
                        )
                        .on_conflict_do_nothing(index_elements=["idempotency_key"])
                    )
                    await session.execute(stmt)
    if tenant_ids:
        logger.info("scheduler.recurring_jobs_ensured tenants=%d", len(tenant_ids))


class SchedulerWorker(StreamWorker):
    """Runs alongside stream consumers: polls scheduled_jobs for due work."""

    stream = "platform.events"  # participates in the worker process lifecycle
    group = "scheduler-workers"
    name = "scheduler-worker"
    poll_interval = 5.0

    #: True once the recurring jobs have been seeded. Observable on purpose: a
    #: boot that never seeded them must be detectable, instead of looking like a
    #: healthy poll loop over an empty table — which is how the RLS bug survived.
    bootstrap_done: bool = False

    def __init__(self, bus) -> None:
        super().__init__(bus)
        self._global_sweeper_last_run: dict[str, float] = {}

    async def handle(self, event: Event) -> None:
        # The scheduler does not consume stream events; run() drives polling.
        return

    async def run(self) -> None:  # noqa: D102 — override: poll loop, no streams
        logger.info("scheduler.started consumer=%s", self.name)
        self._running = True
        while self._running:
            # Bootstrap is RETRIED, not attempted once. It used to run once inside
            # a try/except that only logged: a transient database blip at boot
            # therefore meant no recurring job was EVER seeded and nothing ever
            # retried — a permanent, invisible failure. The table being empty in
            # production is exactly how that looked from the outside.
            if not self.bootstrap_done:
                try:
                    await ensure_recurring_jobs()
                    self.bootstrap_done = True
                except Exception:  # noqa: BLE001 — never block the poll loop
                    logger.exception("scheduler.bootstrap_failed — retrying next poll")
            try:
                processed = await self._poll_once()
            except Exception:  # noqa: BLE001 — scheduler must survive anything
                logger.exception("scheduler.poll_failed")
                processed = 0
            processed += await self._run_global_sweepers()
            if not processed:
                import asyncio

                await asyncio.sleep(self.poll_interval)

    async def _run_global_sweepers(self) -> int:
        import time

        now_monotonic = time.monotonic()
        processed = 0
        for name, (interval, handler) in GLOBAL_SWEEPERS.items():
            last_run = self._global_sweeper_last_run.get(name)
            if last_run is not None and now_monotonic - last_run < interval.total_seconds():
                continue
            # Mark due before calling. A failing maintenance action must not
            # create a hot loop; the normal interval retries it.
            self._global_sweeper_last_run[name] = now_monotonic
            try:
                processed += int(await handler() or 0)
            except Exception:  # noqa: BLE001 — one global task cannot kill scheduling
                logger.exception("scheduler.global_sweeper_failed name=%s", name)
        return processed

    async def _poll_once(self) -> int:
        """Claim and run due jobs for every active tenant.

        ONE TRANSACTION PER TENANT with the GUC bound, because `scheduled_jobs`
        is FORCE RLS: the claim query used to run unbound and therefore matched
        ZERO rows on every poll, forever — the scheduler was polling an empty
        view while logging a healthy loop. `tenants` has no RLS, so the
        enumeration itself needs no context. Same shape as retention_worker.
        """
        from app.modules.identity.models import Tenant

        async with SessionLocal() as session:
            tenant_ids = (
                (await session.execute(select(Tenant.id).where(Tenant.is_active))).scalars().all()
            )

        processed = 0
        for tenant_id in tenant_ids:
            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    processed += await self._drain_tenant(session, tenant_id)
        return processed

    async def _drain_tenant(self, session, tenant_id) -> int:
        """Claim and execute this tenant's due jobs inside the caller's tx."""
        processed = 0
        now = datetime.now(UTC)
        rows = (
            (
                await session.execute(
                    select(ScheduledJob)
                    .where(
                        ScheduledJob.tenant_id == tenant_id,
                        ScheduledJob.status.in_(["queued", "retrying"]),
                        ScheduledJob.run_at <= now,
                        (ScheduledJob.next_attempt_at.is_(None))
                        | (ScheduledJob.next_attempt_at <= now),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        for job in rows:
            if job.idempotency_key:
                claimed = (
                    await session.execute(
                        text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                        {"key": job.idempotency_key},
                    )
                ).scalar()
                if not claimed:
                    continue
            handler = _HANDLERS.get(job.job_type)
            job.attempts += 1
            job.status = "processing"
            if handler is None:
                job.status = "failed"
                job.last_error = f"no handler for {job.job_type}"
                processed += 1
                continue
            try:
                # Already bound by _poll_once; re-binding is harmless and keeps
                # _drain_tenant safe to call from anywhere.
                await bind_tenant(session, job.tenant_id)
                result = await handler(session, job.tenant_id, job.payload or {})
                job.result = result or {}
                # Recurring sweeps re-arm this row; one-shot jobs finish.
                if not await self._reschedule_recurring(session, job, now):
                    job.status = "completed"
            except Exception as exc:  # noqa: BLE001
                # Backoff with jitter — the previous code left
                # next_attempt_at NULL, burning all 5 attempts in ~25s.
                job.last_error = str(exc)[:500]
                if job.attempts >= job.max_attempts:
                    job.status = "failed"
                else:
                    job.status = "retrying"
                    base = min(2.0 * (2 ** (job.attempts - 1)), 300.0)
                    job.next_attempt_at = now + timedelta(seconds=random.uniform(0, base))
            processed += 1
        return processed

    async def _reschedule_recurring(self, session, job: ScheduledJob, now: datetime) -> bool:
        """Recurring sweeps re-arm the SAME row for their next occurrence.

        Returns True when the job was re-armed (caller must not mark it
        completed), False for one-shot jobs.

        Re-arming in place — instead of inserting a second row carrying the
        same stable key — is required for correctness: `idempotency_key` is
        UNIQUE (uq_scheduled_jobs_idem), the flush lands at commit time
        (OUTSIDE the per-job try/except), so the duplicate insert rolled back
        the entire claim batch. Every poll re-claimed the same job and failed
        the same way: reconcile/expire sweeps never ran at all.
        """
        if job.job_type not in RECURRING_JOBS or not job.tenant_id:
            return False
        interval, payload = RECURRING_JOBS[job.job_type]
        job.status = "queued"
        job.run_at = now + interval
        job.attempts = 0
        job.next_attempt_at = None
        job.last_error = None
        job.payload = payload
        return True
