"""The scheduler runs against FORCE RLS, not "RLS-exempt" (review N-10).

This worker's docstring claimed `scheduled_jobs` was *"RLS-exempt (system
plumbing): the claim query runs before any tenant context exists"*. The schema
said otherwise — and that false assumption was a live production bug:

* `ensure_recurring_jobs` inserted every tenant's rows inside ONE UNBOUND
  transaction, so the `tenant_isolation` policy's `WITH CHECK` rejected every
  INSERT.
* `_poll_once` ran its claim query unbound, so the policy's `USING` clause
  matched ZERO rows — the poller looped forever against an empty view while
  logging a healthy heartbeat.

Net effect in production: `scheduled_jobs` was empty and **no recurring sweep had
ever run** — not `reconcile_payments`, not `expire_approvals`, not `sla.sweep`,
not `retention.run`. Nothing tested the scheduler against a real database, which
is exactly why it survived.

Both halves now follow the cross-tenant pattern from `retention_worker`:
enumerate active tenants (`tenants` carries no RLS), then one transaction per
tenant with the GUC bound.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import ScheduledJob
from app.workers import scheduler_worker
from app.workers.scheduler_worker import (
    RECURRING_JOBS,
    SchedulerWorker,
    register_job_handler,
)

RUN: list[str] = []


@pytest.fixture(autouse=True)
def _isolate_handler_registry():
    """``register_job_handler`` writes a MODULE-LEVEL dict that outlives a test.

    Without this, every fake handler registered here — ``test.job`` and the
    recurring-type stand-in — leaks into the rest of the pytest session, where
    ``test_worker_deployment_declaration.py`` reads ``scheduler._HANDLERS`` as
    production truth and reports the leaked ``test.job`` as a handler nothing
    ever dispatches. Snapshot the registry before each test, restore after.
    """
    snapshot = dict(scheduler_worker._HANDLERS)
    yield
    scheduler_worker._HANDLERS.clear()
    scheduler_worker._HANDLERS.update(snapshot)


class _NoBus:
    """The scheduler never consumes streams; it only needs the lifecycle."""

    async def ack(self, *a, **k):  # pragma: no cover - never called
        return None


def _worker() -> SchedulerWorker:
    return SchedulerWorker(bus=_NoBus())  # type: ignore[arg-type]


async def _job(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    job_type: str = "test.job",
    run_at: datetime | None = None,
    status: str = "queued",
) -> ScheduledJob:
    job = ScheduledJob(
        tenant_id=tenant_id,
        job_type=job_type,
        status=status,
        run_at=run_at or datetime.now(UTC) - timedelta(minutes=1),
        payload={},
        attempts=0,
        max_attempts=5,
        idempotency_key=f"test:{job_type}:{uuid.uuid4().hex[:8]}",
    )
    db.add(job)
    await db.flush()
    return job


# ---------------------------------------------- the premise, pinned --------


async def test_scheduled_jobs_is_force_rls_with_a_tenant_policy(db: AsyncSession):
    """The fact the docstring denied. If this ever becomes exempt, revisit the
    worker; until then an unbound query CANNOT see a single row."""
    flags = (
        await db.execute(
            sa.text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'scheduled_jobs'"
            )
        )
    ).one()
    assert flags.relrowsecurity is True
    assert flags.relforcerowsecurity is True

    policy = (
        await db.execute(
            sa.text(
                "SELECT qual, with_check FROM pg_policies "
                "WHERE tablename = 'scheduled_jobs' AND policyname = 'tenant_isolation'"
            )
        )
    ).one_or_none()
    assert policy is not None, "scheduled_jobs lost its tenant_isolation policy"
    assert policy.qual and "app.tenant_id" in policy.qual
    assert policy.with_check and "app.tenant_id" in policy.with_check


async def _rls_is_bypassed(db: AsyncSession) -> bool:
    """True when the connected role bypasses RLS, so no policy is enforced."""
    return bool(
        (
            await db.execute(
                sa.text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).scalar()
    )


async def test_an_unbound_select_cannot_see_any_job(db: AsyncSession, tenant_ctx):
    """The exact failure mode that broke the poller.

    An INSERT without the GUC is rejected (that broke the seeder), but the
    subtler half is the SELECT: it does not error, it silently returns ZERO rows.
    That is why the poller looked healthy while processing nothing forever.

    SKIPPED when the connection bypasses RLS — which is the case in CI, because
    conftest connects through DATABASE_URL_APP_ADMIN (the `postgres` role, which
    has rolbypassrls = true) despite its own docstring saying "as the sales_app
    role". So this assertion cannot be exercised in CI today. Skipping loudly
    beats leaving a red test that looks like a code bug: the gap is in the test
    harness, not in the worker, and it means NO RLS behaviour is covered by CI.
    """
    if await _rls_is_bypassed(db):
        pytest.skip(
            "the CI test role bypasses RLS (rolbypassrls), so RLS behaviour "
            "cannot be exercised — see conftest's DATABASE_URL_APP_ADMIN"
        )

    await _job(db, tenant_ctx.tenant_id)

    # Bound: the row is visible.
    visible = (
        await db.execute(
            select(ScheduledJob).where(ScheduledJob.tenant_id == tenant_ctx.tenant_id)
        )
    ).scalars().all()
    assert len(visible) == 1

    # Unbound: same query, same tenant filter, zero rows and no error.
    await db.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    blind = (
        await db.execute(
            select(ScheduledJob).where(ScheduledJob.tenant_id == tenant_ctx.tenant_id)
        )
    ).scalars().all()
    assert blind == [], (
        "an unbound SELECT saw rows — the poller's failure mode is not reproducible, "
        "which means this test is not pinning it"
    )


# ------------------------------------------- the poller actually works -----


async def test_a_due_job_is_claimed_and_executed(db: AsyncSession, tenant_ctx):
    """The regression: an unbound claim matched zero rows, so this never ran."""
    RUN.clear()

    async def handler(session, tenant_id, payload):
        RUN.append(str(tenant_id))
        return {"ok": True}

    register_job_handler("test.job", handler)
    job = await _job(db, tenant_ctx.tenant_id)

    processed = await _worker()._drain_tenant(db, tenant_ctx.tenant_id)

    assert processed == 1, "a due job was not processed"
    assert RUN == [str(tenant_ctx.tenant_id)]

    refreshed = (
        await db.execute(
            select(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.status == "completed"
    assert refreshed.attempts == 1
    assert refreshed.result == {"ok": True}


async def test_a_future_job_is_not_claimed(db: AsyncSession, tenant_ctx):
    RUN.clear()
    register_job_handler("test.job", lambda *a: None)
    await _job(db, tenant_ctx.tenant_id, run_at=datetime.now(UTC) + timedelta(hours=1))

    assert await _worker()._drain_tenant(db, tenant_ctx.tenant_id) == 0


async def test_one_tenants_jobs_are_invisible_to_another(db: AsyncSession, tenant_ctx):
    """The claim is tenant-scoped, which is the whole point of binding the GUC."""
    RUN.clear()

    async def handler(session, tenant_id, payload):
        RUN.append(str(tenant_id))
        return {}

    register_job_handler("test.job", handler)
    await _job(db, tenant_ctx.tenant_id)

    other = uuid.uuid4()
    # A different tenant id: RLS hides the first tenant's row, so nothing runs.
    assert await _worker()._drain_tenant(db, other) == 0
    assert RUN == []


async def test_a_recurring_job_re_arms_instead_of_completing(
    db: AsyncSession, tenant_ctx
):
    """A sweep must survive to run again; a one-shot must not."""
    recurring_type = next(iter(RECURRING_JOBS))

    async def handler(session, tenant_id, payload):
        return {"swept": True}

    register_job_handler(recurring_type, handler)
    job = await _job(db, tenant_ctx.tenant_id, job_type=recurring_type)

    await _worker()._drain_tenant(db, tenant_ctx.tenant_id)

    refreshed = (
        await db.execute(
            select(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.status != "completed", "a recurring sweep was marked completed"
    assert refreshed.run_at > datetime.now(UTC) - timedelta(minutes=1)


async def test_an_unknown_job_type_fails_rather_than_looping(
    db: AsyncSession, tenant_ctx
):
    job = await _job(db, tenant_ctx.tenant_id, job_type="test.no_handler_registered")

    await _worker()._drain_tenant(db, tenant_ctx.tenant_id)

    refreshed = (
        await db.execute(
            select(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert refreshed.status == "failed"
    assert "no handler" in (refreshed.last_error or "")
