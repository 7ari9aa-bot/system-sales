"""OPERATIONS routes — tasks (§83) + search (§45)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.search import get_search
from app.modules.identity.deps import TenantCtxDep
from app.modules.operations.models import Task

router = APIRouter(tags=["operations"])
search_router = APIRouter(prefix="/search", tags=["search"])


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
