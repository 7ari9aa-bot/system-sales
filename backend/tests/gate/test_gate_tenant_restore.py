"""§176 gate scenario 17 — tenant restore under real commits, real tenants, real races.

§164 promises a tenant that destroyed its own data can restore it without
touching anybody else, and §143 promises that an erasure a customer asked for
is NEVER undone. ``tests/test_tenant_restore.py`` already walks that lifecycle
— inside ONE transaction on ONE connection, which is rolled back.

That harness cannot see the three things this gate exists to prove, because
none of them exist inside a single transaction:

* **cross-connection isolation**: another tenant's connection — and an
  UNBOUND one — must not see or revive a row the restore touched, after the
  restore has COMMITTED (migration ``c166dd166dd1`` claims exactly this and
  nothing measured it until now);
* **a manifest that lies**: a job whose staged ids name another tenant's rows
  must fail validation and stay unexecuted;
* **the window between validate and execute**: a §143 privacy erasure that
  COMMITS in that window must still be honoured, and one restore must still
  publish exactly one completion event however many callers press Execute.

So every test below opens INDEPENDENT connections and commits, exactly like
``test_gate_oversell.py`` does. DB-backed: needs PostgreSQL as the
non-BYPASSRLS ``sales_app`` role; skips via ``db_url`` otherwise — a skip is
not a pass, so this file is CI-only evidence, clearly labelled.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import bind_tenant
from app.core.errors import ValidationError
from app.modules.customers.models import Customer
from app.modules.identity.models import Tenant
from app.modules.platform.tenant_restore import (
    TenantRestoreService,
    TenantRestoreStatus,
)

pytestmark = [pytest.mark.gate]

BACKUP_WINDOW_HOURS = 1


def _as_dict(value: object) -> dict:
    """A JSONB manifest read back through raw SQL may be a dict or a str."""
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)  # type: ignore[call-overload]


# ---------------------------------------------------------------------------
# harness: committed rows on independent connections
# ---------------------------------------------------------------------------


@pytest.fixture
async def restore_engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        db_url,
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@asynccontextmanager
async def _tx(
    engine: AsyncEngine, tenant_id: uuid.UUID | None = None
) -> AsyncIterator[AsyncSession]:
    """One independent connection, one transaction, COMMITTED on exit.

    ``tenant_id=None`` leaves ``app.tenant_id`` genuinely unbound — what a
    worker or a mis-scoped caller sees. An exception rolls the transaction
    back, exactly like the request session when the service refuses.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            if tenant_id is not None:
                await bind_tenant(session, tenant_id)
            yield session


async def _seed_tenant(
    engine: AsyncEngine, label: str, *, tombstoned: int
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Commit a tenant with `tombstoned` §143 soft-deleted customers.

    ``deleted_at`` sits inside the backup window, so extract must stage every
    one of them — that is the incident this scenario is about.
    """
    ids: list[uuid.UUID] = []
    async with _tx(engine) as session:
        tenant = Tenant(slug=f"restore-{label}-{uuid.uuid4().hex[:8]}", name=label)
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id
        await bind_tenant(session, tenant_id)
        for _ in range(tombstoned):
            customer = Customer(
                tenant_id=tenant_id,
                name=f"{label} lost row",
                phone=f"+2011{uuid.uuid4().hex[:8]}",
                deleted_at=datetime.now(UTC) - timedelta(minutes=5),
            )
            session.add(customer)
            await session.flush()
            ids.append(customer.id)
    return tenant_id, ids


async def _cleanup(engine: AsyncEngine, tenant_id: uuid.UUID) -> None:
    """Best-effort: a cleanup failure must never mask an assertion."""
    try:
        async with _tx(engine, tenant_id) as session:
            await session.execute(
                text(
                    "DELETE FROM outbox_events "
                    "WHERE aggregate_type = 'tenant_restore_job' AND aggregate_id IN ("
                    "  SELECT id FROM tenant_restore_jobs WHERE tenant_id = :t)"
                ),
                {"t": tenant_id},
            )
            for table in ("customers", "tenant_restore_jobs", "audit_logs"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
        async with _tx(engine) as session:
            await session.execute(
                text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id}
            )
    except Exception:  # noqa: BLE001
        pass


async def _customer(engine: AsyncEngine, tenant_id: uuid.UUID, customer_id: uuid.UUID):
    """One customer's tombstone state, read from a FRESH committed connection."""
    async with _tx(engine, tenant_id) as session:
        return (
            await session.execute(
                text("SELECT deleted_at, deletion_reason FROM customers WHERE id = :i"),
                {"i": customer_id},
            )
        ).first()


async def _job(engine: AsyncEngine, tenant_id: uuid.UUID, job_id: uuid.UUID):
    async with _tx(engine, tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT status, extraction_results, validation_results, "
                    "restore_results FROM tenant_restore_jobs WHERE id = :j"
                ),
                {"j": job_id},
            )
        ).first()


async def _restore_events(engine: AsyncEngine, job_id: uuid.UUID) -> list[str]:
    async with _tx(engine) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload->>'event_type' FROM outbox_events "
                    "WHERE aggregate_type = 'tenant_restore_job' "
                    "AND aggregate_id = :j ORDER BY created_at"
                ),
                {"j": job_id},
            )
        ).scalars()
        return list(rows.all())


async def _audit_writes(
    engine: AsyncEngine, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> int:
    async with _tx(engine, tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_logs "
                        "WHERE resource_type = 'tenant_restore_job' "
                        "AND resource_id = :j AND action = 'tenant.restore.completed'"
                    ),
                    {"j": str(job_id)},
                )
            ).scalar_one()
        )


async def _create(engine: AsyncEngine, tenant_id: uuid.UUID) -> uuid.UUID:
    async with _tx(engine, tenant_id) as session:
        job = await TenantRestoreService.create_restore_job(
            session,
            tenant_id,
            target_tenant_id=tenant_id,
            backup_point=datetime.now(UTC) - timedelta(hours=BACKUP_WINDOW_HOURS),
            entity_types=["customers"],
        )
        return job.id


async def _extract(engine: AsyncEngine, tenant_id: uuid.UUID, job_id: uuid.UUID) -> None:
    async with _tx(engine, tenant_id) as session:
        await TenantRestoreService.extract_tenant_data(
            session, tenant_id, job_id, recovery_session=session
        )


async def _validate(
    engine: AsyncEngine, tenant_id: uuid.UUID, job_id: uuid.UUID
):
    async with _tx(engine, tenant_id) as session:
        return await TenantRestoreService.validate_against_current(
            session, tenant_id, job_id
        )


async def _execute(engine: AsyncEngine, tenant_id: uuid.UUID, job_id: uuid.UUID):
    async with _tx(engine, tenant_id) as session:
        return await TenantRestoreService.execute_restore(session, tenant_id, job_id)


# ---------------------------------------------------------------------------
# §176.17 + §176.1 — a committed restore is invisible to everyone else
# ---------------------------------------------------------------------------


async def test_gate_a_committed_restore_revives_only_its_own_tenant(
    restore_engine,
) -> None:
    """Cross-tenant isolation measured ACROSS connections, after COMMIT.

    A rollback-only harness hides this completely: on one connection, a policy
    that never fired still looks correct. Here tenant B reads on its own
    backend, and an UNBOUND connection reads the job table — both must come
    back empty-handed.
    """
    tenant_a, rows_a = await _seed_tenant(restore_engine, "a", tombstoned=2)
    tenant_b, rows_b = await _seed_tenant(restore_engine, "b", tombstoned=1)
    try:
        job_id = await _create(restore_engine, tenant_a)
        await _extract(restore_engine, tenant_a, job_id)
        await _validate(restore_engine, tenant_a, job_id)
        await _execute(restore_engine, tenant_a, job_id)

        # A's rows are alive again — and A only knows it because it COMMITTED.
        for customer_id in rows_a:
            row = await _customer(restore_engine, tenant_a, customer_id)
            assert row is not None
            assert row.deleted_at is None, "accidental tombstone must be revived"
            assert row.deletion_reason is None

        # B's rows never moved.
        for customer_id in rows_b:
            row = await _customer(restore_engine, tenant_b, customer_id)
            assert row is not None
            assert row.deleted_at is not None, "§164 restore reached another tenant"

        # B cannot even see that a restore happened, and neither can a caller
        # that forgot to bind a tenant — migration c166dd166dd1's whole point.
        async with _tx(restore_engine, tenant_b) as session:
            visible_to_b = (
                await session.execute(text("SELECT count(*) FROM tenant_restore_jobs"))
            ).scalar_one()
        assert visible_to_b == 0, "tenant B read tenant A's restore job"

        async with _tx(restore_engine) as session:
            visible_unbound = (
                await session.execute(text("SELECT count(*) FROM tenant_restore_jobs"))
            ).scalar_one()
        assert visible_unbound == 0, "an unbound session read a restore job"

        assert await _restore_events(restore_engine, job_id) == [
            "tenant.restore.requested",
            "tenant.restore.completed",
        ]
    finally:
        await _cleanup(restore_engine, tenant_a)
        await _cleanup(restore_engine, tenant_b)


async def test_gate_a_lie_in_the_manifest_is_refused_before_anything_moves(
    restore_engine,
) -> None:
    """A staged id belonging to another tenant fails validation — and stays dead.

    ``extraction_results`` is the restore's work order. Whatever put a foreign
    id into it — a bad backup, an operator edit, a compromised job row — the
    guard must be FORCE RLS plus validation, never trust in the manifest.
    """
    tenant_a, rows_a = await _seed_tenant(restore_engine, "forged-a", tombstoned=1)
    tenant_b, rows_b = await _seed_tenant(restore_engine, "forged-b", tombstoned=1)
    try:
        job_id = await _create(restore_engine, tenant_a)
        await _extract(restore_engine, tenant_a, job_id)

        # Tamper: point the work order at tenant B's tombstoned customer too.
        async with _tx(restore_engine, tenant_a) as session:
            manifest = _as_dict(
                (
                    await session.execute(
                        text(
                            "SELECT extraction_results::text FROM tenant_restore_jobs "
                            "WHERE id = :j"
                        ),
                        {"j": job_id},
                    )
                ).scalar_one()
            )
            manifest["customers"]["ids"].append(str(rows_b[0]))
            manifest["customers"]["count"] = len(manifest["customers"]["ids"])
            await session.execute(
                text(
                    "UPDATE tenant_restore_jobs "
                    "SET extraction_results = CAST(:m AS jsonb) WHERE id = :j"
                ),
                {"m": json.dumps(manifest), "j": job_id},
            )

        job = await _validate(restore_engine, tenant_a, job_id)
        assert job.status == TenantRestoreStatus.FAILED.value
        check = _as_dict(job.validation_results)["customers"]
        assert check["conflicts"] >= 1
        assert {
            "id": str(rows_b[0]),
            "reason": "missing_or_tenant_mismatch",
        } in check["conflict_details"], check["conflict_details"]

        # Execute refuses the WHOLE job — A's own row stays dead too, because
        # a poisoned manifest is not partially trusted.
        with pytest.raises(ValidationError, match="not passed validation"):
            await _execute(restore_engine, tenant_a, job_id)

        b_row = await _customer(restore_engine, tenant_b, rows_b[0])
        assert b_row is not None and b_row.deleted_at is not None, (
            "a refused cross-tenant manifest still revived another tenant's row"
        )
        a_row = await _customer(restore_engine, tenant_a, rows_a[0])
        assert a_row is not None and a_row.deleted_at is not None
        assert "tenant.restore.completed" not in await _restore_events(
            restore_engine, job_id
        )
    finally:
        await _cleanup(restore_engine, tenant_a)
        await _cleanup(restore_engine, tenant_b)


# ---------------------------------------------------------------------------
# §143 × §164 — the erasure that lands in the validate/execute window
# ---------------------------------------------------------------------------


async def test_gate_a_privacy_erasure_committed_mid_flight_is_not_resurrected(
    restore_engine,
) -> None:
    """Validation said "restorable"; a deletion request then COMMITTED anyway.

    Validate and execute are two separate committed transactions (two HTTP
    requests, or a scheduled retry), so the gap between them is real time.
    ``_revive_entity`` re-filters on ``deletion_reason IS NULL`` inside its
    UPDATE, and that is the ONLY thing standing between a customer's erasure
    request and a bulk restore undoing it. Asserted here on the row, the
    manifest AND the job's own report.
    """
    tenant_a, ids = await _seed_tenant(restore_engine, "privacy", tombstoned=2)
    keep, erased = ids
    try:
        job_id = await _create(restore_engine, tenant_a)
        await _extract(restore_engine, tenant_a, job_id)
        job = await _validate(restore_engine, tenant_a, job_id)
        assert _as_dict(job.validation_results)["customers"]["restorable"] == 2

        # Between validation and execution a §143 erasure is committed by
        # another connection — a different request, a different backend.
        async with _tx(restore_engine, tenant_a) as session:
            await session.execute(
                text(
                    "UPDATE customers SET deletion_reason = 'customer_request', "
                    "deleted_at = :now WHERE id = :i"
                ),
                {"i": erased, "now": datetime.now(UTC)},
            )

        await _execute(restore_engine, tenant_a, job_id)

        alive = await _customer(restore_engine, tenant_a, keep)
        assert alive is not None and alive.deleted_at is None, (
            "the accidental tombstone next to the erasure was not revived"
        )
        dead = await _customer(restore_engine, tenant_a, erased)
        assert dead is not None
        assert dead.deleted_at is not None, (
            "§143: a privacy erasure committed mid-flight was resurrected"
        )
        assert dead.deletion_reason == "customer_request"

        done = await _job(restore_engine, tenant_a, job_id)
        assert done.status == TenantRestoreStatus.COMPLETED.value
        assert _as_dict(done.restore_results)["customers"] == {
            "restored": 1,
            "skipped": 1,
            "failed": 0,
        }, "the job's own report hides that it honoured the erasure"
    finally:
        await _cleanup(restore_engine, tenant_a)


# ---------------------------------------------------------------------------
# §177.6 — one restore, one completion event, however many callers press Execute
# ---------------------------------------------------------------------------


async def test_gate_concurrent_execute_publishes_one_completion(
    restore_engine,
) -> None:
    """Two callers, one validated job, TWO REAL BACKENDS, one restore.

    ``status == 'restoring'`` is the guard and the write of ``'completed'`` is
    what makes it one-shot — so the read and the write must be atomic, or a
    double click (a client retry over a slow link) runs the restore twice:
    two ``tenant.restore.completed`` events on the bus, and for the loser a
    record saying ``restored: 0, failed: N`` about work that DID happen. A
    duplicated side effect plus a falsified audit trail.
    """
    callers = 2
    tenant_a, rows_a = await _seed_tenant(restore_engine, "race", tombstoned=2)
    try:
        job_id = await _create(restore_engine, tenant_a)
        await _extract(restore_engine, tenant_a, job_id)
        await _validate(restore_engine, tenant_a, job_id)

        barrier = asyncio.Barrier(callers)
        outcomes: list[str] = []
        backends: list[int] = []

        async def caller() -> None:
            async with _tx(restore_engine, tenant_a) as session:
                # Hold both transactions open until BOTH are inside, so the
                # status check really does race the status write.
                backend = (
                    await session.execute(text("SELECT pg_backend_pid()"))
                ).scalar_one()
                backends.append(int(backend))
                await barrier.wait()
                try:
                    await TenantRestoreService.execute_restore(
                        session, tenant_a, job_id
                    )
                except ValidationError as exc:
                    outcomes.append(f"refused: {exc.message}")
                else:
                    outcomes.append("completed")

        await asyncio.wait_for(
            asyncio.gather(*(caller() for _ in range(callers))), timeout=90
        )

        assert len(set(backends)) == callers, f"callers shared a backend: {backends}"

        for customer_id in rows_a:
            row = await _customer(restore_engine, tenant_a, customer_id)
            assert row is not None and row.deleted_at is None, (
                f"nobody revived the tenant's row: {outcomes}"
            )

        completed = [
            event
            for event in await _restore_events(restore_engine, job_id)
            if event == "tenant.restore.completed"
        ]
        assert len(completed) == 1, (
            f"{outcomes} -> {len(completed)} completion events for one restore "
            "(§177.6: every side effect must be idempotent)"
        )
        assert await _audit_writes(restore_engine, tenant_a, job_id) == 1, (
            f"{outcomes} -> a duplicated audit trail for one restore"
        )

        done = await _job(restore_engine, tenant_a, job_id)
        assert done.status == TenantRestoreStatus.COMPLETED.value
        assert _as_dict(done.restore_results)["customers"] == {
            "restored": 2,
            "skipped": 0,
            "failed": 0,
        }, (
            f"{outcomes} -> the surviving record misreports a restore that "
            f"succeeded: {done.restore_results}"
        )
    finally:
        await _cleanup(restore_engine, tenant_a)
