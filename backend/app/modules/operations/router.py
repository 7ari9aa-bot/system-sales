"""OPERATIONS routes — tasks (§83) + search (§45) + SLA (§46)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.errors import ValidationError
from app.core.search import get_search
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.operations.models import Task

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
async def list_tasks(ctx: TenantCtxDep, status: str | None = None, mine: bool = False):
    from sqlalchemy import select

    stmt = select(Task).where(Task.tenant_id == ctx.tenant_id)
    if status:
        stmt = stmt.where(Task.status == status)
    if mine:
        stmt = stmt.where(Task.assignee_user_id == ctx.user.id)
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
    task = Task(
        tenant_id=ctx.tenant_id,
        title=body.title,
        description=body.description,
        assignee_user_id=body.assignee_user_id,
        priority=body.priority,
        source="human",
    )
    ctx.session.add(task)
    await ctx.session.flush()
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
