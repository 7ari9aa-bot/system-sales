"""Task endpoints for operations."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Query
from sqlalchemy import select

from app.modules.operations.models import Task
from app.modules.operations.schemas import (
    TaskCreate,
    TaskMutationResult,
    TaskSummary,
)
from app.modules.operations.task_service import TaskService

from ._deps import TenantCtxDep, router


@router.get("/tasks", response_model=list[TaskSummary])
async def list_tasks(
    ctx: TenantCtxDep,
    status: str | None = None,
    mine: bool = False,
    customer_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """The tenant's tasks, newest first."""
    stmt = select(Task).where(Task.tenant_id == ctx.tenant_id)
    if status:
        stmt = stmt.where(Task.status == status)
    if mine:
        stmt = stmt.where(Task.assignee_user_id == ctx.user.id)
    if customer_id is not None:
        stmt = stmt.where(
            Task.related_entity_type == "customer",
            Task.related_entity_id == customer_id,
        )
    rows = (
        (
            await ctx.session.execute(
                stmt.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [
        TaskSummary(
            id=t.id,
            title=t.title,
            status=t.status,
            priority=t.priority,
            assignee_user_id=t.assignee_user_id,
            due_date=t.due_date,
            source=t.source,
        )
        for t in rows
    ]


@router.post("/tasks", status_code=201, response_model=TaskMutationResult)
async def create_task(ctx: TenantCtxDep, body: TaskCreate) -> TaskMutationResult:
    """Create a task through TaskService."""
    task = await TaskService.create_task(
        ctx.session,
        ctx.tenant_id,
        title=body.title,
        description=body.description,
        assignee_user_id=body.assignee_user_id,
        due_date=body.due_date,
        priority=body.priority,
        source="human",
    )
    return TaskMutationResult(id=task.id, status=task.status)
