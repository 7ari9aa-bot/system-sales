"""AUTOMATION service rules (spec §136), DB-free.

What this lane covers
--------------------
``app/modules/automation/`` had NO test of its own: the only assertions ever
made against it were two ``WorkflowService.create`` validation calls buried in
``tests/test_module_routers.py`` and an If-Match router sweep in
``tests/test_if_match_wave2.py``. Nothing drove the lifecycle rules, the
version-publishing invariant, the internal engine, or the trigger query — which
is why §176 gate 12 had to be written to discover that the FAILURE path itself
raised (``docs/GAP_REGISTER.md`` wave review #3).

Requirements asserted here, in the words of the spec and the module's own
contract:

* §136 — the tenant Workflow + its Versions are canonical truth; n8n is only an
  adapter. So the definition a version snapshot carries must be one the ENGINE
  can execute, at publish time, not discovered at run time.
* §66 — every critical mutation is auditable (§136's status ladder grants a
  workflow the power to mutate tenant data on events, so it qualifies).
* §17 — a lifecycle write carries the row's CAS token.
* Repo lifecycle convention (`conversations/templates.py:44-53`,
  ``tests/test_template_lifecycle.py``): ``archived`` is TERMINAL.
* §151/RLS: every read of a ``tenant_id``-bearing table names its tenant.

Venue: no database is reachable here, so each case answers the service's
questions with a fake session that records the exact SQL, or asserts on a
compiled statement. The concurrency claims (two publishers, one winner) need a
real PostgreSQL and live in ``tests/gate/``.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.automation.models import (
    Workflow,
    WorkflowExecution,
    WorkflowFailure,
    WorkflowVersion,
)
from app.modules.automation.service import _MAX_STEPS, WorkflowService

TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER = uuid.UUID("99999999-9999-9999-9999-999999999999")


def _now() -> datetime:
    return datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


# ------------------------------------------------------------- fake session --


class _Result:
    def __init__(self, rows=(), scalar=...) -> None:
        self._rows = list(rows)
        self._scalar = scalar

    def scalars(self) -> _Result:
        return self

    def all(self) -> list:
        return list(self._rows)

    def scalar_one_or_none(self):
        if self._scalar is not ...:
            return self._scalar
        return self._rows[0] if self._rows else None


class FakeSession:
    """Answers exactly the statements the automation service runs.

    Anything unrecognised is a failure: a route or service that starts issuing
    its own SQL outside the tables it owns shows up here immediately.
    """

    def __init__(
        self,
        *,
        workflows=(),
        versions=(),
        executions=(),
        update_returns=2,
    ) -> None:
        self.workflows = list(workflows)
        self.versions = list(versions)
        self.executions = list(executions)
        self.update_returns = update_returns
        self.added: list = []
        self.sql: list[str] = []
        self.bound: list[dict] = []
        self.flushes = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def execute(self, statement, params=None) -> _Result:
        try:
            compiled = statement.compile(dialect=postgresql.dialect())
            sql, bound = str(compiled), dict(compiled.params)
        except Exception:  # text() clauses and plain strings
            sql, bound = str(statement), {}
        if isinstance(params, dict):
            bound.update(params)
        self.sql.append(sql)
        self.bound.append(bound)

        low = " ".join(sql.split()).lower()
        if low.startswith("update"):
            return _Result(scalar=self.update_returns)
        if low.startswith("insert"):
            return _Result()
        if "from workflow_versions" in low:
            return _Result(self.versions)
        if "from workflow_executions" in low:
            return _Result(self.executions)
        if "from workflows" in low:
            return _Result(self.workflows)
        raise AssertionError(f"automation asked a question nobody owns: {sql[:160]}")


def _workflow(
    *,
    tenant_id: uuid.UUID = TENANT,
    status: str = "active",
    backend: str = "internal",
    current_version: int = 1,
    version: int = 1,
) -> Workflow:
    return Workflow(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="wf",
        trigger_event="order.created",
        status=status,
        execution_backend=backend,
        current_version=current_version,
        version=version,
        created_at=_now(),
        updated_at=_now(),
    )


def _version(workflow: Workflow, definition: dict, number: int = 1) -> WorkflowVersion:
    return WorkflowVersion(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        version=number,
        definition=definition,
        created_at=_now(),
        updated_at=_now(),
    )


def _execution(
    workflow: Workflow,
    *,
    tenant_id: uuid.UUID = TENANT,
    status: str = "running",
    context: dict | None = None,
) -> WorkflowExecution:
    return WorkflowExecution(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        workflow_id=workflow.id,
        workflow_version=1,
        status=status,
        context=context if context is not None else {},
        started_at=_now(),
        finished_at=None if status == "running" else _now(),
    )


# ------------------------------------------------- the trigger: what stages --


async def test_the_trigger_query_selects_only_active_workflows_of_one_tenant() -> None:
    """The module's own rule, and the anchor for every lifecycle assertion below.

    ``execute_for_event`` selects ``status == 'active'`` only (``service.py:149``):
    a workflow the merchant has not published, has paused, or has archived must
    not mutate tenant data because an unrelated order was created.
    """
    session = FakeSession(workflows=[])
    await WorkflowService.execute_for_event(
        session,
        TENANT,
        event_type="order.created",
        event_id=uuid.uuid4(),
        context={"amount": 10},
    )
    select_sql = next(s for s in session.sql if s.lower().startswith("select"))
    values = {v for row in session.bound for v in row.values()}
    assert "workflows.tenant_id" in select_sql, select_sql
    assert "workflows.status" in select_sql, select_sql
    assert "workflows.trigger_event" in select_sql, select_sql
    assert TENANT in values, "the trigger read is not scoped to one tenant"
    assert "active" in values, "the trigger read does not filter on lifecycle status"
    assert "order.created" in values


async def test_execute_for_event_stages_one_running_execution_per_workflow() -> None:
    """Each staged execution pins the workflow's CURRENT version and carries the
    tenant: ``workflow_executions`` is NOT NULL + FORCE RLS, so an unstamped row
    aborts the whole trigger and a mis-stamped one lands in someone else's
    history."""
    active = _workflow(status="active", current_version=7)
    session = FakeSession(workflows=[active])

    executions = await WorkflowService.execute_for_event(
        session, TENANT, event_type="order.created", event_id=uuid.uuid4(), context={"a": 1}
    )

    staged = [a for a in session.added if isinstance(a, WorkflowExecution)]
    assert len(staged) == 1, f"{len(staged)} executions staged for one active workflow"
    assert staged[0] is executions[0]
    assert staged[0].tenant_id == TENANT
    assert staged[0].workflow_id == active.id
    assert staged[0].workflow_version == 7
    assert staged[0].status == "running"


# ------------------------------------------- §136: a snapshot must RUN -----


@pytest.mark.parametrize(
    "definition",
    [
        {},  # no steps at all: the engine reads .get("steps", []) and "succeeds"
        {"steps": "not-a-list"},
        {"steps": [{"action": "notify"}] * (_MAX_STEPS + 1)},
        {"description": "renamed the field"},
    ],
    ids=["no-steps", "steps-not-a-list", "oversized", "wrong-key"],
)
async def test_publishing_a_definition_the_engine_cannot_run_is_refused(
    definition: dict,
) -> None:
    """§136 — our Workflow Version IS the canonical definition, and execution
    policy sits under it. ``create`` refuses a definition without ``steps``
    (``service.py:50``) and the engine refuses more than ``_MAX_STEPS``
    (``service.py:236``) — but publishing a NEW snapshot checked nothing, so the
    very next write to a live workflow could replace a runnable definition with
    one that silently executes zero steps and reports ``completed``.
    """
    workflow = _workflow()
    session = FakeSession(workflows=[workflow], update_returns=2)

    with pytest.raises(ValidationError):
        await WorkflowService.publish_new_version(
            session, TENANT, workflow.id, definition=definition
        )
    assert not [a for a in session.added if isinstance(a, WorkflowVersion)], (
        "a refused snapshot was still inserted — executions would pin it"
    )


async def test_create_enforces_the_same_definition_rule_as_publish() -> None:
    """The asymmetry IS the bug: create already refuses this input, so the
    publish path has no business accepting it. Pinned so the two can never
    drift apart again."""
    session = FakeSession()
    with pytest.raises(ValidationError):
        await WorkflowService.create(
            session,
            TENANT,
            name="wf",
            trigger_event="order.created",
            definition={},
        )
    with pytest.raises(ValidationError):
        await WorkflowService.create(
            session,
            TENANT,
            name="wf",
            trigger_event="order.created",
            definition={"steps": [{"action": "notify"}] * (_MAX_STEPS + 1)},
        )


async def test_a_legal_snapshot_is_stamped_with_the_version_it_bumps_to() -> None:
    """Immutability + pinning: the snapshot number must be the one the workflow
    row just advanced to, or a running execution pins a version that never
    existed."""
    workflow = _workflow(current_version=3)
    session = FakeSession(workflows=[workflow], update_returns=4)
    version = await WorkflowService.publish_new_version(
        session, TENANT, workflow.id, definition={"steps": [{"action": "set_context"}]}
    )
    assert isinstance(version, WorkflowVersion)
    assert version.version == workflow.current_version == 4


@pytest.mark.parametrize("absent", [None, "*"], ids=["no-header", "star"])
async def test_an_unconditional_publish_still_cas_on_the_version_it_read(
    absent: str | None,
) -> None:
    """§17 — the publish door is the one place an absent If-Match costs money.

    ``apply_versioned_update`` adds ``AND version = :expected`` ONLY when an
    expected version arrives (``core/idempotency.py:784``), so a publish with no
    If-Match issued a bare ``UPDATE workflows SET ... WHERE id`` and BOTH
    writers computed the same ``N+1``. The loser then collided on
    ``uq_workflow_versions_workflow_version`` at INSERT and answered 500, where
    the contract owes a 409. The version this service just read IS the token it
    should CAS on: the door stays usable without a header, and the loser fails
    the way a lost race is supposed to fail.
    """
    workflow = _workflow(current_version=3, version=7)
    session = FakeSession(workflows=[workflow], update_returns=4)

    await WorkflowService.publish_new_version(
        session,
        TENANT,
        workflow.id,
        definition={"steps": [{"action": "notify"}]},
        expected_version=absent,
    )

    updates = [
        (sql, bound)
        for sql, bound in zip(session.sql, session.bound, strict=True)
        if " ".join(sql.split()).lower().startswith("update workflows")
    ]
    assert len(updates) == 1, f"expected exactly one CAS UPDATE, saw {len(updates)}"
    low_sql, bound = updates[0]
    low_sql = " ".join(low_sql.split()).lower()
    assert "and workflows.version = " in low_sql, low_sql
    assert 7 in bound.values(), f"the CAS bound no version: {bound}"


async def test_every_snapshot_names_the_tenant_that_owns_it() -> None:
    """§151 — migration ``a1f2c3d4e5b6`` gives ``workflow_versions`` a NOT NULL
    ``tenant_id`` with no server default, which is the whole reason the table now
    falls under the dynamic RLS sweep. It also means a snapshot written without
    the column is an INSERT failure: both doors that create one would answer 500
    on every call. A row nobody can insert isolates nothing, so the writers are
    part of the contract.
    """
    created = FakeSession()
    await WorkflowService.create(
        created,
        TENANT,
        name="wf",
        trigger_event="order.created",
        definition={"steps": [{"action": "notify"}]},
    )
    on_create = [a for a in created.added if isinstance(a, WorkflowVersion)]
    assert on_create, "create() wrote no version-1 snapshot at all"
    assert [s.tenant_id for s in on_create] == [TENANT] * len(on_create), (
        f"create() wrote snapshots with no tenant: {[s.tenant_id for s in on_create]}"
    )

    workflow = _workflow()
    published = FakeSession(workflows=[workflow], update_returns=2)
    await WorkflowService.publish_new_version(
        published,
        TENANT,
        workflow.id,
        definition={"steps": [{"action": "notify"}]},
    )
    on_publish = [a for a in published.added if isinstance(a, WorkflowVersion)]
    assert len(on_publish) == 1
    assert on_publish[0].tenant_id == TENANT, (
        f"publish() stamped the snapshot with tenant {on_publish[0].tenant_id!r}"
    )


async def test_the_run_path_reads_its_pinned_snapshot_by_tenant() -> None:
    """§151 — the execution read above this one names its tenant; the snapshot
    read did not, because when it was written ``workflow_versions`` had no
    ``tenant_id`` to name. Migration ``a1f2c3d4e5b6`` gave it one, and the RLS
    policy only speaks while the tenant GUC is set — so the predicate is what
    keeps this correct for every caller that reaches it without one.
    """
    workflow = _workflow()
    execution = _execution(workflow)
    session = FakeSession(
        workflows=[workflow],
        executions=[execution],
        versions=[_version(workflow, {"steps": [{"action": "set_context"}]})],
    )

    await WorkflowService.run_execution(session, TENANT, execution.id)

    index = next(i for i, s in enumerate(session.sql) if "from workflow_versions" in s.lower())
    low = " ".join(session.sql[index].split()).lower()
    where = low.split(" where ", 1)[1] if " where " in low else ""
    assert "workflow_versions.tenant_id = " in where, low
    assert TENANT in session.bound[index].values(), session.bound[index]


# ------------------------------------------------ §66/§17: the lifecycle -----


@pytest.mark.parametrize("target", ["draft", "active", "paused", "archived"])
async def test_archived_is_terminal(target: str) -> None:
    """Repo convention, not invention: ``conversations/templates.py`` documents
    ``(anything) --archive--> archived [terminal]`` and enforces it with a
    ``ConflictError`` + an ``ALLOWED_TRANSITIONS`` map
    (``tests/test_template_lifecycle.py``). A workflow that has been withdrawn
    must not be resumable by a status PATCH — re-activating it hands a retired
    definition the power to fire on every matching tenant event."""
    workflow = _workflow(status="archived")
    session = FakeSession(workflows=[workflow], update_returns=2)
    with pytest.raises(ConflictError):
        await WorkflowService.set_status(session, TENANT, workflow.id, target)
    assert workflow.status == "archived", "the refused write mutated the row"
    assert not [s for s in session.sql if s.lower().startswith("update")], (
        "an UPDATE was issued for a transition the lifecycle forbids"
    )


async def test_the_legal_ladder_still_moves() -> None:
    """The guard must not freeze the domain: draft→active (publish), active↔paused
    (resume), and any live state→archived all stay available."""
    for current, target in (
        ("draft", "active"),
        ("active", "paused"),
        ("paused", "active"),
        ("draft", "archived"),
        ("active", "archived"),
        ("paused", "archived"),
    ):
        workflow = _workflow(status=current)
        session = FakeSession(workflows=[workflow], update_returns=2)
        await WorkflowService.set_status(session, TENANT, workflow.id, target)
        assert workflow.status == target, f"{current} -> {target} was refused"


async def test_an_unknown_status_is_still_a_validation_error() -> None:
    session = FakeSession(workflows=[_workflow(status="active")])
    with pytest.raises(ValidationError):
        await WorkflowService.set_status(session, TENANT, uuid.uuid4(), "published")


# ------------------------------- §136: runs honour the lifecycle too --------


@pytest.mark.parametrize("status", ["paused", "archived", "draft"])
async def test_run_never_executes_a_workflow_the_merchant_stopped(status: str) -> None:
    """The trigger path selects ``status == 'active'`` (``service.py:149``); the
    manual ``/run`` door checked nothing, so pausing or archiving a workflow
    left its already-staged executions fully executable — queueing
    notifications and firing webhooks on a definition the merchant withdrew."""
    workflow = _workflow(status=status)
    execution = _execution(workflow)
    session = FakeSession(
        workflows=[workflow],
        executions=[execution],
        versions=[_version(workflow, {"steps": [{"action": "set_context"}]})],
    )

    with pytest.raises(ConflictError):
        await WorkflowService.run_execution(session, TENANT, execution.id)

    assert execution.status == "running", "a refused run must not be marked completed"
    assert not [a for a in session.added if isinstance(a, WorkflowFailure)], (
        "a refused lifecycle must not be recorded as an outage"
    )


async def test_an_active_workflows_execution_runs() -> None:
    """The other half: the guard is lifecycle-only, not a blanket refusal."""
    workflow = _workflow(status="active")
    execution = _execution(workflow, context={"order_id": "1"})
    session = FakeSession(
        workflows=[workflow],
        executions=[execution],
        versions=[_version(workflow, {"steps": [{"action": "set_context", "values": {"k": 1}}]})],
    )
    done = await WorkflowService.run_execution(session, TENANT, execution.id)
    assert done.status == "completed"
    assert done.result["context"]["k"] == 1


async def test_a_finished_execution_is_returned_as_is_without_reaching_the_engine() -> None:
    """§176.6 / gate 12: an operator retry must not multiply history."""
    workflow = _workflow(status="active")
    execution = _execution(workflow, status="failed")
    session = FakeSession(workflows=[workflow], executions=[execution])
    done = await WorkflowService.run_execution(session, TENANT, execution.id)
    assert done is execution
    assert done.status == "failed"
    assert not [s for s in session.sql if "workflow_versions" in s], (
        "a terminal execution was loaded and re-run"
    )


async def test_an_unknown_execution_id_is_a_404_not_a_500() -> None:
    session = FakeSession(executions=[])
    with pytest.raises(NotFoundError):
        await WorkflowService.run_execution(session, TENANT, uuid.uuid4())


async def test_an_execution_of_another_tenant_is_invisible() -> None:
    """Defense in depth over the RLS guarantee: the lookup itself must carry the
    tenant, so a service call made without the GUC bound cannot run someone
    else's execution."""
    foreign = _execution(_workflow(tenant_id=OTHER), tenant_id=OTHER)
    session = FakeSession(executions=[])
    with pytest.raises(NotFoundError):
        await WorkflowService.run_execution(session, TENANT, foreign.id)
    select_sql = next(s for s in session.sql if "workflow_executions" in s)
    assert "workflow_executions.tenant_id" in select_sql
    assert TENANT in {v for row in session.bound for v in row.values()}


# ------------------------------------------------------ the internal engine --


class _Recorder:
    def __init__(self) -> None:
        self.calls: list = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return []


async def test_the_engine_delegates_side_effects_and_bounds_the_steps(
    monkeypatch,
) -> None:
    """§134-style execution bound, and no inline I/O: the notify/webhook steps go
    through the owning module's queueing service (which stages outbox rows), so
    the engine never publishes anything itself."""
    from app.modules.platform.service import NotificationService, WebhookService

    notify, webhook = _Recorder(), _Recorder()
    monkeypatch.setattr(NotificationService, "queue", staticmethod(notify))
    monkeypatch.setattr(WebhookService, "enqueue", staticmethod(webhook))

    workflow = _workflow(status="active")
    execution = _execution(workflow, context={"a": 1})
    steps = [
        {"action": "notify", "message": "hi", "subject": "s"},
        {"action": "webhook", "event": "workflow.done", "name": "hook"},
        {"action": "set_context", "values": {"b": 2}},
    ]
    result = await WorkflowService._run_internal(
        FakeSession(), TENANT, execution, _version(workflow, {"steps": steps})
    )
    assert [o["action"] for o in result["outputs"]] == ["notify", "webhook", "set_context"]
    assert result["context"] == {"a": 1, "b": 2}
    assert len(notify.calls) == 1 and len(webhook.calls) == 1
    assert notify.calls[0][0][1] == TENANT, "the step ran for a tenant other than the row's"


async def test_an_unknown_step_action_fails_the_run_and_is_recorded(monkeypatch) -> None:
    """The failure path is the one the router docstring promises is never a 5xx,
    and it is the path that had zero coverage until §176 gate 12."""
    workflow = _workflow(status="active")
    execution = _execution(workflow)
    session = FakeSession(
        workflows=[workflow],
        executions=[execution],
        versions=[_version(workflow, {"steps": [{"action": "drop_table"}]})],
    )
    done = await WorkflowService.run_execution(session, TENANT, execution.id)
    assert done.status == "failed"
    assert done.error and "drop_table" in done.error
    failures = [a for a in session.added if isinstance(a, WorkflowFailure)]
    assert len(failures) == 1
    assert failures[0].tenant_id == TENANT, (
        "a WorkflowFailure without tenant_id aborts its own transaction (§176 gate 12)"
    )


# ----------------------------------------------------- n8n is only an adapter --


def _code_lines(fn) -> str:
    """A function's source with COMMENT lines removed.

    §136's ban is on CODE that reads the global token; the reason the ban
    exists is written in comments, and a naive substring scan over the whole
    module would fail on the explanation rather than the violation.
    """
    return "\n".join(
        line for line in inspect.getsource(fn).splitlines() if not line.strip().startswith("#")
    )


def test_the_adapter_carries_a_per_tenant_credential_never_the_global_one() -> None:
    """§136: n8n is an adapter, and the token on the wire is tenant-scoped.

    ``_run_n8n`` must take its Bearer from ``automation.tokens`` (digest-stored,
    revocable, one per tenant) and must not reach for a process-wide service
    secret — that is the exact escalation §136's isolation rule names ("لا يملك
    token global unrestricted").
    """
    source = _code_lines(WorkflowService._run_n8n)
    assert "get_or_issue_outbound_token" in source
    for banned in ("settings.service_token", "SERVICE_TOKEN"):
        assert banned not in source, f"the n8n adapter reads a global secret: {banned}"


def test_the_run_reads_our_snapshot_not_a_remote_definition() -> None:
    """§136 canonical-truth rule: the engine executes OUR ``WorkflowVersion``.

    A run that fetched the definition from n8n would make the adapter the
    source of truth the moment anybody edited it there.
    """
    source = _code_lines(WorkflowService.run_execution)
    assert "WorkflowVersion" in source
    assert "workflow_version" in source, "the run must pin the version the row recorded"
