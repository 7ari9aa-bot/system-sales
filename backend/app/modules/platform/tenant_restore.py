"""Spec §164 — Tenant-scoped recovery.

When a tenant accidentally deletes data (e.g. 3000 customers), a full
database PITR is too heavy — it would overwrite all other tenants.

This service provides a tenant-scoped restore process:
    1. Restore backup to an isolated recovery database
    2. Extract the target tenant's records
    3. Validate against current state
    4. Restore selected records (respecting soft-delete/tombstones)

§164: "do not restore the entire production database over other tenants
because of a single Tenant incident."

Because §143 tombstones keep soft-deleted rows IN the live database, the
common "we deleted our own customers yesterday" incident needs no recovery
database at all: extraction stages the still-tombstoned rows (deleted_at at
or after the job's backup point), validation re-checks them against current
state, and execution clears the tombstones — all under the target tenant's
RLS binding, so no other tenant's row can ever be touched. The isolated
``recovery_session`` hook remains for the full PITR variant.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, String, Text, bindparam, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, bind_tenant
from app.core.errors import NotFoundError, ValidationError
from app.core.events.writer import add_outbox_event
from app.core.ids import uuid7
from app.core.model_kit import TenantMixin, TimestampMixin
from app.modules.platform.service import AuditService

logger = logging.getLogger(__name__)

# §143-tombstoned tables this service can restore. They all share the exact
# tombstone column set (tenant_id, id, deleted_at, deleted_by,
# deletion_reason), so one raw-SQL path serves every entity type. Raw SQL —
# not the per-module ORM models — is deliberate: platform -> customers /
# orders / conversations imports would create a NEW module import cycle
# (customers already imports platform.service) and grow the §8 cross-module
# ratchet past its baseline. The dict is also the SQL-injection whitelist:
# the interpolated table identifier can only ever be one of these literals.
_TOMBSTONED_TABLES: dict[str, str] = {
    "customers": "customers",
    "orders": "orders",
    "conversations": "conversations",
    "messages": "messages",
}

# Staged ids live in the job row's JSONB manifest; cap the list so a
# mass-delete of millions of rows cannot bloat the job row. The staged
# "count" stays exact even when the id list is truncated.
_MAX_STAGED_IDS = 10_000
# Conflict details are capped likewise — the conflict COUNT is always exact.
_MAX_CONFLICT_DETAILS = 100


class TenantRestoreStatus(StrEnum):
    PENDING = "pending"
    RESTORING_SNAPSHOT = "restoring_snapshot"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    RESTORING = "restoring"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TenantRestoreJob(TenantMixin, TimestampMixin, Base):
    """A tenant-scoped restore operation (§164).

    Tracks the full restore lifecycle: snapshot recovery → extraction →
    validation → selective restore.
    """

    __tablename__ = "tenant_restore_jobs"

    id: Mapped[uuid.UUID] = mapped_column(default=uuid7, primary_key=True)
    # The tenant to restore
    target_tenant_id: Mapped[uuid.UUID] = mapped_column()
    # PITR / backup point to restore from — TIMESTAMPTZ in the migration
    # (f9b0c1d2e3f4), so the model must declare timezone=True.
    backup_point: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Entity types to restore: ["customers", "orders", "messages", ...]
    entity_types: Mapped[list] = mapped_column(JSONB, server_default="[]")
    status: Mapped[str] = mapped_column(String(25), server_default="pending")
    # Recovery DB connection string (isolated)
    recovery_db_ref: Mapped[str | None] = mapped_column(String(255))
    # Extraction results: {entity_type: {count, ids: [...]}}
    extraction_results: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Validation results: {entity_type: {missing, conflicts, tombstoned}}
    validation_results: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Restore results: {entity_type: {restored, skipped, failed}}
    restore_results: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_tenant_restore_tenant_status", "tenant_id", "status"),)


class TenantRestoreService:
    """§164: tenant-scoped restore process.

    The restore is async (a scheduled job) and operates on an isolated
    recovery database — never on production directly. For tombstone-based
    restores the "recovery database" IS production: §143 soft-deletes keep
    the rows in place, so extraction just stages them.

    Every step binds its session to the job's target tenant before touching
    entity tables, so FORCE RLS makes cross-tenant access impossible even if
    a caller passed the wrong id. The service NEVER commits — every mutation
    flushes inside the caller's transaction, so a restore is atomic: all
    revives + the audit row + the outbox event land together or not at all.
    """

    @staticmethod
    async def create_restore_job(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        target_tenant_id: uuid.UUID,
        backup_point: datetime,
        entity_types: list[str],
    ) -> TenantRestoreJob:
        # m16 (§164): fail FAST. An unknown entity type used to be accepted
        # here and surface only as a per-entity extraction error deep inside
        # the job; a future backup_point can never bound a deletion window.
        unsupported = [e for e in entity_types if e not in _TOMBSTONED_TABLES]
        if unsupported:
            raise ValidationError(
                "unsupported entity_types for restore",
                details={
                    "unsupported": unsupported,
                    "supported": sorted(_TOMBSTONED_TABLES),
                },
            )
        if len(set(entity_types)) != len(entity_types):
            raise ValidationError(
                "entity_types must not contain duplicates",
                details={"entity_types": entity_types},
            )
        point = backup_point
        if point.tzinfo is None:
            point = point.replace(tzinfo=UTC)
        if point > datetime.now(UTC):
            raise ValidationError(
                "backup_point is in the future",
                details={"backup_point": backup_point.isoformat()},
            )
        job = TenantRestoreJob(
            tenant_id=tenant_id,
            target_tenant_id=target_tenant_id,
            backup_point=backup_point,
            entity_types=entity_types,
            status=TenantRestoreStatus.PENDING.value,
        )
        session.add(job)
        await session.flush()

        await add_outbox_event(
            session,
            aggregate_type="tenant_restore_job",
            aggregate_id=job.id,
            event_type="tenant.restore.requested",
            tenant_id=tenant_id,
            payload={
                "target_tenant_id": str(target_tenant_id),
                "entity_types": entity_types,
            },
            # Job rows have no VersionMixin; the request event is emitted
            # exactly once at creation, so the version is the constant 1.
            aggregate_version=1,
        )
        return job

    @staticmethod
    async def extract_tenant_data(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        *,
        recovery_session: AsyncSession,
    ) -> TenantRestoreJob:
        """Extract the target tenant's records from the recovery DB.

        Uses the isolated recovery_session (connected to the restored
        backup) to read records without touching production. For tombstone
        restores, pass the same session: the tombstoned rows are still in
        the live tables. The session is bound to the target tenant first,
        so FORCE RLS scopes every read to that tenant only.
        """
        job = await TenantRestoreService._get_job(session, tenant_id, job_id)
        job.status = TenantRestoreStatus.EXTRACTING.value
        await session.flush()

        await bind_tenant(recovery_session, job.target_tenant_id)

        results: dict[str, dict] = {}

        for entity_type in job.entity_types:
            try:
                count, ids = await TenantRestoreService._extract_entity(
                    recovery_session,
                    job.target_tenant_id,
                    entity_type,
                    window_start=job.backup_point,
                )
                results[entity_type] = {
                    "count": count,
                    "ids": ids,
                    "truncated": count > len(ids),
                }
            except Exception as exc:
                logger.error("extract %s failed: %s", entity_type, exc)
                results[entity_type] = {"count": 0, "ids": [], "error": str(exc)}

        # The job row lives under the JOB's tenant; restore that binding
        # before writing it (a no-op when session is not recovery_session
        # or when tenant_id == target_tenant_id).
        await bind_tenant(session, tenant_id)
        job.extraction_results = results
        job.status = TenantRestoreStatus.VALIDATING.value
        await session.flush()
        return job

    @staticmethod
    async def validate_against_current(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> TenantRestoreJob:
        """Compare the staged manifest against current production state.

        Per staged row, exactly one classification:
          * restorable — still tombstoned, no deletion_reason;
          * intentional_delete — tombstoned WITH a deletion_reason (§143:
            privacy erasures are never revived — skipped, not conflicted);
          * conflict ``already_live`` — the row is visible and no longer
            tombstoned: revived meanwhile, or the id collides with a live row;
          * conflict ``missing_or_tenant_mismatch`` — invisible under the
            target tenant's RLS binding: purged, or owned by another tenant
            (FORCE RLS correctly makes those indistinguishable).

        A job whose target tenant is not the tenant it was created under is
        itself a tenant mismatch. ANY conflict fails the job — and
        execute_restore refuses to run for anything but a validated job.
        """
        job = await TenantRestoreService._get_job(session, tenant_id, job_id)
        # m16 (§164): without this gate, validate→execute on a job that was
        # never extracted "completes" zero work and still emits
        # tenant.restore.completed + an audit row — a falsified trail.
        if not (job.extraction_results or {}):
            raise ValidationError(
                "restore job has no extraction manifest — run extract first",
                details={"job_id": str(job_id), "status": job.status},
            )
        await bind_tenant(session, job.target_tenant_id)

        tenant_mismatch = job.target_tenant_id != tenant_id

        validation: dict[str, dict] = {}
        total_conflicts = 0
        for entity_type, extraction in (job.extraction_results or {}).items():
            entry: dict = {
                "extracted_count": extraction.get("count", 0),
                "restorable": 0,
                "intentional_deletes": 0,
                "conflicts": 0,
                "conflict_details": [],
            }
            if "error" in extraction:
                entry["conflicts"] = 1
                entry["conflict_details"].append({"id": None, "reason": "extraction_failed"})
            elif tenant_mismatch:
                entry["conflicts"] = max(len(extraction.get("ids") or []), 1)
                entry["conflict_details"].append({"id": None, "reason": "tenant_mismatch"})
            else:
                entry = await TenantRestoreService._validate_entity(
                    session,
                    job.target_tenant_id,
                    entity_type,
                    extraction.get("ids") or [],
                    entry,
                )
            total_conflicts += entry["conflicts"]
            validation[entity_type] = entry

        await bind_tenant(session, tenant_id)
        job.validation_results = validation
        if total_conflicts:
            job.status = TenantRestoreStatus.FAILED.value
            job.last_error = f"validation found {total_conflicts} conflict(s)"
        else:
            job.status = TenantRestoreStatus.RESTORING.value
        await session.flush()
        return job

    @staticmethod
    async def execute_restore(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> TenantRestoreJob:
        """Restore the validated records into production.

        Runs ONLY after validation passed (status == restoring, zero
        conflicts). Every revive flushes on the caller's session — one
        transaction, never a commit: all revives + the AuditLog row + the
        outbox event commit together or not at all.

        Respects §143 tombstones — does not un-delete records that were
        intentionally deleted with a deletion_reason. The UPDATEs re-filter
        on ``deleted_at IS NOT NULL``, so a row revived between validate and
        execute is a harmless no-op rather than a double restore.

        The job row is read ``FOR UPDATE``: the status guard below and the
        ``status = 'completed'`` write at the end are one decision, and
        without the lock they are not atomic. §176 gate 17
        (``tests/gate/test_gate_tenant_restore.py``).
        """
        job = await TenantRestoreService._get_job(session, tenant_id, job_id, for_update=True)
        if job.status != TenantRestoreStatus.RESTORING.value:
            raise ValidationError(
                "restore job has not passed validation",
                details={"job_id": str(job_id), "status": job.status},
            )
        conflicts = sum(
            entry.get("conflicts", 0) for entry in (job.validation_results or {}).values()
        )
        if conflicts:
            raise ValidationError(
                "restore job has unresolved validation conflicts",
                details={"job_id": str(job_id), "conflicts": conflicts},
            )

        await bind_tenant(session, job.target_tenant_id)

        restore_results: dict[str, dict] = {}
        for entity_type, extraction in (job.extraction_results or {}).items():
            ids = extraction.get("ids") or []
            table = _TOMBSTONED_TABLES.get(entity_type)
            if not ids or table is None or "error" in extraction:
                restore_results[entity_type] = {
                    "restored": 0,
                    "skipped": 0,
                    "failed": 0,
                }
                continue
            restored, skipped = await TenantRestoreService._revive_entity(
                session, job.target_tenant_id, table, ids
            )
            restore_results[entity_type] = {
                "restored": restored,
                "skipped": skipped,
                "failed": max(len(ids) - restored - skipped, 0),
            }

        await AuditService.write(
            session,
            job.target_tenant_id,
            None,
            action="tenant.restore.completed",
            resource_type="tenant_restore_job",
            resource_id=str(job.id),
            after={
                "target_tenant_id": str(job.target_tenant_id),
                "entity_types": job.entity_types,
                "restore_results": restore_results,
            },
        )
        await add_outbox_event(
            session,
            aggregate_type="tenant_restore_job",
            aggregate_id=job.id,
            event_type="tenant.restore.completed",
            tenant_id=tenant_id,
            payload={
                "job_id": str(job.id),
                "target_tenant_id": str(job.target_tenant_id),
                "results": restore_results,
            },
            # Job rows have no VersionMixin; completion is emitted exactly
            # once (the status guard above forbids re-execution), so the
            # version is the constant 1.
            aggregate_version=1,
        )

        # The job row lives under the JOB's tenant; restore that binding
        # before writing it (a no-op when tenant_id == target_tenant_id).
        await bind_tenant(session, tenant_id)
        job.restore_results = restore_results
        job.status = TenantRestoreStatus.COMPLETED.value
        job.completed_at = datetime.now(UTC)
        await session.flush()
        return job

    @staticmethod
    async def get_restore_job(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> TenantRestoreJob:
        """Read one restore job owned by the calling tenant."""
        return await TenantRestoreService._get_job(session, tenant_id, job_id)

    @staticmethod
    async def _get_job(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> TenantRestoreJob:
        """Read one job of this tenant, optionally locking its row.

        ``for_update`` exists for the ONE path where a guard and a state
        transition must be atomic: ``execute_restore`` decides on
        ``status == 'restoring'`` and later writes ``status = 'completed'``.
        Read without the lock, two concurrent Execute calls — a double click,
        or a client retry on a slow restore — both pass the guard, both emit
        ``tenant.restore.completed`` and both write an audit row, and the
        loser reports ``restored: 0, failed: N`` for work that did happen
        (§177.6: every side effect idempotent). With the lock the second
        caller waits, re-reads ``completed`` under READ COMMITTED, and is
        refused.
        """
        stmt = select(TenantRestoreJob).where(
            TenantRestoreJob.tenant_id == tenant_id,
            TenantRestoreJob.id == job_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        job = (await session.execute(stmt)).scalar_one_or_none()
        if job is None:
            raise NotFoundError("tenant restore job not found")
        return job

    @staticmethod
    async def _extract_entity(
        recovery_session: AsyncSession,
        tenant_id: uuid.UUID,
        entity_type: str,
        *,
        window_start: datetime,
    ) -> tuple[int, list[str]]:
        """Stage the tenant's tombstoned rows of one entity type.

        Selects rows soft-deleted within the retention window — deleted_at
        at or after ``window_start`` (the job's backup point: rows already
        dead at the backup point predate the incident and are not the
        tenant's loss). Returns the exact tombstoned count plus the staged
        id list (capped at _MAX_STAGED_IDS, oldest deletions first).
        """
        table = _TOMBSTONED_TABLES.get(entity_type)
        if table is None:
            raise ValidationError(
                f"unknown restorable entity type: {entity_type!r}",
                details={
                    "entity_type": entity_type,
                    "allowed": sorted(_TOMBSTONED_TABLES),
                },
            )
        count = int(
            (
                await recovery_session.execute(
                    text(
                        # table is a _TOMBSTONED_TABLES literal, never input
                        f"SELECT count(*) FROM {table} "
                        "WHERE tenant_id = :tenant_id "
                        "AND deleted_at IS NOT NULL "
                        "AND deleted_at >= :window_start"
                    ),
                    {"tenant_id": tenant_id, "window_start": window_start},
                )
            ).scalar_one()
        )
        rows = (
            await recovery_session.execute(
                text(
                    f"SELECT id FROM {table} "
                    "WHERE tenant_id = :tenant_id "
                    "AND deleted_at IS NOT NULL "
                    "AND deleted_at >= :window_start "
                    "ORDER BY deleted_at ASC "
                    "LIMIT :limit"
                ),
                {
                    "tenant_id": tenant_id,
                    "window_start": window_start,
                    "limit": _MAX_STAGED_IDS,
                },
            )
        ).all()
        return count, [str(row.id) for row in rows]

    @staticmethod
    async def _validate_entity(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        entity_type: str,
        staged_ids: list[str],
        entry: dict,
    ) -> dict:
        """Classify every staged id against the row's CURRENT state."""
        table = _TOMBSTONED_TABLES.get(entity_type)
        if table is None:
            entry["conflicts"] = 1
            entry["conflict_details"].append({"id": None, "reason": "unknown_entity_type"})
            return entry
        if not staged_ids:
            return entry
        rows = (
            await session.execute(
                text(
                    f"SELECT id, deleted_at, deletion_reason FROM {table} "
                    "WHERE tenant_id = :tenant_id AND id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {
                    "tenant_id": tenant_id,
                    "ids": [uuid.UUID(sid) for sid in staged_ids],
                },
            )
        ).all()
        current = {str(row.id): row for row in rows}
        for sid in staged_ids:
            row = current.get(sid)
            if row is None:
                reason = "missing_or_tenant_mismatch"
            elif row.deleted_at is None:
                reason = "already_live"
            elif row.deletion_reason is not None:
                entry["intentional_deletes"] += 1
                continue
            else:
                entry["restorable"] += 1
                continue
            entry["conflicts"] += 1
            if len(entry["conflict_details"]) < _MAX_CONFLICT_DETAILS:
                entry["conflict_details"].append({"id": sid, "reason": reason})
        return entry

    @staticmethod
    async def _revive_entity(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        table: str,
        staged_ids: list[str],
    ) -> tuple[int, int]:
        """Clear tombstones for the staged ids. Returns (restored, skipped).

        ``skipped`` counts staged rows with a deletion_reason — intentional
        §143 deletions the restore must not un-delete.
        """
        ids = [uuid.UUID(sid) for sid in staged_ids]
        revived = await session.execute(
            text(
                f"UPDATE {table} "
                "SET deleted_at = NULL, deleted_by = NULL "
                "WHERE tenant_id = :tenant_id AND id IN :ids "
                "AND deleted_at IS NOT NULL AND deletion_reason IS NULL"
            ).bindparams(bindparam("ids", expanding=True)),
            {"tenant_id": tenant_id, "ids": ids},
        )
        skipped = int(
            (
                await session.execute(
                    text(
                        f"SELECT count(*) FROM {table} "
                        "WHERE tenant_id = :tenant_id AND id IN :ids "
                        "AND deleted_at IS NOT NULL "
                        "AND deletion_reason IS NOT NULL"
                    ).bindparams(bindparam("ids", expanding=True)),
                    {"tenant_id": tenant_id, "ids": ids},
                )
            ).scalar_one()
        )
        return revived.rowcount or 0, skipped
