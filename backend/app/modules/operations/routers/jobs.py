"""Jobs, scheduled jobs, and tenant fairness endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Query
from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.operations.schemas import (
    FairnessBucket,
    FairnessCheckResult,
    JobList,
    JobOut,
    ScheduledJobReschedule,
    ScheduledJobRescheduleResult,
    ScheduledJobStatusResult,
)

from ._deps import (
    Job,
    SettingsCtx,
    TenantCtxDep,
    _job_out,
    _load_job,
    job_can_cancel,
    job_can_retry,
    router,
)


@router.get("/jobs", response_model=JobList)
async def list_jobs(
    ctx: TenantCtxDep,
    status: str | None = None,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Newest-first jobs for the tenant, optionally filtered by status/kind."""
    stmt = select(Job).where(Job.tenant_id == ctx.tenant_id)
    if status:
        stmt = stmt.where(Job.status == status)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    rows = (
        (
            await ctx.session.execute(
                stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return JobList(items=[_job_out(job) for job in rows])


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(ctx: TenantCtxDep, job_id: uuid.UUID) -> JobOut:
    """One job's full record — status, progress, attempts, error and result."""
    return _job_out(await _load_job(ctx, job_id))


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
async def retry_job(
    job_id: uuid.UUID,
    ctx: SettingsCtx,
) -> JobOut:
    """Re-queue a job that stopped without succeeding."""
    job = await _load_job(ctx, job_id)
    if not job_can_retry(job.status):
        raise ConflictError(
            f"job is {job.status} and cannot be retried",
            details={"job_id": str(job.id), "status": job.status},
        )
    job.status = "queued"
    job.attempts = 0
    job.progress = 0
    job.last_error = None
    await ctx.session.flush()
    return _job_out(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: uuid.UUID,
    ctx: SettingsCtx,
) -> JobOut:
    """Cancel a job that has not reached a terminal state."""
    job = await _load_job(ctx, job_id)
    if not job_can_cancel(job.status):
        raise ConflictError(
            f"job is {job.status} and cannot be cancelled",
            details={"job_id": str(job.id), "status": job.status},
        )
    job.status = "cancelled"
    await ctx.session.flush()
    return _job_out(job)


@router.get("/fairness/usage", response_model=dict[str, FairnessBucket])
async def fairness_usage(ctx: TenantCtxDep):
    """§144: current tenant's resource usage against fairness budgets."""
    from app.core.fairness import get_usage

    return await get_usage(ctx.tenant_id)


@router.get("/fairness/check", response_model=FairnessCheckResult)
async def fairness_check(
    ctx: TenantCtxDep,
    resource: Annotated[
        str,
        Query(
            description="ai_tokens | messages_outbound | storage_bytes | worker_seconds",
        ),
    ],
    units: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
):
    """§144: pre-flight check — does the tenant have `units` remaining?"""
    from app.core.fairness import ResourceType, check_budget

    try:
        res = ResourceType(resource)
    except ValueError as err:
        raise ValidationError(
            f"unknown resource type: {resource}",
            details={"valid_types": [r.value for r in ResourceType]},
        ) from err
    result = await check_budget(ctx.tenant_id, res, units=units)
    return FairnessCheckResult(
        resource=result.resource.value,
        limit=result.limit,
        current_usage=result.current_usage,
        remaining=result.remaining,
        allowed=result.allowed,
    )


@router.post("/scheduled-jobs/{job_id}/cancel", response_model=ScheduledJobStatusResult)
async def cancel_scheduled_job(
    job_id: uuid.UUID,
    ctx: SettingsCtx,
) -> ScheduledJobStatusResult:
    """§154: cancel a queued/retrying scheduled job."""
    from app.modules.platform.models import ScheduledJob

    job = (
        await ctx.session.execute(
            select(ScheduledJob).where(
                ScheduledJob.tenant_id == ctx.tenant_id, ScheduledJob.id == job_id
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("scheduled job not found")
    if job.status in ("completed", "failed", "cancelled"):
        raise ConflictError(
            f"scheduled job is {job.status} and cannot be cancelled",
        )
    job.status = "cancelled"
    job.cancelled_at = datetime.now(UTC)
    await ctx.session.flush()
    return ScheduledJobStatusResult(id=job.id, status=job.status)


@router.post("/scheduled-jobs/{job_id}/reschedule", response_model=ScheduledJobRescheduleResult)
async def reschedule_scheduled_job(
    job_id: uuid.UUID,
    body: ScheduledJobReschedule,
    ctx: SettingsCtx,
) -> ScheduledJobRescheduleResult:
    """§154: move a scheduled job's run_at."""
    from app.modules.platform.models import ScheduledJob

    job = (
        await ctx.session.execute(
            select(ScheduledJob).where(
                ScheduledJob.tenant_id == ctx.tenant_id, ScheduledJob.id == job_id
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("scheduled job not found")
    if job.status == "processing":
        raise ConflictError("cannot reschedule a job that is currently processing")
    job.run_at = body.run_at
    job.status = "queued"
    await ctx.session.flush()
    return ScheduledJobRescheduleResult(id=job.id, status=job.status, run_at=job.run_at)
