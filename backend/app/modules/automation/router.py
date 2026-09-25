"""AUTOMATION routes — versioned workflows + executions (§136).

Our Workflow is the source of truth; n8n is only an execution adapter. A
workflow's definition is versioned (immutable snapshots) and each execution
pins the version it ran. Writes require ``settings:write`` (automation is
tenant configuration — no new permission codes are invented); reads use plain
``TenantCtxDep``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.audit import write_audit_row  # §66
from app.core.idempotency import IfMatch, apply_etag  # §17
from app.modules.automation.models import Workflow, WorkflowExecution, WorkflowVersion
from app.modules.automation.service import WorkflowService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

router = APIRouter(prefix="/workflows", tags=["automation"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

# §66: every mutation on this surface is a governance event, not a routine
# insert. Activating a workflow grants it the right to act on tenant data by
# itself (``execute_for_event`` fires on business events), and publishing a
# version decides what every future execution will run — so each of the four
# writes below leaves a row naming who did it, to what, from what to what.
# ``app.core.audit`` is a core capability, so this costs no cross-module edge.
AUDIT_CREATE = "workflow.created"
AUDIT_STATUS = "workflow.status_changed"
AUDIT_PUBLISH = "workflow.version_published"
AUDIT_RUN = "workflow.execution_run"
AUDIT_RESOURCE_WORKFLOW = "workflow"
AUDIT_RESOURCE_EXECUTION = "workflow_execution"

# Query params are declared `Annotated[type, Query(...)] = <value>`, never
# `name: type = Query(...)` — see the parameter-declaration rule in
# app/modules/analytics/router.py and the full-app gate in
# tests/test_route_parameter_declarations.py.


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    trigger_event: str = Field(min_length=1, max_length=127)
    definition: dict
    description: str | None = None
    execution_backend: str = Field(default="internal", pattern="^(internal|n8n)$")
    n8n_workflow_ref: str | None = Field(default=None, max_length=255)


class WorkflowStatusUpdate(BaseModel):
    status: str = Field(pattern="^(draft|active|paused|archived)$")


class WorkflowVersionCreate(BaseModel):
    definition: dict


def _workflow_dict(workflow: Workflow) -> dict:
    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "description": workflow.description,
        "trigger_event": workflow.trigger_event,
        "status": workflow.status,
        "execution_backend": workflow.execution_backend,
        "n8n_workflow_ref": workflow.n8n_workflow_ref,
        "current_version": workflow.current_version,
        "version": workflow.version,  # §17 CAS token (mirrors the ETag)
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
    }


def _execution_dict(execution: WorkflowExecution) -> dict:
    return {
        "id": str(execution.id),
        "workflow_id": str(execution.workflow_id),
        "workflow_version": execution.workflow_version,
        "status": execution.status,
        "trigger_event_type": execution.trigger_event_type,
        "trigger_event_id": (
            str(execution.trigger_event_id) if execution.trigger_event_id else None
        ),
        "correlation_id": execution.correlation_id,
        "result": execution.result,
        "error": execution.error,
        "started_at": execution.started_at.isoformat(),
        "finished_at": (
            execution.finished_at.isoformat() if execution.finished_at else None
        ),
    }


@router.get("")
async def list_workflows(
    ctx: TenantCtxDep,
    status: Annotated[str | None, Query(pattern="^(draft|active|paused|archived)$")] = None,
):
    """List this tenant's workflows (optionally filtered by status)."""
    stmt = select(Workflow).where(Workflow.tenant_id == ctx.tenant_id)
    if status is not None:
        stmt = stmt.where(Workflow.status == status)
    rows = (
        await ctx.session.execute(stmt.order_by(Workflow.created_at.desc()).limit(200))
    ).scalars().all()
    return [_workflow_dict(workflow) for workflow in rows]


@router.post("", status_code=201)
async def create_workflow(ctx: WriteCtx, body: WorkflowCreate):
    """Create a workflow (draft, version 1) with its first definition snapshot."""
    workflow = await WorkflowService.create(
        ctx.session,
        ctx.tenant_id,
        name=body.name,
        trigger_event=body.trigger_event,
        definition=body.definition,
        execution_backend=body.execution_backend,
        n8n_workflow_ref=body.n8n_workflow_ref,
    )
    if body.description is not None:
        workflow.description = body.description
        await ctx.session.flush()
    await write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        AUDIT_CREATE,
        AUDIT_RESOURCE_WORKFLOW,
        str(workflow.id),
        after={
            "name": workflow.name,
            "trigger_event": workflow.trigger_event,
            "status": workflow.status,
            "execution_backend": workflow.execution_backend,
            "current_version": workflow.current_version,
        },
    )
    return _workflow_dict(workflow)


@router.post("/executions/{execution_id}/run")
async def run_workflow_execution(ctx: WriteCtx, execution_id: uuid.UUID):
    """Run one existing execution against its pinned workflow version.

    Execution runs through the workflow's configured backend (the internal
    engine or the n8n adapter). Failures are recorded on the execution row and
    in ``workflow_failures`` — they are not surfaced as a 5xx.
    """
    execution = await WorkflowService.run_execution(ctx.session, ctx.tenant_id, execution_id)
    await write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        AUDIT_RUN,
        AUDIT_RESOURCE_EXECUTION,
        str(execution.id),
        after={
            "workflow_id": str(execution.workflow_id),
            "workflow_version": execution.workflow_version,
            "status": execution.status,
            "error": execution.error,
        },
    )
    return _execution_dict(execution)


@router.get("/{workflow_id}")
async def get_workflow(
    ctx: TenantCtxDep, workflow_id: uuid.UUID, response: Response
):
    """Fetch one workflow by id (§17: version in the body + strong ETag)."""
    workflow = await WorkflowService.get(ctx.session, ctx.tenant_id, workflow_id)
    apply_etag(response, workflow.version)
    return _workflow_dict(workflow)


@router.patch("/{workflow_id}/status")
async def update_workflow_status(
    ctx: WriteCtx,
    workflow_id: uuid.UUID,
    body: WorkflowStatusUpdate,
    response: Response,
    if_match: IfMatch = None,  # §17 optimistic concurrency; absent = unconditional
):
    """Change a workflow's lifecycle status (draft | active | paused | archived)."""
    # Read the current rung FIRST: §66 wants the transition, not just the
    # destination, and ``set_status`` overwrites the attribute in place. The
    # CAS inside set_status is what makes the read safe — a racing writer
    # loses on ``WHERE version``, it does not slip past this lookup.
    previous = await WorkflowService.get(ctx.session, ctx.tenant_id, workflow_id)
    before_status = previous.status
    workflow = await WorkflowService.set_status(
        ctx.session,
        ctx.tenant_id,
        workflow_id,
        body.status,
        expected_version=if_match,
    )
    await ctx.session.flush()
    await write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        AUDIT_STATUS,
        AUDIT_RESOURCE_WORKFLOW,
        str(workflow.id),
        before={"status": before_status},
        after={
            "status": workflow.status,
            "current_version": workflow.current_version,
            "version": workflow.version,
        },
    )
    apply_etag(response, workflow.version)
    return _workflow_dict(workflow)


@router.post("/{workflow_id}/versions", status_code=201)
async def publish_workflow_version(
    ctx: WriteCtx,
    workflow_id: uuid.UUID,
    body: WorkflowVersionCreate,
    response: Response,
    if_match: IfMatch = None,  # §17: two publishers of one version cannot both win
):
    """Publish a new immutable definition snapshot (bumps current_version)."""
    version = await WorkflowService.publish_new_version(
        ctx.session,
        ctx.tenant_id,
        workflow_id,
        definition=body.definition,
        expected_version=if_match,
    )
    workflow = await WorkflowService.get(ctx.session, ctx.tenant_id, workflow_id)
    apply_etag(response, workflow.version)
    await write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        AUDIT_PUBLISH,
        AUDIT_RESOURCE_WORKFLOW,
        str(workflow_id),
        after={
            "version": version.version,
            "current_version": workflow.current_version,
            "step_count": len(version.definition.get("steps", [])),
        },
    )
    return {"workflow_id": str(workflow_id), "version": version.version}


@router.get("/{workflow_id}/versions")
async def list_workflow_versions(ctx: TenantCtxDep, workflow_id: uuid.UUID):
    """List the definition snapshots of one workflow (newest first)."""
    await WorkflowService.get(ctx.session, ctx.tenant_id, workflow_id)
    rows = (
        await ctx.session.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.desc())
        )
    ).scalars().all()
    return [
        {
            "version": version.version,
            "definition": version.definition,
            "created_at": version.created_at.isoformat(),
        }
        for version in rows
    ]


@router.get("/{workflow_id}/executions")
async def list_workflow_executions(
    ctx: TenantCtxDep,
    workflow_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """List executions of one workflow (newest first)."""
    await WorkflowService.get(ctx.session, ctx.tenant_id, workflow_id)
    rows = (
        await ctx.session.execute(
            select(WorkflowExecution)
            .where(
                WorkflowExecution.tenant_id == ctx.tenant_id,
                WorkflowExecution.workflow_id == workflow_id,
            )
            .order_by(WorkflowExecution.started_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [_execution_dict(execution) for execution in rows]
