"""OPERATIONS routes — tasks (§83) + search (§45) + SLA (§46)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.search import get_search
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.operations.models import Task
from app.modules.operations.task_service import TaskService  # §13-14
from app.modules.platform.models import Job

router = APIRouter(tags=["operations"])
search_router = APIRouter(prefix="/search", tags=["search"])
sla_router = APIRouter(prefix="/sla", tags=["sla"])

SettingsCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    assignee_user_id: uuid.UUID | None = None
    due_date: str | None = None
    priority: int = 2


class TaskUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(todo|in_progress|done|cancelled)$")
    assignee_user_id: uuid.UUID | None = None
    priority: int | None = None


@router.get("/tasks")
async def list_tasks(
    ctx: TenantCtxDep,
    status: str | None = None,
    mine: bool = False,
    customer_id: uuid.UUID | None = None,
):
    from sqlalchemy import select

    stmt = select(Task).where(Task.tenant_id == ctx.tenant_id)
    if status:
        stmt = stmt.where(Task.status == status)
    if mine:
        stmt = stmt.where(Task.assignee_user_id == ctx.user.id)
    if customer_id is not None:
        # Customer 360: tasks attach polymorphically, so a customer's tasks
        # are the ones whose related entity points at that customer.
        stmt = stmt.where(
            Task.related_entity_type == "customer",
            Task.related_entity_id == customer_id,
        )
    rows = (
        await ctx.session.execute(stmt.order_by(Task.created_at.desc()).limit(100))
    ).scalars().all()
    return [
        {
            "id": str(t.id),
            "title": t.title,
            "status": t.status,
            "priority": t.priority,
            "assignee_user_id": str(t.assignee_user_id) if t.assignee_user_id else None,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "source": t.source,
        }
        for t in rows
    ]


@router.post("/tasks", status_code=201)
async def create_task(ctx: TenantCtxDep, body: TaskCreate):
    # §13-14: route through TaskService — no direct model construction.
    task = await TaskService.create_task(
        ctx.session,
        ctx.tenant_id,
        title=body.title,
        description=body.description,
        assignee_user_id=body.assignee_user_id,
        priority=body.priority,
        source="human",
    )
    return {"id": str(task.id), "status": task.status}


@router.post("/tasks/{task_id}/status")
async def update_task_status(ctx: TenantCtxDep, task_id: uuid.UUID, body: TaskUpdate):
    task = (
        await ctx.session.execute(
            select(Task).where(Task.tenant_id == ctx.tenant_id, Task.id == task_id)
        )
    ).scalar_one_or_none()
    if task is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("task not found")
    if body.status:
        task.status = body.status
    if body.priority is not None:
        task.priority = body.priority
    return {"id": str(task.id), "status": task.status}


@search_router.get("")
async def global_search(
    ctx: TenantCtxDep, q: str = Query(min_length=1, max_length=200), limit: int = 20
):
    """§45: unified search through the SearchPort (engine-agnostic)."""
    hits = await get_search().search(ctx.session, ctx.tenant_id, q, limit=limit)
    return [
        {
            "entity_type": h.entity_type,
            "entity_id": str(h.entity_id),
            "title": h.title,
            "snippet": h.snippet,
        }
        for h in hits
    ]


# ---------- SLA (§46) ----------
#
# Without these routes a tenant cannot configure an SLA at all, so the clock in
# operations/sla.py would never have a policy to apply.

class SLAPolicyUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    first_response_minutes: int = Field(gt=0, le=60 * 24 * 30)
    resolution_minutes: int = Field(gt=0, le=60 * 24 * 365)
    applies_to_channel: str | None = Field(default=None, max_length=31)
    is_default: bool = False


class BusinessCalendarUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    timezone: str = Field(default="Africa/Cairo", max_length=63)
    hours: dict = Field(default_factory=dict)
    holidays: list = Field(default_factory=list)
    is_default: bool = False


def _policy_out(p) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "first_response_minutes": p.first_response_minutes,
        "resolution_minutes": p.resolution_minutes,
        "applies_to_channel": p.applies_to_channel,
        "is_default": p.is_default,
        "status": p.status,
    }


def _calendar_out(c) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "timezone": c.timezone,
        "hours": c.hours or {},
        "holidays": c.holidays or [],
        "is_default": c.is_default,
    }


@sla_router.get("/policies")
async def list_sla_policies(ctx: TenantCtxDep):
    from app.modules.operations.models import SLAPolicy

    rows = (
        await ctx.session.execute(
            select(SLAPolicy).where(SLAPolicy.tenant_id == ctx.tenant_id)
        )
    ).scalars().all()
    return {"items": [_policy_out(p) for p in rows]}


@sla_router.put("/policies", status_code=201)
async def upsert_sla_policy(
    body: SLAPolicyUpsert,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Create or replace the tenant's SLA policy of the same name.

    `is_default` is exclusive: promoting a policy demotes the previous default,
    otherwise `resolve_policy` could pick either one and the effective SLA would
    depend on row order.
    """
    from app.modules.operations.models import SLAPolicy

    if body.is_default:
        for row in (
            await ctx.session.execute(
                select(SLAPolicy).where(
                    SLAPolicy.tenant_id == ctx.tenant_id, SLAPolicy.is_default.is_(True)
                )
            )
        ).scalars().all():
            row.is_default = False
        await ctx.session.flush()

    existing = (
        await ctx.session.execute(
            select(SLAPolicy).where(
                SLAPolicy.tenant_id == ctx.tenant_id, SLAPolicy.name == body.name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.first_response_minutes = body.first_response_minutes
        existing.resolution_minutes = body.resolution_minutes
        existing.applies_to_channel = body.applies_to_channel
        existing.is_default = body.is_default
        await ctx.session.flush()
        return _policy_out(existing)

    policy = SLAPolicy(
        tenant_id=ctx.tenant_id,
        name=body.name,
        first_response_minutes=body.first_response_minutes,
        resolution_minutes=body.resolution_minutes,
        applies_to_channel=body.applies_to_channel,
        is_default=body.is_default,
        status="active",
    )
    ctx.session.add(policy)
    await ctx.session.flush()
    return _policy_out(policy)


@sla_router.get("/calendars")
async def list_business_calendars(ctx: TenantCtxDep):
    from app.modules.operations.models import BusinessCalendar

    rows = (
        await ctx.session.execute(
            select(BusinessCalendar).where(BusinessCalendar.tenant_id == ctx.tenant_id)
        )
    ).scalars().all()
    return {"items": [_calendar_out(c) for c in rows]}


@sla_router.put("/calendars", status_code=201)
async def upsert_business_calendar(
    body: BusinessCalendarUpsert,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Configure opening hours. A malformed calendar is refused here rather
    than silently degrading the SLA clock to wall-clock time at run time."""
    from app.modules.operations.models import BusinessCalendar
    from app.modules.operations.sla import validate_calendar

    validate_calendar(body.hours, body.holidays)
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"unknown timezone: {body.timezone}") from exc

    if body.is_default:
        for row in (
            await ctx.session.execute(
                select(BusinessCalendar).where(
                    BusinessCalendar.tenant_id == ctx.tenant_id,
                    BusinessCalendar.is_default.is_(True),
                )
            )
        ).scalars().all():
            row.is_default = False
        await ctx.session.flush()

    existing = (
        await ctx.session.execute(
            select(BusinessCalendar).where(
                BusinessCalendar.tenant_id == ctx.tenant_id,
                BusinessCalendar.name == body.name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.timezone = body.timezone
        existing.hours = body.hours
        existing.holidays = body.holidays
        existing.is_default = body.is_default
        await ctx.session.flush()
        return _calendar_out(existing)

    calendar = BusinessCalendar(
        tenant_id=ctx.tenant_id,
        name=body.name,
        timezone=body.timezone,
        hours=body.hours,
        holidays=body.holidays,
        is_default=body.is_default,
    )
    ctx.session.add(calendar)
    await ctx.session.flush()
    return _calendar_out(calendar)


@sla_router.get("/risk")
async def sla_risk(ctx: TenantCtxDep, limit: int = Query(default=50, ge=1, le=200)):
    """Conversations whose first-response SLA is running, breached or at risk.

    This is the query behind the inbox "SLA risk" view: without it the clock
    ticks but nobody can see it.
    """
    from app.modules.operations.models import SLAEvent
    from app.modules.operations.sla import SlaService

    clock = await SlaService.resolve_clock(ctx.session, ctx.tenant_id)
    rows = (
        await ctx.session.execute(
            select(SLAEvent)
            .where(
                SLAEvent.tenant_id == ctx.tenant_id,
                SLAEvent.status.in_(("running", "breached")),
            )
            .order_by(SLAEvent.deadline_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    now = datetime.now(UTC)
    items = []
    for row in rows:
        remaining = None
        if row.deadline_at is not None:
            remaining = int((row.deadline_at - now).total_seconds() // 60)
        items.append(
            {
                "id": str(row.id),
                "conversation_id": str(row.conversation_id),
                "kind": row.kind,
                "status": row.status,
                "deadline_at": row.deadline_at.isoformat() if row.deadline_at else None,
                "minutes_remaining": remaining,
                # "at risk" = still running but under a quarter of the window
                # left, which is what an agent needs to triage by.
                "at_risk": bool(
                    row.status == "running"
                    and remaining is not None
                    and remaining <= 15
                ),
            }
        )
    return {"items": items, "timezone": clock.timezone_name}


# ---------- Jobs (§84) ----------
#
# The durable record and control surface for long operations: what was started,
# how far it got, what it produced, and whether it can be retried or cancelled.
# There is deliberately NO runner here — a worker executes a job and writes its
# status back. Running work inside the request would tie a long operation to
# the request lifetime, which is the failure this table exists to expose.

JOB_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
# Retry is meaningful only once a run has stopped without succeeding:
#   completed -> the work already happened; re-running could repeat a side
#                effect (a double import, a second charge), so refuse it.
#   queued / processing / retrying -> already in flight; a second retry would
#                race the run that is happening.
JOB_RETRYABLE_STATUSES = frozenset({"failed", "cancelled"})


def job_can_retry(status: str) -> bool:
    """Whether ``POST /jobs/{id}/retry`` is allowed for this status."""
    return status in JOB_RETRYABLE_STATUSES


def job_can_cancel(status: str) -> bool:
    """Whether ``POST /jobs/{id}/cancel`` is allowed — never on a terminal job."""
    return status not in JOB_TERMINAL_STATUSES


def _job_out(job: Job) -> dict:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "last_error": job.last_error,
        "result": job.result,
        "correlation_id": job.correlation_id,
        "actor_user_id": str(job.actor_user_id) if job.actor_user_id else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


async def _load_job(ctx: TenantContext, job_id: uuid.UUID) -> Job:
    """Fetch one job scoped to the caller's tenant; 404 rather than leak."""
    job = (
        await ctx.session.execute(
            select(Job).where(Job.tenant_id == ctx.tenant_id, Job.id == job_id)
        )
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("job not found")
    return job


@router.get("/jobs")
async def list_jobs(
    ctx: TenantCtxDep,
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    """Newest-first jobs for the tenant, optionally filtered by status/kind."""
    stmt = select(Job).where(Job.tenant_id == ctx.tenant_id)
    if status:
        stmt = stmt.where(Job.status == status)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    rows = (
        await ctx.session.execute(stmt.order_by(Job.created_at.desc()).limit(limit))
    ).scalars().all()
    return {"items": [_job_out(job) for job in rows]}


@router.get("/jobs/{job_id}")
async def get_job(ctx: TenantCtxDep, job_id: uuid.UUID):
    """One job's full record — status, progress, attempts, error and result."""
    return _job_out(await _load_job(ctx, job_id))


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Re-queue a job that stopped without succeeding."""
    job = await _load_job(ctx, job_id)
    if not job_can_retry(job.status):
        raise ConflictError(
            f"job is {job.status} and cannot be retried",
            details={"job_id": str(job.id), "status": job.status},
        )
    job.status = "queued"
    # A retry is a fresh run, so the attempt counter restarts. Leaving the old
    # count would make the job look already-exhausted to the runner that
    # compares attempts against max_attempts — it would fail instantly instead
    # of running, so the "retry" would silently do nothing.
    job.attempts = 0
    job.progress = 0
    job.last_error = None
    await ctx.session.flush()
    return _job_out(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
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


# ---------- Tenant fairness (§144) ----------
#
# Resource quotas: a single tenant cannot starve the platform.


@router.get("/fairness/usage")
async def fairness_usage(ctx: TenantCtxDep):
    """§144: current tenant's resource usage against fairness budgets."""
    from app.core.fairness import get_usage

    return await get_usage(ctx.tenant_id)


@router.get("/fairness/check")
async def fairness_check(
    ctx: TenantCtxDep,
    resource: str = Query(
        ...,
        description="ai_tokens | messages_outbound | storage_bytes | worker_seconds",
    ),
    units: int = Query(default=1, ge=1),
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
    return {
        "resource": result.resource.value,
        "limit": result.limit,
        "current_usage": result.current_usage,
        "remaining": result.remaining,
        "allowed": result.allowed,
    }


# ---------- SLO (§168) ----------
#
# Aggregate health objectives, distinct from per-conversation SLA.


@sla_router.get("/slos")
async def list_slo_definitions(ctx: TenantCtxDep):
    """§168: list all SLO definitions (deployment-wide, not per-tenant)."""
    from app.modules.operations.slo_service import get_slo_definitions

    return {"items": get_slo_definitions()}


@sla_router.get("/slos/measure")
async def measure_all_slos(ctx: TenantCtxDep):
    """§168: compute every SLO's compliance for the tenant."""
    from app.modules.operations.slo_service import measure_all_slos

    results = await measure_all_slos(ctx.session, ctx.tenant_id)
    return {
        "items": [
            {
                "name": r.name,
                "compliance_percent": r.compliance_percent,
                "total": r.total,
                "met": r.met,
                "target_percent": r.target_percent,
                "status": r.status,
                "window_since": r.window_since,
            }
            for r in results
        ]
    }


@sla_router.get("/slos/{slo_name}")
async def measure_one_slo(ctx: TenantCtxDep, slo_name: str):
    """§168: compute one SLO's compliance for the tenant."""
    from app.modules.operations.slo_service import measure_slo

    result = await measure_slo(ctx.session, ctx.tenant_id, slo_name)
    return {
        "name": result.name,
        "compliance_percent": result.compliance_percent,
        "total": result.total,
        "met": result.met,
        "target_percent": result.target_percent,
        "status": result.status,
        "window_since": result.window_since,
    }


# ---------- §154: Scheduled job cancel/reschedule ----------

class ScheduledJobReschedule(BaseModel):
    run_at: datetime


@router.post("/scheduled-jobs/{job_id}/cancel")
async def cancel_scheduled_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
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
    return {"id": str(job.id), "status": job.status}


@router.post("/scheduled-jobs/{job_id}/reschedule")
async def reschedule_scheduled_job(
    job_id: uuid.UUID,
    body: ScheduledJobReschedule,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
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
    return {
        "id": str(job.id),
        "status": job.status,
        "run_at": job.run_at.isoformat() if job.run_at else None,
    }
