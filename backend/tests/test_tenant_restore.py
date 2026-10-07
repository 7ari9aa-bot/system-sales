"""§164 regression — tenant-scoped restore works against real tombstones.

The §164 lifecycle (create → extract → validate → execute) was a stub:
``_extract_entity`` returned 0, so restore jobs staged and revived nothing.
These tests run the full lifecycle against real Postgres with FORCE RLS as
``sales_app`` (see conftest — every test rolls back), proving that:
  * extract stages the tenant's tombstoned rows (and NOT live rows),
  * validate detects real conflicts (revived rows, tenant mismatch),
  * execute revives exactly the staged accidental tombstones — never §143
    intentional deletions — and lands the audit row + outbox event in the
    same transaction.

Skips cleanly when DATABASE_URL_APP_ADMIN is unset (conftest ``db_url``);
CI runs it against real Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.customers.models import Customer
from app.modules.platform.models import AuditLog, OutboxEvent
from app.modules.platform.tenant_restore import (
    TenantRestoreJob,
    TenantRestoreService,
    TenantRestoreStatus,
)


def _unique_phone() -> str:
    return f"+2010{uuid.uuid4().hex[:8]}"


async def _make_customer(
    db: AsyncSession, tenant_id: uuid.UUID, *, name: str = "Restore Me"
) -> Customer:
    customer = Customer(tenant_id=tenant_id, name=name, phone=_unique_phone())
    db.add(customer)
    await db.flush()
    return customer


async def _tombstone(
    db: AsyncSession,
    customer: Customer,
    *,
    deleted_by: uuid.UUID | None = None,
    reason: str | None = None,
) -> None:
    """§143 soft-delete: tombstone in place, optionally intentional."""
    customer.deleted_at = datetime.now(UTC)
    customer.deleted_by = deleted_by
    customer.deletion_reason = reason
    await db.flush()


async def _make_job(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    target_tenant_id: uuid.UUID | None = None,
    entity_types: list[str] | None = None,
) -> TenantRestoreJob:
    """backup_point one hour back: anything tombstoned 'just now' is staged."""
    return await TenantRestoreService.create_restore_job(
        db,
        tenant_id,
        target_tenant_id=target_tenant_id or tenant_id,
        backup_point=datetime.now(UTC) - timedelta(hours=1),
        entity_types=entity_types if entity_types is not None else ["customers"],
    )


async def test_extract_stages_tombstoned_rows_but_not_live_ones(
    db: AsyncSession, tenant_ctx
) -> None:
    """create → tombstone → extract: the job manifest stages the dead row."""
    tenant_id = tenant_ctx.tenant_id
    dead = await _make_customer(db, tenant_id)
    live = await _make_customer(db, tenant_id, name="Still Here")
    await _tombstone(db, dead, deleted_by=tenant_ctx.user.id)

    job = await _make_job(db, tenant_id)
    job = await TenantRestoreService.extract_tenant_data(db, tenant_id, job.id, recovery_session=db)

    assert job.status == TenantRestoreStatus.VALIDATING.value
    staged = job.extraction_results["customers"]
    assert staged["count"] >= 1
    assert str(dead.id) in staged["ids"]
    assert str(live.id) not in staged["ids"]


async def test_execute_revives_rows_and_writes_audit_and_outbox(
    db: AsyncSession, tenant_ctx
) -> None:
    """Full lifecycle: tombstone revived, §143 intentional delete skipped."""
    tenant_id = tenant_ctx.tenant_id
    accidental = await _make_customer(db, tenant_id)
    intentional = await _make_customer(db, tenant_id, name="Erased By Request")
    await _tombstone(db, accidental, deleted_by=tenant_ctx.user.id)
    await _tombstone(
        db,
        intentional,
        deleted_by=tenant_ctx.user.id,
        reason="privacy_request",
    )

    job = await _make_job(db, tenant_id)
    job = await TenantRestoreService.extract_tenant_data(db, tenant_id, job.id, recovery_session=db)
    job = await TenantRestoreService.validate_against_current(db, tenant_id, job.id)

    assert job.status == TenantRestoreStatus.RESTORING.value
    check = job.validation_results["customers"]
    assert check["restorable"] == 1
    assert check["intentional_deletes"] == 1
    assert check["conflicts"] == 0

    job = await TenantRestoreService.execute_restore(db, tenant_id, job.id)

    assert job.status == TenantRestoreStatus.COMPLETED.value
    assert job.completed_at is not None
    assert job.restore_results["customers"] == {
        "restored": 1,
        "skipped": 1,
        "failed": 0,
    }

    await db.refresh(accidental)
    await db.refresh(intentional)
    assert accidental.deleted_at is None, "accidental tombstone must be revived"
    assert intentional.deleted_at is not None, "§143 erasures are never revived"

    events = list(
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_type == "tenant_restore_job",
                    OutboxEvent.aggregate_id == job.id,
                )
            )
        )
        .scalars()
        .all()
    )
    event_types = [e.payload["event_type"] for e in events]
    assert "tenant.restore.requested" in event_types
    assert "tenant.restore.completed" in event_types
    completed = next(e for e in events if e.payload["event_type"] == "tenant.restore.completed")
    assert completed.meta["aggregate_version"] == 1
    assert completed.payload["results"]["customers"]["restored"] == 1

    audits = list(
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.resource_type == "tenant_restore_job",
                    AuditLog.resource_id == str(job.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(a.action == "tenant.restore.completed" for a in audits)


async def test_validate_conflicts_when_staged_row_is_live_again(
    db: AsyncSession, tenant_ctx
) -> None:
    """Revived-between-extract-and-validate = conflict; job FAILS, no execute."""
    tenant_id = tenant_ctx.tenant_id
    customer = await _make_customer(db, tenant_id)
    await _tombstone(db, customer, deleted_by=tenant_ctx.user.id)

    job = await _make_job(db, tenant_id)
    job = await TenantRestoreService.extract_tenant_data(db, tenant_id, job.id, recovery_session=db)
    assert str(customer.id) in job.extraction_results["customers"]["ids"]

    # Someone revives the row before validation runs.
    customer.deleted_at = None
    customer.deleted_by = None
    await db.flush()

    job = await TenantRestoreService.validate_against_current(db, tenant_id, job.id)

    assert job.status == TenantRestoreStatus.FAILED.value
    assert job.last_error
    check = job.validation_results["customers"]
    assert check["conflicts"] >= 1
    assert {
        "id": str(customer.id),
        "reason": "already_live",
    } in check["conflict_details"]

    with pytest.raises(ValidationError):
        await TenantRestoreService.execute_restore(db, tenant_id, job.id)


async def test_validate_fails_when_target_tenant_is_not_the_job_tenant(
    db: AsyncSession, tenant_ctx
) -> None:
    """A job pointing at ANOTHER tenant is a tenant mismatch — never runs."""
    tenant_id = tenant_ctx.tenant_id
    other_tenant = uuid.uuid4()
    job = await _make_job(db, tenant_id, target_tenant_id=other_tenant)

    job = await TenantRestoreService.extract_tenant_data(db, tenant_id, job.id, recovery_session=db)
    # Nothing of ours is visible under the foreign tenant's RLS binding.
    assert job.extraction_results["customers"]["count"] == 0

    job = await TenantRestoreService.validate_against_current(db, tenant_id, job.id)

    assert job.status == TenantRestoreStatus.FAILED.value
    check = job.validation_results["customers"]
    assert check["conflicts"] >= 1
    assert any(detail["reason"] == "tenant_mismatch" for detail in check["conflict_details"])

    with pytest.raises(ValidationError):
        await TenantRestoreService.execute_restore(db, tenant_id, job.id)


async def test_execute_is_refused_before_validation_passes(db: AsyncSession, tenant_ctx) -> None:
    """A fresh PENDING job cannot be executed — validation is the gate."""
    tenant_id = tenant_ctx.tenant_id
    job = await _make_job(db, tenant_id)
    assert job.status == TenantRestoreStatus.PENDING.value

    with pytest.raises(ValidationError):
        await TenantRestoreService.execute_restore(db, tenant_id, job.id)


# ------------------------------------------- m16: fail-fast input gates ---


async def test_create_rejects_unknown_entity_types(db: AsyncSession, tenant_ctx) -> None:
    """An unsupported entity type fails at CREATION, not mid-extraction."""
    with pytest.raises(ValidationError, match="unsupported entity_types"):
        await _make_job(db, tenant_ctx.tenant_id, entity_types=["customers", "invoices"])


async def test_create_rejects_duplicate_entity_types(db: AsyncSession, tenant_ctx) -> None:
    """Duplicates would extract/validate/restore the same table twice."""
    with pytest.raises(ValidationError, match="duplicates"):
        await _make_job(db, tenant_ctx.tenant_id, entity_types=["orders", "orders"])


async def test_create_rejects_a_future_backup_point(db: AsyncSession, tenant_ctx) -> None:
    """A watermark in the future can never bound a completed deletion."""
    with pytest.raises(ValidationError, match="future"):
        await TenantRestoreService.create_restore_job(
            db,
            tenant_ctx.tenant_id,
            target_tenant_id=tenant_ctx.tenant_id,
            backup_point=datetime.now(UTC) + timedelta(hours=1),
            entity_types=["customers"],
        )


async def test_a_naive_backup_point_is_still_checked(db: AsyncSession, tenant_ctx) -> None:
    """Naive datetimes are read as UTC — a naive future point is rejected too."""
    with pytest.raises(ValidationError, match="future"):
        await TenantRestoreService.create_restore_job(
            db,
            tenant_ctx.tenant_id,
            target_tenant_id=tenant_ctx.tenant_id,
            backup_point=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            entity_types=["customers"],
        )

    job = await TenantRestoreService.create_restore_job(
        db,
        tenant_ctx.tenant_id,
        target_tenant_id=tenant_ctx.tenant_id,
        backup_point=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1),
        entity_types=["customers"],
    )
    assert job.status == TenantRestoreStatus.PENDING.value


async def test_validate_is_refused_before_extraction(db: AsyncSession, tenant_ctx) -> None:
    """m16: validate→execute with NO extract used to complete a zero-work
    job and still emit tenant.restore.completed + an audit row."""
    tenant_id = tenant_ctx.tenant_id
    job = await _make_job(db, tenant_id)

    with pytest.raises(ValidationError, match="extract"):
        await TenantRestoreService.validate_against_current(db, tenant_id, job.id)

    # The refusal staged no completion trail.
    completed = (
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == job.id,
                    OutboxEvent.payload["event_type"].astext == "tenant.restore.completed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert completed == []
