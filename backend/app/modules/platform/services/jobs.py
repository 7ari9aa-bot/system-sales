"""JobService for platform jobs."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.errors import ValidationError
from app.modules.platform.models import Job


class JobService:
    """Creates the user-facing Job record (§84) — the control surface only.

    The Job row is the durable handle a user watches and controls; the
    ``job-runner`` worker pool executes it. Creation is deliberately a plain
    insert with no scheduling: ``jobs`` carries no ``run_at``/``next_attempt_at``
    (that is ``scheduled_jobs``), so a new job is simply ``queued`` and the
    runner picks it up on its next poll. Nothing runs inside the request.
    """

    @staticmethod
    async def create(
        session: Any,
        tenant_id: uuid.UUID,
        *,
        kind: str,
        actor_user_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
        max_attempts: int = 3,
    ) -> Job:
        """Queue a job of ``kind`` for this tenant.

        ``kind`` must match a handler registered with
        ``app.workers.job_runner.register_job_handler``; an unregistered kind is
        not rejected here (this layer must not import the worker registry) —
        the runner fails it with a clear error rather than leaving it queued.
        """
        if not kind:
            raise ValidationError("job kind is required")
        if max_attempts < 1:
            raise ValidationError("max_attempts must be at least 1")
        job = Job(
            tenant_id=tenant_id,
            kind=kind,
            status="queued",
            progress=0,
            attempts=0,
            max_attempts=max_attempts,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )
        session.add(job)
        await session.flush()
        return job
