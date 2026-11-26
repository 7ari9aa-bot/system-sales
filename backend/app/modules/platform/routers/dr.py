"""Platform disaster recovery and tenant-scoped restore (§164).

A tenant that destroyed its own data (the §164 "3000 customers" incident)
restores it HERE — on the tenant plane, not the §160 admin plane, because
the job reads and revives tenant data. §143 tombstones keep soft-deleted
rows in place, so extraction/validation/execution run against the live
tables under the caller's RLS-bound session (the service re-binds to the
job's target tenant regardless); no other tenant's rows can be read or
revived, and a full production PITR is never overwritten for one tenant.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.modules.platform import schemas
from app.modules.platform.dr import DRService
from app.modules.platform.routers._deps import (
    TenantContext,
    TenantCtxDep,
    require_permission,
)
from app.modules.platform.tenant_restore import (
    TenantRestoreJob,
    TenantRestoreService,
)

router = APIRouter(prefix="/platform", tags=["platform"])


class TenantRestoreJobCreate(BaseModel):
    """Body for ``POST /platform/tenant-restores``."""

    backup_point: datetime
    entity_types: list[str] = Field(min_length=1)


def _restore_job_payload(job: TenantRestoreJob) -> dict:
    return {
        "id": str(job.id),
        "target_tenant_id": str(job.target_tenant_id),
        "backup_point": job.backup_point.isoformat() if job.backup_point else None,
        "entity_types": job.entity_types,
        "status": job.status,
        "extraction_results": job.extraction_results,
        "validation_results": job.validation_results,
        "restore_results": job.restore_results,
        "last_error": job.last_error,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.get("/dr")
async def get_dr_position(ctx: TenantCtxDep):
    """§70: the DR position as the merchant's settings screen must show it.

    Read-only, and deliberately evidence-shaped: the policy numbers (RPO, RTO,
    retention, PITR window, drill cadence) sit beside the last drill that
    actually ran, because "configured weekly" and "recoverable" are different
    claims and only the second one matters after an incident. Health comes from
    ``DRService.check_dr_health``, which reads recorded drill results, never the
    configured intent.
    """
    policy = await DRService.get_policy(ctx.session)
    health = await DRService.check_dr_health(ctx.session)
    runs = await DRService.list_restore_tests(ctx.session, limit=10)
    return {
        "rpo_minutes": policy.rpo_minutes,
        "rto_minutes": policy.rto_minutes,
        "backup_retention_days": policy.backup_retention_days,
        "pitr_window_days": policy.pitr_window_days,
        "restore_test_cron": policy.restore_test_cron,
        "last_restore_test_at": policy.last_restore_test_at.isoformat()
        if policy.last_restore_test_at
        else None,
        "last_restore_test_status": policy.last_restore_test_status,
        "restore_test_overdue": health["restore_test_overdue"],
        "healthy": health["healthy"],
        "restore_tests": [
            {
                "id": str(run.id),
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "restore_duration_seconds": run.restore_duration_seconds,
                "data_loss_seconds": run.data_loss_seconds,
                "errors": run.errors,
            }
            for run in runs
        ],
    }


@router.get("/tenant-restores", response_model=list[schemas.TenantRestoreJobOut])
async def list_tenant_restore_jobs(ctx: TenantCtxDep):
    """This tenant's restore jobs, newest first.

    The list exists so a merchant can see an incident it opened and never
    finished: a job stuck at ``pending`` or ``validated`` is visible evidence
    that a restore was started and not completed.
    """
    jobs = await TenantRestoreService.list_restore_jobs(ctx.session, ctx.tenant_id)
    return [_restore_job_payload(job) for job in jobs]


@router.post("/tenant-restores", response_model=schemas.TenantRestoreJobOut, status_code=201)
async def create_tenant_restore_job(
    body: TenantRestoreJobCreate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§164: open a restore job for the CALLER's tenant (never another's).

    ``backup_point`` is the incident watermark: rows tombstoned at or after
    it are the restore candidates; rows already dead before it predate the
    incident and stay dead.
    """
    job = await TenantRestoreService.create_restore_job(
        ctx.session,
        ctx.tenant_id,
        target_tenant_id=ctx.tenant_id,
        backup_point=body.backup_point,
        entity_types=body.entity_types,
    )
    return _restore_job_payload(job)


@router.get("/tenant-restores/{job_id}", response_model=schemas.TenantRestoreJobOut)
async def get_tenant_restore_job(ctx: TenantCtxDep, job_id: uuid.UUID):
    """One restore job's status + extraction/validation/restore manifests."""
    job = await TenantRestoreService.get_restore_job(ctx.session, ctx.tenant_id, job_id)
    return _restore_job_payload(job)


@router.post("/tenant-restores/{job_id}/extract", response_model=schemas.TenantRestoreJobOut)
async def extract_tenant_restore_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§164 step 2: stage the tenant's tombstoned rows into the job manifest.

    Tombstones live in the live tables, so the request session doubles as
    the recovery session; the full-PITR variant injects an isolated one.
    """
    job = await TenantRestoreService.extract_tenant_data(
        ctx.session,
        ctx.tenant_id,
        job_id,
        recovery_session=ctx.session,
    )
    return _restore_job_payload(job)


@router.post("/tenant-restores/{job_id}/validate", response_model=schemas.TenantRestoreJobOut)
async def validate_tenant_restore_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§164 step 3: re-check staged rows against current state.

    Any conflict (row already live, id collision, tenant mismatch, failed
    extraction) FAILS the job; only a clean validation unlocks execute.
    """
    job = await TenantRestoreService.validate_against_current(ctx.session, ctx.tenant_id, job_id)
    return _restore_job_payload(job)


@router.post("/tenant-restores/{job_id}/execute", response_model=schemas.TenantRestoreJobOut)
async def execute_tenant_restore_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§164 step 4: revive the staged tombstoned rows in one transaction.

    Refuses to run unless validation passed. Writes an audit row and stages
    ``tenant.restore.completed`` on the outbox in the same transaction.
    """
    job = await TenantRestoreService.execute_restore(ctx.session, ctx.tenant_id, job_id)
    return _restore_job_payload(job)
