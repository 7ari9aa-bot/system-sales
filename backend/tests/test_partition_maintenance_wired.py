"""§55-57 maintenance is WIRED, and proven through the scheduler.

This repo's recurring defect is a helper that exists and a job type nobody
seeds: `app/core/partitioning.py` had `ensure_upcoming_partitions()` with zero
callers, and `retention_worker` had `_RETENTABLE` with a worker that was in no
pool. Both looked healthy from the inside. So the pins below are the same shape
as `test_reservation_expiry_sweep_wired.py`: the job type must be in
`RECURRING_JOBS` (so `ensure_recurring_jobs` actually seeds a row per tenant),
a handler must be registered for it, that handler must call the real function,
and the producer must be invoked from `SchedulerWorker.run`.

Then the live chain: a DUE row driven through the claim loop must create a
partition eight months out, and must drop a month only when every active tenant
has chosen a policy that allows it. The second half is the one that matters —
it is the difference between retention and the deleted `archive_old_rows`.

DB-backed cases skip without `DATABASE_URL_APP_ADMIN`; the static pins run
everywhere.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import partitioning
from app.core.db import bind_tenant
from app.modules.analytics import retention
from app.modules.platform.models import ScheduledJob
from app.workers import scheduler_worker as sw

_WORKER_SRC = pathlib.Path(sw.__file__).read_text(encoding="utf-8")
_WORKER_TREE = ast.parse(_WORKER_SRC)
PARENT = "public.ai_usage"


def _func(tree: ast.AST, name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name
        ):
            return node
    return None


def _method_names(scope: ast.AST) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(scope)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _called_names(scope: ast.AST) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(scope)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def _month_back(count: int) -> date:
    """First of the month `count` months before this one (negative = ahead)."""
    now = datetime.now(UTC)
    total = now.year * 12 + (now.month - 1) - count
    return date(total // 12, total % 12 + 1, 1)


# ------------------------------------------------ static pins (always run) ---


def test_partition_maintenance_is_a_recurring_job_with_a_handler() -> None:
    for job_type in ("partition.ensure_months", "retention.purge_partitions"):
        assert job_type in sw.RECURRING_JOBS, (
            f"{job_type} is not recurring — no ScheduledJob row is ever seeded, so "
            "the partition DDL would rot the moment the migration's horizon runs out"
        )
        assert job_type in sw._HANDLERS, (
            f"{job_type} is recurring but has no handler: the claimed row would be "
            "failed as 'no handler for ...'"
        )


def test_the_ensure_handler_calls_the_real_partition_helper() -> None:
    fn = _func(_WORKER_TREE, "_handle_partition_ensure")
    assert fn is not None, "_handle_partition_ensure was renamed or deleted"
    assert "ensure_month_partitions" in _called_names(fn), (
        "the ensure handler no longer calls app.core.partitioning."
        "ensure_month_partitions — it would be a stub that reports success"
    )


def test_the_purge_handler_delegates_to_the_policy_gate() -> None:
    """The handler must NOT reach for raw DDL. The only safe entry point is the
    one that first asks whether every tenant chose this.
    """
    fn = _func(_WORKER_TREE, "_handle_retention_purge")
    assert fn is not None
    assert "purge_expired_partitions" in _called_names(fn)
    reached = _called_names(fn) | _method_names(fn)
    assert "detach_old_partitions" not in reached, (
        "DETACH without the consent gate is the removed archive_old_rows path"
    )
    assert "purge_month" not in reached, (
        "the handler must not drop a month directly; only the planned purge "
        "inside analytics/retention.py may ask for one"
    )


def test_both_new_jobs_are_seeded_idempotently_at_worker_start() -> None:
    """`ensure_recurring_jobs` is the producer; adding the job types above is
    enough because it loops the registry — this pin fails if someone
    special-cases them out of it, or stops calling the producer at boot.
    """
    fn = _func(_WORKER_TREE, "ensure_recurring_jobs")
    assert fn is not None
    referenced = {node.id for node in ast.walk(fn) if isinstance(node, ast.Name)}
    assert "RECURRING_JOBS" in referenced
    assert "on_conflict_do_nothing" in _method_names(fn)
    worker_cls = next(
        node
        for node in ast.walk(_WORKER_TREE)
        if isinstance(node, ast.ClassDef) and node.name == "SchedulerWorker"
    )
    run_fn = _func(worker_cls, "run")
    assert run_fn is not None
    assert "ensure_recurring_jobs" in _called_names(run_fn)


def test_the_purge_job_is_slow_and_the_ensure_job_stays_ahead_of_the_calendar() -> None:
    ensure_interval, ensure_payload = sw.RECURRING_JOBS["partition.ensure_months"]
    purge_interval, _ = sw.RECURRING_JOBS["retention.purge_partitions"]
    assert ensure_payload.get("months_ahead", 0) >= 3, (
        "pre-creating fewer than 3 months lets a month arrive before its "
        "partition exists, and rows then silently land in DEFAULT"
    )
    assert ensure_interval <= timedelta(days=2)
    assert purge_interval >= timedelta(days=1), (
        "a destructive sweep runs on a human timescale, not a hot loop"
    )


async def test_recurring_sweeps_re_arm_the_row_instead_of_completing_it() -> None:
    """DB-free half of the live chain's re-arm assertion, so the convention holds
    without a database: a sweep whose type is in `RECURRING_JOBS` must come back
    from `_reschedule_recurring` as `queued` with its next run pushed out and its
    attempt budget reset. `completed` is the ONE-SHOT terminal state — a sweep
    that reached it would never run again, because the row IS the schedule.
    """
    worker = sw.SchedulerWorker(bus=_NoBus())  # type: ignore[arg-type]
    now = datetime.now(UTC)
    for job_type in ("partition.ensure_months", "retention.purge_partitions"):
        job = ScheduledJob(
            tenant_id=uuid.uuid4(),
            job_type=job_type,
            status="processing",
            run_at=now,
            attempts=3,
            last_error="stale",
            payload={"months_ahead": 8},
        )
        # The re-arm mutates the row in place; it takes the session only for
        # signature symmetry with the claim loop, so a bare None is honest here.
        assert await worker._reschedule_recurring(None, job, now) is True, (
            f"{job_type} is recurring: returning False marks the row completed"
        )
        assert job.status == "queued", job.status
        assert job.run_at > now
        assert job.attempts == 0
        assert job.next_attempt_at is None
        assert job.last_error is None


def test_module_boundary_measure_is_not_raised_by_this_feature() -> None:
    """The retention surface reads `retention_policies` (privacy) and appends the
    audit row (platform) through bound raw SQL in `app.core`, because
    `tests/test_module_boundaries.py` ratchets the cross-module count at 94 —
    the ceiling must not rise for this feature.
    """
    src = pathlib.Path(retention.__file__).read_text(encoding="utf-8")
    assert "from app.modules" not in src
    assert "from app.core.audit import" in src or "from app.core import" in src
    handler = _func(_WORKER_TREE, "_handle_retention_purge")
    assert handler is not None
    imported = {
        node.module or "" for node in ast.walk(handler) if isinstance(node, ast.ImportFrom)
    }
    assert any(m.endswith("analytics.retention") for m in imported), (
        "handlers import inside the function body, like every other handler here"
    )


# ------------------------------------------------- the live chain (CI-only) ---


class _NoBus:
    async def ack(self, *a, **k):  # pragma: no cover - never consumed
        return None


async def _due_job(
    db: AsyncSession, tenant_id: uuid.UUID, job_type: str, payload: dict
) -> ScheduledJob:
    job = ScheduledJob(
        tenant_id=tenant_id,
        job_type=job_type,
        status="queued",
        run_at=datetime.now(UTC) - timedelta(minutes=1),
        payload=payload,
        attempts=0,
        max_attempts=5,
        idempotency_key=f"recurring:{job_type}:{tenant_id}",
    )
    db.add(job)
    await db.flush()
    return job


async def _job_after_drain(db: AsyncSession, job: ScheduledJob) -> ScheduledJob:
    """Re-read the claimed row the way the sibling wired test does — a SELECT —
    never with ``Session.refresh()``.

    ``refresh()`` expires the instance and re-SELECTs it WITHOUT flushing the
    session's pending changes. ``_drain_tenant`` had already autoflushed the
    claimed row back as 'processing' (the flush in front of its first bound
    statement), while the recurring re-arm — status 'queued', pushed run_at,
    reset attempts, the result dict — was still pending in memory. refresh()
    therefore read the stale row and CLOBBERED the re-arm: the sweep looked
    completed ('processing' != 'queued') even though the worker had re-armed
    it, which is exactly the red herring this test's CI failure carried. A
    SELECT autoflushes first, so the re-armed state is both written and read
    back; ``populate_existing`` makes the round-trip real instead of trusting
    the identity map.
    """
    return (
        await db.execute(
            select(ScheduledJob)
            .where(ScheduledJob.id == job.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _partition_names(db: AsyncSession) -> set[str]:
    return {
        r[0]
        for r in (
            await db.execute(
                text(
                    "SELECT c.relname FROM pg_inherits i JOIN pg_class c "
                    "ON c.oid = i.inhrelid "
                    "WHERE i.inhparent = 'public.ai_usage'::regclass"
                )
            )
        ).all()
    }


async def _role_exists(db: AsyncSession, role: str) -> bool:
    return bool(
        (
            await db.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            )
        ).scalar()
    )


async def test_a_due_ensure_job_creates_a_partition_eight_months_out(
    db: AsyncSession, tenant_ctx
) -> None:
    """Boot-time seeding is covered by the pins above; this proves the CLAIMED
    row reaches the DDL, and that what it creates is usable and isolated.
    """
    target = _month_back(-8)
    name = f"ai_usage_{target:%Y_%m}"
    assert name not in await _partition_names(db), (
        f"{name} already exists — the migration pre-creates less than 8 months, "
        "or this test's horizon needs widening"
    )

    job = await _due_job(
        db, tenant_ctx.tenant_id, "partition.ensure_months", {"months_ahead": 8}
    )
    worker = sw.SchedulerWorker(bus=_NoBus())  # type: ignore[arg-type]
    assert await worker._drain_tenant(db, tenant_ctx.tenant_id) == 1
    job = await _job_after_drain(db, job)

    assert job.status == "queued", "a recurring sweep must re-arm, not complete"
    assert not job.last_error, job.last_error
    created = (job.result or {}).get("created")
    assert created, f"the sweep created nothing: {job.result}"
    assert name in created
    assert name in await _partition_names(db)

    # A partition the app role cannot write into is worse than no partition, and
    # a partition without RLS is a tenant leak: assert both.
    flags = (
        await db.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
                "WHERE c.oid = to_regclass(:n)"
            ),
            {"n": f"public.{name}"},
        )
    ).one()
    assert flags[0] is True and flags[1] is True, "the new partition has no RLS"
    if await _role_exists(db, "sales_app"):
        granted = (
            await db.execute(
                text(
                    "SELECT has_table_privilege('sales_app', to_regclass(:n), 'INSERT')"
                ),
                {"n": f"public.{name}"},
            )
        ).scalar_one()
        assert granted is True, "sales_app cannot INSERT into the new partition"

    # Second run: nothing to create, nothing raised.
    assert await partitioning.ensure_month_partitions(db, months_ahead=8) == []


async def _seed_month(db: AsyncSession, months_back: int, tenant_id: uuid.UUID) -> str:
    month = _month_back(months_back)
    created = await partitioning.ensure_partition_for_month(db, PARENT, month)
    name = created or f"ai_usage_{month:%Y_%m}"
    # Bind a REAL datetime. asyncpg validates parameter types client-side,
    # before Postgres ever sees the statement — a 'YYYY-MM-DDT00:00:00+00:00'
    # string is refused with DataError even though a server-side CAST would
    # have parsed it, which is exactly how this INSERT used to die in CI.
    await db.execute(
        text(
            "INSERT INTO ai_usage (id, period_date, tokens_in, tokens_out, cost, "
            "model_calls, created_at, tenant_id) VALUES (:id, :d, 7, 7, 0, 1, "
            ":ts, :t)"
        ),
        {
            "id": uuid.uuid4(),
            "d": month,
            "ts": datetime(month.year, month.month, 1, tzinfo=UTC),
            "t": tenant_id,
        },
    )
    return name


async def _choose_for_every_active_tenant(
    db: AsyncSession, *, days: int, rebind_to: uuid.UUID
) -> int:
    """Record the same choice for every active tenant, switching the GUC per
    tenant the way the workers do. One tenant cannot write another tenant's
    policy — that is what FORCE RLS is for — so "everyone consented" has to be
    asked of each of them in turn, and the context restored afterwards.
    """
    tenants = [
        r[0]
        for r in (
            await db.execute(text("SELECT id FROM tenants WHERE is_active ORDER BY id"))
        ).all()
    ]
    assert tenants, "no active tenants to consent"
    for tid in tenants:
        await bind_tenant(db, tid)
        await db.execute(
            text(
                "INSERT INTO retention_policies (id, tenant_id, data_class, "
                "retention_days, status, created_at, updated_at) "
                "VALUES (:id, :t, :c, :d, :s, now(), now()) "
                "ON CONFLICT (tenant_id, data_class) DO UPDATE "
                "SET retention_days = :d, status = :s, updated_at = now()"
            ),
            {
                "id": uuid.uuid4(),
                "t": str(tid),
                "c": retention.AI_USAGE_DATA_CLASS,
                "d": days,
                "s": "active",
            },
        )
    await bind_tenant(db, rebind_to)
    await db.flush()
    return len(tenants)


async def test_a_due_purge_job_deletes_nothing_without_a_chosen_policy(
    db: AsyncSession, tenant_ctx
) -> None:
    """The `archive_old_rows` failure mode, tested from the scheduler side: a
    tenant that never chose anything must end the sweep with the same rows and
    the same partitions it started with.
    """
    old = await _seed_month(db, 20, tenant_ctx.tenant_id)
    recent = await _seed_month(db, 2, tenant_ctx.tenant_id)
    before = (await db.execute(text("SELECT count(*) FROM ai_usage"))).scalar_one()

    gate = await retention.read_drop_gate(db)
    assert gate.tenant_count >= 1
    assert gate.missing_policies >= 1
    assert gate.may_drop is False

    job = await _due_job(db, tenant_ctx.tenant_id, "retention.purge_partitions", {})
    worker = sw.SchedulerWorker(bus=_NoBus())  # type: ignore[arg-type]
    assert await worker._drain_tenant(db, tenant_ctx.tenant_id) == 1
    job = await _job_after_drain(db, job)
    assert not job.last_error, job.last_error
    assert job.status == "queued"
    assert job.result["purged"] == []
    assert job.result["skipped_reason"] == retention.BLOCKED_NO_CHOSEN_POLICY

    names = await _partition_names(db)
    assert old in names and recent in names, "a partition was dropped without consent"
    assert (await db.execute(text("SELECT count(*) FROM ai_usage"))).scalar_one() == before, (
        "rows vanished with no chosen policy"
    )


async def test_an_opted_in_tenant_loses_exactly_the_month_it_should(
    db: AsyncSession, tenant_ctx
) -> None:
    """500 days chosen by every active tenant: the 20-months-old partition is
    past both the chosen horizon and the database's 13-month floor, so it goes
    as ONE partition; the 2-months-old one is inside both and stays.
    """
    old = await _seed_month(db, 20, tenant_ctx.tenant_id)
    keep = await _seed_month(db, 2, tenant_ctx.tenant_id)
    old_month, keep_month = _month_back(20), _month_back(2)
    survivors = (
        await db.execute(
            text("SELECT count(*) FROM ai_usage WHERE period_date = :d"),
            {"d": keep_month},
        )
    ).scalar_one()
    assert survivors >= 1

    await _choose_for_every_active_tenant(db, days=500, rebind_to=tenant_ctx.tenant_id)

    job = await _due_job(db, tenant_ctx.tenant_id, "retention.purge_partitions", {})
    worker = sw.SchedulerWorker(bus=_NoBus())  # type: ignore[arg-type]
    assert await worker._drain_tenant(db, tenant_ctx.tenant_id) == 1
    job = await _job_after_drain(db, job)
    assert not job.last_error, job.last_error
    assert job.result["purged"] == [old], job.result

    names = await _partition_names(db)
    assert old not in names, f"{old} is still attached"
    assert keep in names, "a month inside the chosen horizon was dropped"
    assert (
        await db.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{old}"})
    ).scalar() is None, "DETACH left the month's data in the schema as a zombie table"

    assert (
        await db.execute(
            text("SELECT count(*) FROM ai_usage WHERE period_date = :d"), {"d": keep_month}
        )
    ).scalar_one() == survivors
    assert (
        await db.execute(
            text("SELECT count(*) FROM ai_usage WHERE period_date = :d"), {"d": old_month}
        )
    ).scalar_one() == 0, "the dropped month is still readable through the parent"

    # §57: a purge must be auditable after the fact.
    audits = (
        await db.execute(
            text(
                "SELECT action, resource_id, after::text FROM audit_logs "
                "WHERE action = :a ORDER BY created_at"
            ),
            {"a": retention.PURGE_AUDIT_ACTION},
        )
    ).all()
    assert len(audits) == 1, audits
    assert audits[0][1] == old
    assert str(old) in audits[0][2]


async def test_one_tenant_withdrawing_consent_blocks_the_shared_month(
    db: AsyncSession, tenant_ctx
) -> None:
    """§56 partitions by time, not by tenant, so one month belongs to everyone:
    if a single tenant pauses its policy again, the sweep must stop dropping.
    """
    old = await _seed_month(db, 20, tenant_ctx.tenant_id)
    tenants = await _choose_for_every_active_tenant(
        db, days=500, rebind_to=tenant_ctx.tenant_id
    )
    gate = await retention.read_drop_gate(db)
    assert gate.tenant_count == tenants and gate.missing_policies == 0
    assert gate.may_drop is True

    await db.execute(
        text(
            "UPDATE retention_policies SET status = 'paused' "
            "WHERE tenant_id = :t AND data_class = :c"
        ),
        {"t": str(tenant_ctx.tenant_id), "c": retention.AI_USAGE_DATA_CLASS},
    )
    await db.flush()

    result = await retention.purge_expired_partitions(db, tenant_ctx.tenant_id)
    assert result["purged"] == []
    assert result["skipped_reason"] == retention.BLOCKED_NO_CHOSEN_POLICY
    assert old in await _partition_names(db)


async def test_the_database_itself_refuses_a_month_inside_the_legal_floor(
    db: AsyncSession, tenant_ctx
) -> None:
    """Independent of any policy or plan: a caller holding EXECUTE — a person
    with psql, or a Python bug — cannot reach a month that is still inside the
    PII map's 13 months for this store.
    """
    month = _month_back(6)
    name = await _seed_month(db, 6, tenant_ctx.tenant_id)
    # The refusal aborts the PostgreSQL transaction, so the read below cannot
    # simply follow it — CI's failure was exactly that: `current transaction is
    # aborted, commands ignored until end of transaction block` raised while
    # asserting the month survived (run on c85e130). `test_hierarchy_rls.py`
    # recovers with `await db.rollback()`, and it can afford to because it
    # asserts nothing afterwards. Here that rollback would ALSO undo the seed:
    # this month's partition is created inside this transaction — `f7a2c9d4e8b1`
    # attaches only the DEFAULT child — so unwinding would delete the very
    # partition the last line claims survived, and the only way to keep it green
    # would be to drop the claim. So the abort is CONTAINED by a savepoint
    # instead, which is the repo's other precedent for a database refusal
    # (`test_invoice_immutability.py`: "without `begin_nested` the surrounding
    # test transaction would be poisoned"). The tenant GUC is re-asserted after
    # the recovery rather than trusted: `set_config(..., true)` is
    # transaction-local, so that is one cheap statement in place of an
    # assumption about savepoint semantics.
    with pytest.raises(partitioning.PartitionMaintenanceRefused) as exc:
        async with db.begin_nested():
            await partitioning.purge_month(db, PARENT, month)
    assert "floor" in str(exc.value).lower()
    await bind_tenant(db, tenant_ctx.tenant_id)
    assert name in await _partition_names(db)


async def test_non_allowlisted_parents_are_refused_by_both_layers(
    db: AsyncSession, tenant_ctx
) -> None:
    """`messages` is §56's other big append-only table and it is NOT converted
    (inbound single-column FKs make a partitioned primary key impossible) — the
    maintenance functions must refuse it by name rather than half-partition it.
    """
    assert PARENT in partitioning.PARTITION_MAINTENANCE_ALLOWLIST
    assert "public.messages" not in partitioning.PARTITION_MAINTENANCE_ALLOWLIST
    with pytest.raises(ValueError):
        await partitioning.ensure_partition_for_month(db, "public.messages", _month_back(0))
    with pytest.raises(ValueError):
        await partitioning.purge_month(db, "public.audit_logs", _month_back(20))
