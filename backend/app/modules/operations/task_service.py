"""§13-14: TaskService — the single entry point for creating tasks.

The AI tool `_add_task` and the operations router both call this service
instead of directly constructing Task models. This ensures:
- Consistent validation (title length, priority range)
- Consistent defaults (source, status)
- The AI tool cannot bypass the service layer (§13-14)
- Future hooks (audit, events) are in one place
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.operations.models import Task


class TaskService:
    """§13-14: service layer for task operations."""

    @staticmethod
    async def create_task(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        title: str,
        description: str | None = None,
        assignee_user_id: uuid.UUID | None = None,
        due_date: datetime | None = None,
        priority: int = 2,
        source: str = "human",
        created_by: str | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
    ) -> Task:
        """Create a task with consistent validation and defaults."""
        if not title or len(title.strip()) < 1:
            raise ValidationError("task title is required")
        if len(title) > 255:
            raise ValidationError("task title must be 255 chars or less")
        if priority < 1 or priority > 3:
            raise ValidationError("priority must be 1 (high), 2 (normal), or 3 (low)")

        task = Task(
            tenant_id=tenant_id,
            title=title.strip(),
            description=description,
            assignee_user_id=assignee_user_id,
            due_date=due_date,
            priority=priority,
            status="todo",
            source=source,
            created_by=created_by or source,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        session.add(task)
        await session.flush()
        return task

    @staticmethod
    async def update_status(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
        *,
        status: str,
        by_user_id: uuid.UUID | None = None,
    ) -> Task:
        """Transition a task's status with validation."""
        task = (
            await session.execute(
                select(Task).where(
                    Task.tenant_id == tenant_id, Task.id == task_id
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise NotFoundError(f"task {task_id} not found")

        allowed = {"todo", "in_progress", "done", "cancelled"}
        if status not in allowed:
            raise ValidationError(f"invalid task status: {status}")

        task.status = status
        await session.flush()
        return task

    @staticmethod
    async def get(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        task_id: uuid.UUID,
    ) -> Task:
        """Get a task by ID (tenant-scoped)."""
        task = (
            await session.execute(
                select(Task).where(
                    Task.tenant_id == tenant_id, Task.id == task_id
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise NotFoundError(f"task {task_id} not found")
        return task
