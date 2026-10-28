"""OPERATIONS routes — tasks (§83) + search (§45) + SLA (§46).

Re-export aggregator for decomposed operations routers.
"""

from __future__ import annotations

import uuid

from app.modules.operations.routers._deps import (
    JOB_RETRYABLE_STATUSES,
    JOB_TERMINAL_STATUSES,
    SettingsCtx,
    TenantCtxDep,
    _calendar_out,
    _job_out,
    _load_job,
    _policy_out,
    _slo_out,
    job_can_cancel,
    job_can_retry,
    router,
    search_router,
    sla_router,
)
from app.modules.operations.routers.jobs import (
    cancel_job,
    cancel_scheduled_job,
    fairness_check,
    fairness_usage,
    get_job,
    list_jobs,
    reschedule_scheduled_job,
    retry_job,
)
from app.modules.operations.routers.search import global_search
from app.modules.operations.routers.sla import (
    list_business_calendars,
    list_sla_policies,
    list_slo_definitions,
    measure_all_slos,
    measure_one_slo,
    sla_risk,
    upsert_business_calendar,
    upsert_sla_policy,
)
from app.modules.operations.routers.tasks import (
    create_task,
    list_tasks,
)
from app.modules.operations.schemas import (
    ScheduledJobReschedule,
    TaskCreate,
    TaskMutationResult,
    TaskUpdate,
)
from app.modules.operations.task_service import TaskService


@router.post("/tasks/{task_id}/status", response_model=TaskMutationResult)
async def update_task_status(
    ctx: TenantCtxDep, task_id: uuid.UUID, body: TaskUpdate
) -> TaskMutationResult:
    """Move a task: status, assignee, priority — any combination."""
    task = await TaskService.update_status(
        ctx.session,
        ctx.tenant_id,
        task_id,
        status=body.status,
        assignee_user_id=body.assignee_user_id,
        priority=body.priority,
    )
    return TaskMutationResult(id=task.id, status=task.status)


# Preserve module qualification for introspection and test sweeps (§168 / test_operations_contracts.py)  # noqa: E501
for _endpoint in (
    list_tasks,
    create_task,
    update_task_status,
    global_search,
    list_jobs,
    get_job,
    retry_job,
    cancel_job,
    fairness_usage,
    fairness_check,
    cancel_scheduled_job,
    reschedule_scheduled_job,
    list_sla_policies,
    upsert_sla_policy,
    list_business_calendars,
    upsert_business_calendar,
    sla_risk,
    list_slo_definitions,
    measure_all_slos,
    measure_one_slo,
):
    _endpoint.__module__ = "app.modules.operations.router"

__all__ = [
    "JOB_RETRYABLE_STATUSES",
    "JOB_TERMINAL_STATUSES",
    "ScheduledJobReschedule",
    "SettingsCtx",
    "TaskCreate",
    "TaskUpdate",
    "_calendar_out",
    "_job_out",
    "_load_job",
    "_policy_out",
    "_slo_out",
    "cancel_job",
    "cancel_scheduled_job",
    "create_task",
    "fairness_check",
    "fairness_usage",
    "get_job",
    "global_search",
    "job_can_cancel",
    "job_can_retry",
    "list_business_calendars",
    "list_jobs",
    "list_sla_policies",
    "list_slo_definitions",
    "list_tasks",
    "measure_all_slos",
    "measure_one_slo",
    "reschedule_scheduled_job",
    "retry_job",
    "router",
    "search_router",
    "sla_risk",
    "sla_router",
    "update_task_status",
    "upsert_business_calendar",
    "upsert_sla_policy",
]
