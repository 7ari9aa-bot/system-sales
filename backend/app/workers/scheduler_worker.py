"""Durable scheduler poller (spec §154).

Claims due ScheduledJob rows (FOR UPDATE SKIP LOCKED), executes the
registered handler, records attempts/error/result. Handlers register by
job_type; re-check conditions at execution time (spec: customer may have
replied / order changed / consent revoked since scheduling).

Recurring jobs (reconcile sweeps) are self-rescheduling: on completion the
handler path inserts the NEXT occurrence via a stable idempotency key, so a
crash between completion and re-schedule re-runs the sweep idempotently.
The table is RLS-exempt (system plumbing): the claim query runs before any
tenant context exists.
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
    "expire_reservations": (timedelta(minutes=5), {}),
    # §135: a PENDING approval past its TTL must not stay decidable forever —
    # the parked run would hang indefinitely otherwise.
    "expire_approvals": (timedelta(minutes=10), {}),
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


async def ensure_recurring_jobs() -> None:
    """Insert the recurring sweep jobs (per active tenant) if absent.

    Runs at scheduler start; ON CONFLICT DO NOTHING on the idempotency key
    makes it safe to call on every boot and from multiple replicas.
    """
    from sqlalchemy import select as sa_select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.modules.identity.models import Tenant

    async with SessionLocal() as session:
        async with session.begin():
            tenant_ids = (
                (await session.execute(sa_select(Tenant.id).where(Tenant.is_active)))
                .scalars()
                .all()
            )
            now = datetime.now(UTC)
            for tenant_id in tenant_ids:
                for job_type, (_interval, payload) in RECURRING_JOBS.items():
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

    async def handle(self, event: Event) -> None:
        # The scheduler does not consume stream events; run() drives polling.
        return

    async def run(self) -> None:  # noqa: D102 — override: poll loop, no streams
        logger.info("scheduler.started consumer=%s", self.name)
        self._running = True
        try:
            await ensure_recurring_jobs()
        except Exception:  # noqa: BLE001 — never block the poll loop on bootstrap
            logger.exception("scheduler.bootstrap_failed")
        while self._running:
            try:
                processed = await self._poll_once()
            except Exception:  # noqa: BLE001 — scheduler must survive anything
                logger.exception("scheduler.poll_failed")
                processed = 0
            if not processed:
                import asyncio

                await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> int:

        processed = 0
        async with SessionLocal() as session:
            async with session.begin():
                now = datetime.now(UTC)
                rows = (
                    await session.execute(
                        select(ScheduledJob)
                        .where(
                            ScheduledJob.status.in_(["queued", "retrying"]),
                            ScheduledJob.run_at <= now,
                            (ScheduledJob.next_attempt_at.is_(None))
                            | (ScheduledJob.next_attempt_at <= now),
                        )
                        .with_for_update(skip_locked=True)
                        .limit(10)
                    )
                ).scalars().all()
                for job in rows:
                    if job.idempotency_key:
                        claimed = (
                            await session.execute(
                                text(
                                    "SELECT pg_try_advisory_xact_lock("
                                    "hashtext(:key))"
                                ),
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
                        tenant_raw = job.tenant_id  # tenant-scoped job
                        if tenant_raw:
                            await bind_tenant(session, tenant_raw)
                        result = await handler(session, tenant_raw, job.payload or {})
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
                            job.next_attempt_at = now + timedelta(
                                seconds=random.uniform(0, base)
                            )
                    processed += 1
        return processed

    async def _reschedule_recurring(
        self, session, job: ScheduledJob, now: datetime
    ) -> bool:
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
