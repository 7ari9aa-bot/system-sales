"""AUTOMATION HTTP surface (spec §136 + §66 + §17 + §151), DB-free.

The eight routes under ``/api/v1/workflows`` had no test of their own: nothing
checked which permission gates a write, whether a read carries the request's
tenant, what the bounds on ``limit`` are, or — the requirement this file exists
for — whether a mutation leaves an audit row (§66: "كل mutation مهم … actor /
action / entity / before / after / tenant", ``docs/spec/ARCHITECTURE_SPEC_1-124.txt:2262``).

Venue: no database on this machine, so the app is driven through
``httpx.ASGITransport`` over ``create_app()`` with ``get_tenant_ctx`` overridden
and a fake session that records the exact SQL each route issues. An unrecognised
statement is a failure, so a route that grows its own SQL is caught here rather
than in production.
"""

from __future__ import annotations

import inspect
import json
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.main import create_app
from app.modules.automation import router as automation_router
from app.modules.automation.models import Workflow, WorkflowExecution, WorkflowVersion
from app.modules.automation.service import WorkflowService
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_TENANT = uuid.UUID("99999999-9999-9999-9999-999999999999")
ACTOR = uuid.UUID("33333333-3333-3333-3333-333333333333")

PREFIX = "/api/v1/workflows"
WRITE_SCOPE = "settings:write"


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
    """The automation routes read three tables and audit into a fourth."""

    def __init__(self, *, workflows=(), versions=(), executions=(), update_returns=2) -> None:
        self.workflows = list(workflows)
        self.versions = list(versions)
        self.executions = list(executions)
        self.update_returns = update_returns
        self.added: list = []
        self.sql: list[str] = []
        self.bound: list[dict] = []
        self.audits: list[dict] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, statement, params=None) -> _Result:
        try:
            compiled = statement.compile(dialect=postgresql.dialect())
            sql, bound = str(compiled), dict(compiled.params)
        except Exception:
            sql, bound = str(statement), {}
        if isinstance(params, dict):
            bound.update(params)
        self.sql.append(" ".join(sql.split()))
        self.bound.append(bound)
        low = self.sql[-1].lower()
        if "into audit_logs" in low:
            self.audits.append(bound)
            return _Result()
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
        raise AssertionError(f"the automation routes asked a question nobody owns: {sql[:160]}")


def _workflow(
    *,
    tenant_id: uuid.UUID = TENANT,
    status: str = "draft",
    current_version: int = 1,
    version: int = 4,
) -> Workflow:
    return Workflow(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="wf",
        description=None,
        trigger_event="order.created",
        status=status,
        current_version=current_version,
        version=version,
        created_at=_now(),
        updated_at=_now(),
    )


def _execution(workflow: Workflow, *, tenant_id: uuid.UUID = TENANT) -> WorkflowExecution:
    return WorkflowExecution(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        workflow_id=workflow.id,
        workflow_version=1,
        status="running",
        trigger_event_type="order.created",
        trigger_event_id=uuid.uuid4(),
        context={},
        started_at=_now(),
        finished_at=None,
    )


def _app(session: FakeSession, *, tenant: uuid.UUID = TENANT, perms: set[str]) -> FastAPI:
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=session,
            user=AuthedUser(id=ACTOR, tenant_id=tenant, role_code="owner"),
            tenant_id=tenant,
            role_code="owner",
            permission_codes=set(perms),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


async def _call(
    session: FakeSession, method: str, path: str, *, perms: set[str] | None = None, **kw
):
    granted = set(perms or ())
    if _is_write(method):
        granted.add(WRITE_SCOPE)
    app = _app(session, perms=granted)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, f"{PREFIX}{path}", **kw)


def _is_write(method: str) -> bool:
    return method.upper() in {"POST", "PATCH", "PUT", "DELETE"}


async def _call_read(session: FakeSession, path: str, *, perms: set[str] | None = None, **kw):
    return await _call(session, "GET", path, perms=perms, **kw)


# ------------------------------------------------------------ the surface ----


def test_the_eight_documented_operations_are_published() -> None:
    """A route that quietly disappears is a door that closes on the tenant."""
    paths = create_app().openapi()["paths"]
    expected = {
        f"{PREFIX}": {"get", "post"},
        f"{PREFIX}/{{workflow_id}}": {"get"},
        f"{PREFIX}/{{workflow_id}}/status": {"patch"},
        f"{PREFIX}/{{workflow_id}}/versions": {"get", "post"},
        f"{PREFIX}/{{workflow_id}}/executions": {"get"},
        f"{PREFIX}/executions/{{execution_id}}/run": {"post"},
    }
    for path, methods in expected.items():
        assert path in paths, f"missing {path}: {sorted(p for p in paths if 'workflow' in p)}"
        assert methods <= set(paths[path]), f"{path} lost {methods - set(paths[path])}"


def test_no_route_lets_the_client_name_a_tenant() -> None:
    """§125: tenancy is the request context's, never a parameter."""
    spec = create_app().openapi()
    for path, operations in spec["paths"].items():
        if not path.startswith(PREFIX):
            continue
        for operation in operations.values():
            names = {p["name"] for p in operation.get("parameters", [])}
            assert "tenant_id" not in names, f"{path} takes a tenant from the caller"

    for _, handler in inspect.getmembers(automation_router, inspect.isfunction):
        if handler.__module__ != automation_router.__name__:
            continue
        assert "tenant_id" not in inspect.signature(handler).parameters, handler.__name__


# ------------------------------------------------- §151: reads are scoped ----


async def test_the_list_read_is_scoped_to_the_context_tenant() -> None:
    session = FakeSession(workflows=[_workflow()])
    response = await _call_read(session, "", perms={"automation:read"})
    assert response.status_code == 200, response.text
    index = next(i for i, s in enumerate(session.sql) if "from workflows" in s.lower())
    low = " ".join(session.sql[index].split()).lower()
    where = low.split(" where ", 1)[1] if " where " in low else ""
    assert "workflows.tenant_id = " in where, low
    assert TENANT in session.bound[index].values(), session.bound[index]


async def test_the_list_read_stays_bounded() -> None:
    """An unbounded ``SELECT * FROM workflows`` is a memory incident waiting to
    happen; the route caps its fetch."""
    session = FakeSession(workflows=[])
    await _call_read(session, "", perms=set())
    sql = next(s for s in session.sql if "from workflows" in s.lower())
    assert "LIMIT" in sql.upper(), sql


async def test_a_status_filter_reaches_the_sql_and_a_bad_one_is_refused() -> None:
    session = FakeSession(workflows=[])
    response = await _call_read(session, "?status=active", perms=set())
    assert response.status_code == 200, response.text
    assert "active" in {v for row in session.bound for v in row.values()}

    refused = FakeSession(workflows=[])
    bad = await _call_read(refused, "?status=deleted", perms=set())
    assert bad.status_code == 422, bad.text


async def test_a_single_read_carries_the_version_and_a_strong_etag() -> None:
    """§17: the body and the header must agree, or If-Match is unobtainable."""
    workflow = _workflow(version=7)
    session = FakeSession(workflows=[workflow])
    response = await _call_read(session, f"/{workflow.id}", perms=set())
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 7
    assert response.headers["etag"] == '"7"'


async def test_another_tenants_workflow_reads_as_not_found_everywhere() -> None:
    """Four reads, one rule: the id is not a permission. The fake holds NO row
    for this tenant, so every read must 404 — and the version/execution lists
    must 404 BEFORE they query the child table. That ordering is the guard that
    holds whichever way the child's own tenancy goes: ``workflow_versions`` has
    carried a ``tenant_id`` (and so its own RLS policy) only since migration
    ``a1f2c3d4e5b6``, and this route predates it.
    """
    foreign_id = uuid.uuid4()
    for path in (f"/{foreign_id}", f"/{foreign_id}/versions", f"/{foreign_id}/executions"):
        session = FakeSession(workflows=[])
        response = await _call_read(session, path, perms=set())
        assert response.status_code == 404, f"{path} -> {response.status_code}: {response.text}"
        children = [
            s for s in session.sql if "workflow_versions" in s or "workflow_executions" in s
        ]
        assert not children, f"{path} read a child table before proving the parent is this tenant's"


async def test_the_execution_list_is_scoped_twice() -> None:
    """By the parent's tenancy (via the 404 guard) AND by an explicit predicate:
    ``workflow_executions`` is FORCE RLS and the index leads on tenant_id."""
    workflow = _workflow()
    session = FakeSession(workflows=[workflow], executions=[])
    response = await _call_read(session, f"/{workflow.id}/executions", perms=set())
    assert response.status_code == 200, response.text
    index = next(i for i, s in enumerate(session.sql) if "from workflow_executions" in s.lower())
    low = " ".join(session.sql[index].split()).lower()
    # See the versions test below for WHY this reads the WHERE clause: the SELECT
    # list already names the column, so matching the whole statement proves nothing.
    where = low.split(" where ", 1)[1] if " where " in low else ""
    assert "workflow_executions.tenant_id = " in where, low
    assert TENANT in session.bound[index].values(), session.bound[index]


async def test_the_version_list_is_scoped_by_tenant_too() -> None:
    """§151 — the child read that had no tenant to name until migration
    ``a1f2c3d4e5b6`` gave ``workflow_versions`` its ``tenant_id``.

    Naming the tenant here is not decoration next to the new RLS policy: the
    policy only bites when the tenant GUC is set, and this repo's own convention
    (``core/idempotency.py``'s CAS, ``workflow_executions`` above) is to pin the
    predicate in the statement so a caller running without the GUC still cannot
    read across tenants.
    """
    workflow = _workflow()
    session = FakeSession(workflows=[workflow], versions=[])
    response = await _call_read(session, f"/{workflow.id}/versions", perms=set())
    assert response.status_code == 200, response.text
    index = next(i for i, s in enumerate(session.sql) if "from workflow_versions" in s.lower())
    low = " ".join(session.sql[index].split()).lower()
    # Asserted on the PREDICATE, not the statement: TenantMixin puts
    # ``workflow_versions.tenant_id`` in the SELECT list, so a substring match on
    # the whole string passes while the WHERE clause names nobody.
    where = low.split(" where ", 1)[1] if " where " in low else ""
    assert "workflow_versions.tenant_id = " in where, low
    assert TENANT in session.bound[index].values(), session.bound[index]


async def test_the_execution_list_limit_is_bounded_on_both_sides() -> None:
    for query, expected in (("?limit=0", 422), ("?limit=201", 422), ("?limit=200", 200)):
        session = FakeSession(workflows=[_workflow()], executions=[])
        response = await _call_read(session, f"/{_workflow().id}/executions{query}", perms=set())
        assert response.status_code == expected, f"{query} -> {response.status_code}"


async def test_run_cannot_reach_another_tenants_execution() -> None:
    execution = _execution(_workflow(tenant_id=OTHER_TENANT), tenant_id=OTHER_TENANT)
    session = FakeSession(executions=[])  # invisible to this tenant
    response = await _call(
        session, "POST", f"/executions/{execution.id}/run", perms={"orders:read"}
    )
    assert response.status_code == 404, response.text
    sql = next(s for s in session.sql if "from workflow_executions" in s.lower())
    assert "workflow_executions.tenant_id" in sql


# --------------------------------------------------- §66: writes are audited --


class _Spy:
    """Stands in for a service method and says exactly what the route passed."""

    def __init__(self, result) -> None:
        self.result = result
        self.calls: list = []
        self.kwargs: list = []

    async def __call__(self, *args, **kwargs):
        self.calls.append(args)
        self.kwargs.append(kwargs)
        return self.result


async def test_creating_a_workflow_is_audited(monkeypatch) -> None:
    """§66 names actor / action / entity / entity_id / before / after / tenant for
    EVERY important mutation. Creating an automation is granting it the right to
    act on tenant data later, so it is not a routine insert.

    ``WorkflowService.create`` is replaced because a fake flush cannot apply the
    ORM's server-side defaults — the id/created_at the response echoes are what
    a real INSERT would generate, not something this venue can mint.
    """
    created = _workflow(status="draft")
    spy = _Spy(created)
    monkeypatch.setattr(WorkflowService, "create", staticmethod(spy))

    session = FakeSession()
    response = await _call(
        session,
        "POST",
        "",
        json={"name": "wf", "trigger_event": "order.created", "definition": {"steps": []}},
    )
    assert response.status_code == 201, response.text
    assert spy.calls[0][1] == TENANT, "the route let a non-context tenant through"
    assert len(session.audits) == 1, (
        f"{len(session.audits)} audit rows for a workflow creation — §66 requires one"
    )
    audit = session.audits[0]
    assert audit["tenant_id"] == TENANT
    assert audit["actor_user_id"] == ACTOR
    assert audit["resource_type"] == "workflow"
    assert audit["resource_id"] == str(created.id)
    # §66's before/after are JSONB: the writer serialises them, so the trail
    # holds the STRUCTURE (which trigger, which backend), not a summary string.
    assert json.loads(audit["after"])["trigger_event"] == "order.created"
    assert json.loads(audit["after"])["status"] == "draft"


async def test_changing_a_workflows_status_is_audited_with_before_and_after() -> None:
    """Publishing (draft→active) turns event triggers ON; archiving turns them
    off. Either way the trail has to say what changed from what to what."""
    workflow = _workflow(status="draft")
    session = FakeSession(workflows=[workflow])
    response = await _call(session, "PATCH", f"/{workflow.id}/status", json={"status": "active"})
    assert response.status_code == 200, response.text
    assert len(session.audits) == 1
    audit = session.audits[0]
    assert audit["tenant_id"] == TENANT
    assert audit["actor_user_id"] == ACTOR
    assert audit["resource_id"] == str(workflow.id)
    assert json.loads(audit["before"]) == {"status": "draft"}
    assert json.loads(audit["after"])["status"] == "active"


async def test_publishing_a_version_is_audited() -> None:
    """An immutable snapshot is the thing every future execution runs, so the
    trail must record who put it up."""
    workflow = _workflow(status="active", current_version=2)
    session = FakeSession(workflows=[workflow])
    response = await _call(
        session,
        "POST",
        f"/{workflow.id}/versions",
        json={"definition": {"steps": [{"action": "set_context", "values": {}}]}},
    )
    assert response.status_code == 201, response.text
    assert len(session.audits) == 1, session.audits
    audit = session.audits[0]
    assert audit["tenant_id"] == TENANT
    assert audit["actor_user_id"] == ACTOR
    assert audit["resource_id"] == str(workflow.id)
    assert json.loads(audit["after"])["version"] == response.json()["version"]


async def test_running_an_execution_is_audited() -> None:
    """A run queues notifications and fires webhooks against tenant data. Without
    a row nobody can answer 'what made this go out at 03:12'."""
    workflow = _workflow(status="active")
    execution = _execution(workflow)
    session = FakeSession(
        workflows=[workflow],
        executions=[execution],
        versions=[
            WorkflowVersion(
                id=uuid.uuid4(),
                workflow_id=workflow.id,
                version=1,
                definition={"steps": [{"action": "set_context", "values": {"k": 1}}]},
                created_at=_now(),
                updated_at=_now(),
            )
        ],
    )
    response = await _call(session, "POST", f"/executions/{execution.id}/run", perms=set())
    assert response.status_code == 200, response.text
    assert len(session.audits) == 1, session.audits
    audit = session.audits[0]
    assert audit["tenant_id"] == TENANT
    assert audit["resource_id"] == str(execution.id)


async def test_a_refused_mutation_leaves_no_audit_row() -> None:
    """The audit row describes a change that HAPPENED. A 403 or a 422 must not
    add one — §67 owns refusals, and a trail padded with denials stops being
    evidence."""
    session = FakeSession()
    async with AsyncClient(
        transport=ASGITransport(app=_app(session, perms=set())), base_url="http://test"
    ) as client:
        denied = await client.post(
            PREFIX,
            json={"name": "wf", "trigger_event": "order.created", "definition": {"steps": []}},
        )
        assert denied.status_code == 403, denied.text

        bad = await _call(session, "POST", "", json={"name": "", "trigger_event": "x"})
        assert bad.status_code == 422, bad.text

    assert session.audits == [], session.audits
    assert session.added == [], "a refused request reached the database"


# ------------------------------------------------ §17 + §136 at the boundary --


async def test_a_stale_if_match_on_publish_is_a_conflict_and_no_snapshot() -> None:
    """Two publishers of one version cannot both win (§17). The fake returns no
    row for the conditional UPDATE, which is what the database answers when the
    version has moved."""
    workflow = _workflow(version=4, current_version=2)
    session = FakeSession(workflows=[workflow], update_returns=None)
    response = await _call(
        session,
        "POST",
        f"/{workflow.id}/versions",
        json={"definition": {"steps": []}},
        headers={"If-Match": '"2"'},
    )
    assert response.status_code == 409, response.text
    assert not [a for a in session.added if isinstance(a, WorkflowVersion)]


async def test_publishing_a_definition_the_engine_cannot_run_is_refused_at_the_door() -> None:
    """§136: the snapshot is the canonical definition, so the HTTP door must
    refuse what the engine cannot execute — as it already does on create."""
    workflow = _workflow(status="active")
    session = FakeSession(workflows=[workflow])
    response = await _call(
        session, "POST", f"/{workflow.id}/versions", json={"definition": {"foo": 1}}
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert not [a for a in session.added if isinstance(a, WorkflowVersion)]


async def test_an_archived_workflow_cannot_be_reactivated_over_http() -> None:
    """Repo lifecycle convention (``conversations/templates.py``: archived is
    terminal), enforced at the service and therefore at the route."""
    workflow = _workflow(status="archived")
    session = FakeSession(workflows=[workflow])
    response = await _call(session, "PATCH", f"/{workflow.id}/status", json={"status": "active"})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"
    assert workflow.status == "archived"


async def test_running_a_workflow_the_merchant_stopped_is_a_conflict() -> None:
    """The trigger path only stages ``status == 'active'`` workflows; the manual
    run door has to honour the same ladder or pausing achieves nothing."""
    workflow = _workflow(status="paused")
    execution = _execution(workflow)
    session = FakeSession(
        workflows=[workflow],
        executions=[execution],
        versions=[
            WorkflowVersion(
                id=uuid.uuid4(),
                workflow_id=workflow.id,
                version=1,
                definition={"steps": []},
                created_at=_now(),
                updated_at=_now(),
            )
        ],
    )
    response = await _call(session, "POST", f"/executions/{execution.id}/run", perms=set())
    assert response.status_code == 409, response.text
    assert execution.status == "running"


# ------------------------------------------------------------ permissioning --


async def test_every_write_needs_the_settings_write_scope() -> None:
    """The module gates writes on one existing permission code (§136 says
    automation is tenant configuration — no invented codes)."""
    workflow = _workflow()
    cases = [
        ("POST", "", {"name": "wf", "trigger_event": "x", "definition": {"steps": []}}),
        ("PATCH", f"/{workflow.id}/status", {"status": "active"}),
        ("POST", f"/{workflow.id}/versions", {"definition": {"steps": []}}),
        ("POST", f"/executions/{uuid.uuid4()}/run", None),
    ]
    for method, path, payload in cases:
        session = FakeSession(workflows=[workflow])
        app = _app(session, perms={"orders:read"})  # NOT settings:write
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(method, f"{PREFIX}{path}", json=payload)
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
        assert session.audits == []
        assert session.added == [], "a denied request still wrote"


def test_writes_are_gated_on_the_write_scope_and_reads_are_not() -> None:
    """The gate is the dependency FastAPI builds, not a convention inside a
    handler: walk every mounted operation and check which context its first
    parameter asks for. A write that quietly switched to ``TenantCtxDep`` would
    otherwise be readable only by whoever notices the missing 403."""
    for route in automation_router.router.routes:
        methods = {m for m in route.methods if m != "HEAD"}
        annotations = [
            str(p.annotation) for p in inspect.signature(route.endpoint).parameters.values()
        ]
        gated = any("WriteCtx" in a for a in annotations)
        reads_context = any("TenantCtxDep" in a for a in annotations)
        if methods & {"POST", "PATCH", "PUT", "DELETE"}:
            assert gated, f"{sorted(methods)} {route.path} has no write gate"
        else:
            assert reads_context, f"{route.path} reads without a bound tenant context"
            assert not gated, f"GET {route.path} is gated on a write permission"


def test_the_write_gate_is_an_existing_permission_code() -> None:
    """§136 says automation is tenant configuration, so it reuses ``settings:write``
    rather than inventing a code no role was ever granted — an invented code is
    an unreachable door."""
    source = inspect.getsource(automation_router)
    assert 'require_permission("settings:write")' in source
    assert 'require_permission("automation' not in source
