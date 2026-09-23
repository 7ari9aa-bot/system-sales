"""AUTOMATION service (spec §136) — versioned workflows + execution.

Creation is versioned (immutability). Execution runs through the configured
backend: 'internal' executes the definition AST inline; 'n8n' POSTs the
context to the n8n adapter webhook (SecretReference only — no raw creds).
Execution is asynchronous by contract: the caller gets an execution id and
the result lands on the WorkflowExecution row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    DomainError,
    ExternalProviderError,
    NotFoundError,
    ValidationError,
)
from app.core.idempotency import apply_versioned_update  # §17
from app.modules.automation.models import (
    Workflow,
    WorkflowExecution,
    WorkflowFailure,
    WorkflowVersion,
)

_MAX_STEPS = 25  # §134-style execution bound


class WorkflowService:
    @staticmethod
    async def create(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        name: str,
        trigger_event: str,
        definition: dict,
        execution_backend: str = "internal",
        n8n_workflow_ref: str | None = None,
    ) -> Workflow:
        if execution_backend not in ("internal", "n8n"):
            raise ValidationError(f"unknown backend: {execution_backend}")
        if not isinstance(definition, dict) or "steps" not in definition:
            raise ValidationError("definition must contain 'steps'")
        workflow = Workflow(
            tenant_id=tenant_id,
            name=name,
            trigger_event=trigger_event,
            execution_backend=execution_backend,
            n8n_workflow_ref=n8n_workflow_ref,
            status="draft",
            current_version=1,
        )
        session.add(workflow)
        await session.flush()
        session.add(
            WorkflowVersion(
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
        workflow = await WorkflowService.get(session, tenant_id, workflow_id)
        # §17: the CAS on the workflow row IS the race guard — two publishers
        # holding the same version cannot both bump current_version; the loser
        # gets ConflictError before any snapshot is inserted.
        await apply_versioned_update(
            session,
            workflow,
            expected_version,
            {"current_version": workflow.current_version + 1},
        )
        version = WorkflowVersion(
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
        if status not in ("draft", "active", "paused", "archived"):
            raise ValidationError(f"invalid status: {status}")
        workflow = await WorkflowService.get(session, tenant_id, workflow_id)
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
                    WorkflowVersion.workflow_id == execution.workflow_id,
                    WorkflowVersion.version == execution.workflow_version,
                )
            )
        ).scalar_one_or_none()
        workflow = await WorkflowService.get(session, tenant_id, execution.workflow_id)

        try:
            if workflow.execution_backend == "n8n":
                result = await WorkflowService._run_n8n(
                    session, tenant_id, workflow, execution, version
                )
            else:
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
            # §176 gate 12: tests/gate/test_gate_n8n_outage.py
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

    @staticmethod
    async def _run_n8n(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        workflow: Workflow,
        execution: WorkflowExecution,
        version: WorkflowVersion,
    ) -> dict:
        """n8n execution adapter — POST context to the n8n webhook."""
        from app.core.config import get_settings
        from app.modules.automation.tokens import get_or_issue_outbound_token

        settings = get_settings()
        base = getattr(settings, "n8n_base_url", "")
        if not base:
            raise ExternalProviderError("n8n base url not configured")
        # §136: per-tenant credential only — the global SERVICE_TOKEN_INTERNAL
        # Bearer let any tenant act as any other tenant and must never be sent
        # again. Issuance failure is a hard DomainError, never a fallback.
        try:
            token = await get_or_issue_outbound_token(session, tenant_id)
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001 — re-raised as a domain error
            raise ExternalProviderError(
                f"n8n service token issuance failed: {str(exc)[:200]}"
            ) from exc
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{base}/webhook/{workflow.n8n_workflow_ref or 'default'}",
                json={"execution_id": str(execution.id), "context": execution.context},
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code >= 400:
            raise ExternalProviderError(f"n8n execution failed: {response.status_code}")
        return response.json() if response.content else {}
