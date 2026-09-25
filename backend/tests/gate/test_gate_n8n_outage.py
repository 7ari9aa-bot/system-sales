"""§176 gate scenario 12 — n8n is DOWN: the outage must be recorded, not escalated.

The spec's rule (§177.8) is that n8n is an optional adapter, never core truth.
The gate that supposedly proved it read the SOURCE of
``ConversationService.add_message`` for the string "n8n" — a grep. It says
nothing about the one place the platform actually depends on n8n: the workflow
execution adapter, which is documented (``app/modules/automation/router.py:120``)
as

    "Failures are recorded on the execution row and in ``workflow_failures`` —
     they are not surfaced as a 5xx."

Nothing had ever executed that path: ``run_execution`` has no other test. So
these drive it for real — a POST to a port that REFUSES the connection, through
the production httpx client — and check what the durable record says.

DB-backed (the failure record is the thing under test); skips via ``db_url``
without an application database.
"""

from __future__ import annotations

import socket
import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import bind_tenant
from app.modules.automation.models import (
    Workflow,
    WorkflowExecution,
    WorkflowFailure,
    WorkflowVersion,
)
from app.modules.automation.service import WorkflowService

pytestmark = [pytest.mark.gate]


def _closed_port() -> int:
    """A port nothing listens on: a genuine connection refusal, not a stub."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def _stage_unreachable_n8n(db, tenant_id, monkeypatch) -> WorkflowExecution:
    """An active n8n-backed workflow whose adapter points at a dead endpoint.

    Only the SETTINGS change (base url → refused port). The client, the
    request, the exception handling and the persistence are all production
    code — mocking the HTTP call would mock the very thing under test.
    """
    monkeypatch.setattr(
        get_settings(), "n8n_base_url", f"http://127.0.0.1:{_closed_port()}", raising=False
    )
    # CI connects as `sales_app` with RLS enforced, and the `db` fixture does
    # not bind the tenant GUC, so every tenant_id table refuses the INSERTs
    # below until the row-owning tenant is bound (the reason
    # test_inbox_read_model's inbox_seed binds before it writes — visible only
    # in CI, where these tests actually run).
    await bind_tenant(db, tenant_id)
    workflow = Workflow(
        tenant_id=tenant_id,
        name="gate n8n outage",
        trigger_event="order.created",
        status="active",
        execution_backend="n8n",
        n8n_workflow_ref="gate-outage-ref",
    )
    db.add(workflow)
    await db.flush()
    db.add(
        WorkflowVersion(
            tenant_id=tenant_id,  # NOT NULL, no default — the writer must own it
            workflow_id=workflow.id,
            version=workflow.current_version,
            definition={"steps": []},
        )
    )
    await db.flush()
    executions = await WorkflowService.execute_for_event(
        db,
        tenant_id,
        event_type="order.created",
        event_id=uuid.uuid4(),
        context={"gate": "n8n-outage"},
    )
    assert len(executions) == 1, "the active n8n workflow did not take the trigger"
    return executions[0]


async def _failure_rows(db, execution_id: uuid.UUID) -> list[WorkflowFailure]:
    return list(
        (
            await db.execute(
                select(WorkflowFailure).where(WorkflowFailure.execution_id == execution_id)
            )
        )
        .scalars()
        .all()
    )


async def test_gate_an_unreachable_n8n_is_recorded_and_never_reaches_the_caller(
    db, tenant_ctx, monkeypatch
) -> None:
    """The outage is a DATA point, not a 5xx — and it leaves a tenant behind."""
    tenant_id = tenant_ctx.tenant_id
    execution = await _stage_unreachable_n8n(db, tenant_id, monkeypatch)

    # `run_execution` must RETURN. Everything below is unreachable if the
    # failure handler itself raises, which is the difference between an
    # outage being survived and an outage being lost.
    done = await WorkflowService.run_execution(db, tenant_id, execution.id)

    assert done.status == "failed", (
        f"an unreachable n8n produced status {done.status!r}"
    )
    assert done.error, "the failure was recorded without a reason"
    assert done.finished_at is not None
    assert not done.result, "a failed run must not claim an output"

    failures = await _failure_rows(db, execution.id)
    assert len(failures) == 1, (
        f"{len(failures)} workflow_failures rows for one outage — the router "
        "documents exactly one, and its absence is a silent 5xx"
    )
    assert failures[0].tenant_id == tenant_id
    assert failures[0].error == done.error

    # And the REQUEST survives: the transaction that logged the failure is
    # still usable, so the record actually commits instead of rolling back
    # with the outage.
    total = (
        await db.execute(
            select(func.count()).select_from(WorkflowExecution).where(
                WorkflowExecution.id == execution.id
            )
        )
    ).scalar_one()
    assert total == 1


async def test_gate_retrying_a_failed_run_does_not_record_it_twice(
    db, tenant_ctx, monkeypatch
) -> None:
    """§177.6: an operator re-pressing Run must not multiply history.

    A failed execution is terminal — ``run_execution`` returns it as-is — so
    a client retry over a flaky link cannot emit a second failure record or
    a second n8n call.
    """
    tenant_id = tenant_ctx.tenant_id
    execution = await _stage_unreachable_n8n(db, tenant_id, monkeypatch)

    first = await WorkflowService.run_execution(db, tenant_id, execution.id)
    second = await WorkflowService.run_execution(db, tenant_id, execution.id)

    assert first.status == second.status == "failed"
    assert await _failure_rows(db, execution.id) and len(
        await _failure_rows(db, execution.id)
    ) == 1
