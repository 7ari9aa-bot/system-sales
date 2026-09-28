"""AUTOMATION service — versioned workflows executed by the internal engine.

Creation is versioned (immutability). Execution is asynchronous by contract:
the caller gets an execution id and the result lands on the WorkflowExecution
row. Domain side effects are staged in Postgres and delivered by workers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.idempotency import apply_versioned_update, parse_if_match  # §17
from app.modules.automation.models import (
    Workflow,
    WorkflowExecution,
    WorkflowFailure,
    WorkflowVersion,
)

_MAX_STEPS = 25  # §134-style execution bound

WORKFLOW_STATUSES = ("draft", "active", "paused", "archived")

#: §176/§136 lifecycle ladder. CURRENT -> allowed targets, mirroring the repo's
#: own convention (``conversations/templates.py:44``): ``archived`` is TERMINAL.
#: A withdrawn workflow must not be resumable by a status PATCH, because
#: ``active`` is exactly the flag that lets ``execute_for_event`` fire it — and
#: therefore let it mutate tenant data — on every matching tenant event.
ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"active", "archived"}),
    "active": frozenset({"paused", "archived"}),
    "paused": frozenset({"active", "archived"}),
    "archived": frozenset(),
}


def _validate_definition(definition: object) -> None:
    """§136: OUR Workflow Version is the canonical definition the engine runs.

    Checked at WRITE time, on both doors that create a snapshot, for the same
    reason ``create`` already checked it: a version nobody can execute is not a
    draft, it is an outage waiting for the next event. Before this, ``create``
    rejected a definition without ``steps`` while ``publish_new_version``
    rejected nothing — so the very next write to a live workflow could replace
    a runnable definition with one that executes zero steps and still reports
    ``completed``. The engine's own guard in ``_run_internal`` stays: snapshots
    published before this rule existed are still refused at run time.
    """
    if not isinstance(definition, dict) or "steps" not in definition:
        raise ValidationError("definition must contain 'steps'")
    steps = definition["steps"]
    if not isinstance(steps, list):
        raise ValidationError("definition['steps'] must be a list")
    if len(steps) > _MAX_STEPS:
        raise ValidationError(f"a workflow may not exceed {_MAX_STEPS} steps")


class WorkflowService:
    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        name: str,
        trigger_event: str,
        definition: dict,
    ) -> Workflow:
        _validate_definition(definition)
        workflow = Workflow(
            tenant_id=tenant_id,
            name=name,
            trigger_event=trigger_event,
            status="draft",
            current_version=1,
        )
        session.add(workflow)
        await session.flush()
        session.add(
            WorkflowVersion(
                tenant_id=tenant_id,
                workflow_id=workflow.id,
                version=1,
                definition=definition,
            )
        )
        await session.flush()
        return workflow

    @staticmethod
    async def publish_new_version(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        workflow_id: uuid.UUID,
        *,
        definition: dict,
        expected_version: str | None = None,  # §17 If-Match
    ) -> WorkflowVersion:
        # Refused BEFORE the row is touched: a snapshot nobody can execute must
        # not bump current_version even when the definition is rejected later.
        _validate_definition(definition)
        workflow = await WorkflowService.get(session, tenant_id, workflow_id)
        # §17: the CAS on the workflow row IS the race guard — two publishers
        # holding the same version cannot both bump current_version; the loser
        # gets ConflictError before any snapshot is inserted.
        #
        # An absent or wildcard If-Match is not a licence to skip that guard.
        # Without a predicate BOTH publishers compute the same N+1, and the loser
        # collides on uq_workflow_versions_workflow_version at INSERT — a 500
        # where the contract owes a 409. The version this call just read is the
        # token to CAS on, which keeps the door usable without a header and makes
        # a lost race fail the way a lost race is supposed to.
        cas_token = (
            expected_version
            if parse_if_match(expected_version) is not None
            else str(workflow.version)
        )
        await apply_versioned_update(
            session,
            workflow,
            cas_token,
            {"current_version": workflow.current_version + 1},
        )
        version = WorkflowVersion(
            tenant_id=workflow.tenant_id,
            workflow_id=workflow.id,
            version=workflow.current_version,
            definition=definition,
        )
        session.add(version)
        await session.flush()
        return version

    @staticmethod
    async def get(session: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
        workflow = (
            await session.execute(
                select(Workflow).where(Workflow.tenant_id == tenant_id, Workflow.id == workflow_id)
            )
        ).scalar_one_or_none()
        if workflow is None:
            raise NotFoundError("workflow not found")
        return workflow

    @staticmethod
    async def set_status(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        workflow_id: uuid.UUID,
        status: str,
        *,
        expected_version: str | None = None,  # §17 If-Match
    ) -> Workflow:
        if status not in WORKFLOW_STATUSES:
            raise ValidationError(f"invalid status: {status}")
        workflow = await WorkflowService.get(session, tenant_id, workflow_id)
        allowed = ALLOWED_STATUS_TRANSITIONS.get(workflow.status, frozenset())
        if status not in allowed:
            hint = f" (allowed: {', '.join(sorted(allowed))})" if allowed else (
                " - archived is terminal"
            )
            raise ConflictError(
                f"cannot move a {workflow.status} workflow to {status}{hint}"
            )
        # ONE statement, always version-bumped (even without If-Match) so an
        # ETag never goes stale silently on a concurrent unconditional write.
        await apply_versioned_update(
            session, workflow, expected_version, {"status": status}
        )
        return workflow

    @staticmethod
    async def execute_for_event(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        event_type: str,
        event_id: uuid.UUID,
        context: dict,
    ) -> list[WorkflowExecution]:
        """Event-driven entry: run every ACTIVE workflow listening to this
        trigger. Never raises to the caller — failures are recorded."""
        workflows = (
            (
                await session.execute(
                    select(Workflow).where(
                        Workflow.tenant_id == tenant_id,
                        Workflow.trigger_event == event_type,
                        Workflow.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        executions: list[WorkflowExecution] = []
        for workflow in workflows:
            execution = WorkflowExecution(
                tenant_id=tenant_id,
                workflow_id=workflow.id,
                workflow_version=workflow.current_version,
                trigger_event_type=event_type,
                trigger_event_id=event_id,
                context=context or {},
                status="running",
            )
            session.add(execution)
            executions.append(execution)
        await session.flush()
        return executions

    @staticmethod
    async def run_execution(
        session: AsyncSession, tenant_id: uuid.UUID, execution_id: uuid.UUID
    ) -> WorkflowExecution:
        """Execute one running execution against its pinned version."""
        execution = (
            await session.execute(
                select(WorkflowExecution).where(
                    WorkflowExecution.tenant_id == tenant_id,
                    WorkflowExecution.id == execution_id,
                )
            )
        ).scalar_one_or_none()
        if execution is None:
            raise NotFoundError("execution not found")
        if execution.status != "running":
            return execution
        version = (
            await session.execute(
                select(WorkflowVersion).where(
                    WorkflowVersion.tenant_id == tenant_id,
                    WorkflowVersion.workflow_id == execution.workflow_id,
                    WorkflowVersion.version == execution.workflow_version,
                )
            )
        ).scalar_one_or_none()
        workflow = await WorkflowService.get(session, tenant_id, execution.workflow_id)
        # §136 lifecycle: the TRIGGER path only stages an ACTIVE workflow
        # (see ``execute_for_event``), so the manual run door must honour the
        # same ladder or pausing/archiving a workflow achieves nothing — an
        # operator could still fire the queued executions of a definition the
        # merchant withdrew, queueing notifications and webhooks on its behalf.
        if workflow.status != "active":
            raise ConflictError(
                f"workflow {workflow.id} is {workflow.status}; only an active "
                "workflow executes"
            )

        try:
            result = await WorkflowService._run_internal(session, tenant_id, execution, version)
            execution.result = result
            execution.status = "completed"
        except Exception as exc:  # noqa: BLE001 — failures are recorded
            execution.status = "failed"
            execution.error = str(exc)[:500]
            # `tenant_id` is NOT NULL (and this table is FORCE RLS), so omitting
            # it made the FAILURE path itself raise IntegrityError on flush —
            # every workflow outage became the 5xx the router docstring promises
            # it is not, and the rollback took the execution row with it. Nothing
            # else in the suite ever ran this branch.
            # Workflow failures are durable and do not bubble into the caller.
            session.add(
                WorkflowFailure(
                    tenant_id=tenant_id,
                    execution_id=execution.id,
                    error=str(exc)[:500],
                )
            )
        execution.finished_at = datetime.now(UTC)
        await session.flush()
        return execution

    @staticmethod
    async def _run_internal(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        execution: WorkflowExecution,
        version: WorkflowVersion,
    ) -> dict:
        """Internal engine: sequential steps with bound limits (§134)."""
        steps = version.definition.get("steps", [])
        if not isinstance(steps, list) or len(steps) > _MAX_STEPS:
            raise ValidationError("invalid or oversized steps")
        context = dict(execution.context or {})
        outputs: list[dict] = []
        for step in steps[:_MAX_STEPS]:
            action = step.get("action")
            if action == "notify":
                from app.modules.platform.service import NotificationService

                await NotificationService.queue(
                    session,
                    tenant_id,
                    channel="inapp",
                    body=str(step.get("message", "workflow step")),
                    subject=step.get("subject"),
                )
                outputs.append({"action": "notify", "ok": True})
            elif action == "webhook":
                from app.modules.platform.service import WebhookService

                deliveries = await WebhookService.enqueue(
                    session,
                    tenant_id,
                    event_name=step.get("event", "workflow.step"),
                    payload={"context": context, "step": step.get("name")},
                )
                outputs.append({"action": "webhook", "deliveries": len(deliveries)})
            elif action == "set_context":
                context.update(step.get("values") or {})
                outputs.append({"action": "set_context", "ok": True})
            else:
                raise ValidationError(f"unknown step action: {action}")
        return {"outputs": outputs, "context": context}
