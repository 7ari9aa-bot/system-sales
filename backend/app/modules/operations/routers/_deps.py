"""Shared routers, dependencies, and helpers for operations."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.errors import NotFoundError
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.identity.deps import (
    TenantCtxDep as TenantCtxDep,  # noqa: F401  — re-exported for the routers
)
from app.modules.operations.schemas import (
    BusinessCalendarOut,
    JobOut,
    SLAPolicyOut,
    SLOMeasurement,
)
from app.modules.platform.models import Job

router = APIRouter(tags=["operations"])
search_router = APIRouter(prefix="/search", tags=["search"])
sla_router = APIRouter(prefix="/sla", tags=["sla"])

SettingsCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

JOB_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
JOB_RETRYABLE_STATUSES = frozenset({"failed", "cancelled"})


def job_can_retry(status: str) -> bool:
    """Whether ``POST /jobs/{id}/retry`` is allowed for this status."""
    return status in JOB_RETRYABLE_STATUSES


def job_can_cancel(status: str) -> bool:
    """Whether ``POST /jobs/{id}/cancel`` is allowed — never on a terminal job."""
    return status not in JOB_TERMINAL_STATUSES


def _policy_out(policy) -> SLAPolicyOut:
    return SLAPolicyOut(
        id=policy.id,
        name=policy.name,
        first_response_minutes=policy.first_response_minutes,
        resolution_minutes=policy.resolution_minutes,
        applies_to_channel=policy.applies_to_channel,
        is_default=policy.is_default,
        status=policy.status,
    )


def _calendar_out(calendar) -> BusinessCalendarOut:
    return BusinessCalendarOut(
        id=calendar.id,
        name=calendar.name,
        timezone=calendar.timezone,
        hours=calendar.hours or {},
        holidays=calendar.holidays or [],
        is_default=calendar.is_default,
    )


def _job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        last_error=job.last_error,
        result=job.result,
        correlation_id=job.correlation_id,
        actor_user_id=job.actor_user_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _slo_out(result) -> SLOMeasurement:
    return SLOMeasurement(
        name=result.name,
        compliance_percent=result.compliance_percent,
        total=result.total,
        met=result.met,
        target_percent=result.target_percent,
        status=result.status,
        window_since=result.window_since,
    )


async def _load_job(ctx: TenantContext, job_id: uuid.UUID) -> Job:
    """Fetch one job scoped to the caller's tenant; 404 rather than leak."""
    from sqlalchemy import select

    job = (
        await ctx.session.execute(
            select(Job).where(Job.tenant_id == ctx.tenant_id, Job.id == job_id)
        )
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("job not found")
    return job
