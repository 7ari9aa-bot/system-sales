"""OPERATIONS surface contracts — typed replies, clamped params, real errors.

Three defect classes, all reachable without a database.

1. **No response contract.** Every route in ``app/modules/operations/router.py``
   returns a hand-built ``dict``/``list[dict]`` with no ``response_model``, so
   OpenAPI says ``{}`` for the whole module: a client generator learns nothing,
   and a handler that forgets a key fails silently instead of at the edge. The
   gate here is the client-facing one — each route's 2xx schema must resolve to
   a *named* component, which a bare ``dict`` never does.

2. **P7 (docs/GAP_REGISTER.md): unbounded query params.** ``/search?limit=-1``
   reaches ``LIMIT -1``, ``?limit=100000`` is a free amplification knob, and
   ``POST /scheduled-jobs/{id}/reschedule`` accepts a *naive* ``run_at`` that
   Postgres then resolves against the session timezone — a job scheduled for
   09:00 can fire six hours early depending on who is connected.

3. **The v2 error envelope.** ``slo_service.measure_slo`` refuses an unknown
   SLO with a bare ``ValueError``. No ``DomainError``, so ``app.main`` treats it
   as an unhandled crash: 500 ``internal_error`` with ``retryable: true``. The
   caller's typo is answered as the server's fault, and ``retryable`` is what
   drives the client's auto-retry, so it hammers a request that fails
   identically forever.

And the dead-code half of the module — the repo's dominant failure mode,
"complete, unit-tested, imported by nothing". ``TaskService.update_status`` and
``TaskService.get`` had zero callers because ``POST /tasks/{id}/status``
re-implemented the lookup inline, which is also how that endpoint dropped
``assignee_user_id`` from its own request model and how ``POST /tasks`` dropped
``due_date``. ``find_calendar_or_404`` had no caller and no route that could
have one. Each verdict is pinned below.

DB-free throughout: the handlers are driven with the recording-session double
the suite already uses (see ``tests/test_erasure_media_release.py``).
"""

from __future__ import annotations

import ast
import functools
import pathlib
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.main import create_app
from app.modules.operations import sla
from app.modules.operations.router import (
    ScheduledJobReschedule,
    TaskCreate,
    TaskUpdate,
    cancel_job,
    create_task,
    get_job,
    list_jobs,
    measure_one_slo,
    retry_job,
    update_task_status,
)
from app.modules.operations.slo_service import measure_slo
from app.modules.operations.task_service import TaskService

OPERATIONS_MODULE = "app.modules.operations.router"
BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# doubles
# --------------------------------------------------------------------------


class _Result:
    def __init__(self, *, scalar: Any = None, rows: tuple = ()) -> None:
        self._scalar = scalar
        self._rows = rows
        self.rowcount = len(rows)

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> _Result:
        return self

    def all(self) -> tuple:
        return self._rows


class RecordingSession:
    """Answers ``select(...).scalar_one_or_none()`` with ``row``; logs what ran."""

    def __init__(self, row: Any = None, rows: tuple = ()) -> None:
        self.row = row
        self.rows = rows
        self.statements: list[str] = []
        self.flushes = 0

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        self.statements.append(str(statement))
        return _Result(scalar=self.row, rows=self.rows)

    def add(self, obj: Any) -> None:
        self.rows = (*self.rows, obj)

    async def flush(self) -> None:
        self.flushes += 1


def _ctx(session: Any) -> Any:
    return SimpleNamespace(
        session=session,
        tenant_id=uuid.uuid4(),
        user=SimpleNamespace(id=uuid.uuid4()),
    )


def _task(**overrides: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "title": "Call the supplier",
        "status": "todo",
        "priority": 2,
        "assignee_user_id": None,
        "due_date": None,
        "source": "human",
        "description": None,
        "related_entity_type": None,
        "related_entity_id": None,
    }
    return SimpleNamespace(**{**base, **overrides})


def _job(**overrides: Any) -> Any:
    from datetime import UTC, datetime

    base = {
        "id": uuid.uuid4(),
        "kind": "csv_import",
        "status": "failed",
        "progress": 40,
        "attempts": 2,
        "max_attempts": 3,
        "last_error": "boom",
        "result": None,
        "correlation_id": "corr-1",
        "actor_user_id": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    return SimpleNamespace(**{**base, **overrides})


# --------------------------------------------------------------------------
# walk the live graph
# --------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _app() -> Any:
    return create_app()


@functools.lru_cache(maxsize=1)
def _document() -> dict:
    """The one generated OpenAPI document this file reads.

    The mounted surface is asserted against what a client actually receives,
    not against a handler's return annotation — an annotation FastAPI may drop
    (``response_model=None``) or generalise away (``dict``) is exactly the
    nothing-a-client-can-see case this gate is about.
    """
    return _app().openapi()


def _iter_mounted(node: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """``(mounted_path, APIRoute)`` for every route, prefix accumulated.

    FastAPI 0.141 defers ``include_router`` into an ``_IncludedRouter`` that
    exposes neither ``.routes`` nor the prefix on the route itself — the real
    router and its prefix hang off ``include_context`` — so the walk carries
    the prefix down by hand. Without this a module's routes read as
    ``/search`` instead of ``/api/v1/search`` and cannot be matched to the
    OpenAPI document.
    """
    include_ctx = getattr(node, "include_context", None)
    child = getattr(include_ctx, "included_router", None) if include_ctx else None
    if child is not None:
        yield from _iter_mounted(child, prefix + (getattr(include_ctx, "prefix", "") or ""))
    for sub in getattr(node, "routes", None) or []:
        yield from _iter_mounted(sub, prefix)
    if isinstance(node, APIRoute):
        yield prefix + node.path, node


def _mounted_for(module: str) -> dict[tuple[str, str], str]:
    """``(METHOD, path) -> endpoint`` for every route one module owns."""
    out: dict[tuple[str, str], str] = {}
    for path, route in _iter_mounted(_app()):
        if getattr(route.endpoint, "__module__", None) != module:
            continue
        for method in route.methods or ():
            if method not in {"HEAD", "OPTIONS"}:
                out[(method, path)] = route.endpoint.__name__
    return out


def _named_component(schema: Any) -> str | None:
    """The name of the schema a 2xx body resolves to, if it names one at all.

    A ``$ref`` — directly, or as the item type of an array — is a named
    contract a client can generate against. ``{"type": "object"}`` with no ref
    means the route returned a ``dict`` and the shape is undocumented.
    """
    ref = (schema or {}).get("$ref")
    if ref:
        return ref.rsplit("/", 1)[-1]
    for key in ("items", "additionalProperties"):
        sub = (schema or {}).get(key)
        if isinstance(sub, dict) and sub.get("$ref"):
            return sub["$ref"].rsplit("/", 1)[-1]
    return None


def _success_component(document: dict, method: str, path: str) -> str | None:
    operation = document["paths"][path][method.lower()]
    for status in sorted(operation["responses"]):
        if not status.startswith("2"):
            continue
        content = operation["responses"][status].get("content", {})
        schema = content.get("application/json", {}).get("schema")
        if schema is None:
            return None
        return _named_component(schema)
    return None


def _bounds(schema: Any) -> tuple[int | None, int | None]:
    """``(ge, le)`` from a parameter schema, unwrapping the optional form."""
    candidates = [schema, *schema.get("allOf", [])]
    for candidate in candidates:
        if candidate.get("minimum") is not None or candidate.get("maximum") is not None:
            return candidate.get("minimum"), candidate.get("maximum")
    return None, None


def _query_bounds(path: str, name: str, method: str = "get") -> tuple[int | None, int | None]:
    spec = _document()["paths"][f"/api/v1{path}"][method]
    param = next(p for p in spec["parameters"] if p["name"] == name and p["in"] == "query")
    return _bounds(param["schema"])


# ==========================================================================
# 1. every route answers with a named schema
# ==========================================================================


def test_every_operations_route_has_a_typed_response() -> None:
    """No operations endpoint may answer with an undocumented ``dict``."""
    document = _document()
    mounted = _mounted_for(OPERATIONS_MODULE)
    assert len(mounted) >= 20, f"the walk reached only {len(mounted)} operations routes"

    untyped = sorted(
        f"{method} {path} ({endpoint})"
        for (method, path), endpoint in mounted.items()
        if _success_component(document, method, path) is None
    )
    assert not untyped, (
        "these routes return a body OpenAPI cannot name:\n  " + "\n  ".join(untyped)
    )


def test_the_typed_response_gate_can_fail() -> None:
    """Proof the gate above bites, so it cannot be green by matching nothing."""
    probe = FastAPI()

    @probe.get("/untyped")
    async def untyped() -> dict:
        return {"anything": 1}

    @probe.get("/typed")
    async def typed() -> TaskCreate:
        return TaskCreate(title="x")

    @probe.get("/typed-list")
    async def typed_list() -> list[TaskCreate]:
        return []

    document = probe.openapi()
    assert _success_component(document, "GET", "/untyped") is None
    assert _success_component(document, "GET", "/typed") == "TaskCreate"
    assert _success_component(document, "GET", "/typed-list") == "TaskCreate"


# ==========================================================================
# 2. P7 — clamped pagination and date ranges
# ==========================================================================


def test_global_search_limit_is_bounded() -> None:
    """``GET /search?limit=-1`` used to reach ``LIMIT -1`` and answer 500."""
    low, high = _query_bounds("/search", "limit")
    assert low == 1, f"limit must refuse 0 and negatives, got ge={low}"
    assert high is not None and high <= 100, f"limit needs a ceiling, got le={high}"


def test_fairness_check_units_are_bounded() -> None:
    """``units`` multiplies the tenant's budget ask — it needs a ceiling."""
    low, high = _query_bounds("/fairness/check", "units")
    assert low == 1, low
    assert high is not None, "units is unbounded: no ceiling on the pre-flight ask"


def test_jobs_list_limit_is_bounded() -> None:
    """Already clamped before this file; pinned so it cannot regress."""
    assert _query_bounds("/jobs", "limit") == (1, 200)


def test_sla_risk_limit_is_bounded() -> None:
    assert _query_bounds("/sla/risk", "limit") == (1, 200)


def test_reschedule_refuses_a_naive_run_at() -> None:
    """``scheduled_jobs.run_at`` is TIMESTAMPTZ.

    A naive value is resolved by Postgres against the *session* timezone, so
    the same body means a different instant depending on who is connected. The
    API must refuse the ambiguity rather than silently pick a reading.
    """
    with pytest.raises(PydanticValidationError):
        ScheduledJobReschedule(run_at="2026-01-01T09:00:00")
    ScheduledJobReschedule(run_at="2026-01-01T09:00:00+02:00")
    ScheduledJobReschedule(run_at="2026-01-01T07:00:00Z")


def test_task_due_date_is_a_real_datetime() -> None:
    """``due_date`` arrives as an unparsed string today, so a typo is a 500."""
    with pytest.raises(PydanticValidationError):
        TaskCreate(title="x", due_date="tomorrow-ish")
    with pytest.raises(PydanticValidationError):
        TaskCreate(title="x", due_date="2026-01-01T09:00:00")
    TaskCreate(title="x", due_date="2026-01-01T09:00:00Z")


# ==========================================================================
# 3. the v2 error envelope
# ==========================================================================


async def test_unknown_slo_is_a_validation_error_not_an_internal_error() -> None:
    """A caller's typo must not be answered 500 with ``retryable: true``."""
    with pytest.raises(ValidationError) as excinfo:
        await measure_slo(None, uuid.uuid4(), "no_such_slo")  # type: ignore[arg-type]
    assert excinfo.value.http_status == 400
    assert excinfo.value.code == "validation_error"
    assert excinfo.value.retryable is False


async def test_measure_one_slo_route_refuses_an_unknown_name() -> None:
    """Same failure seen from the route: no session is ever needed."""
    with pytest.raises(ValidationError):
        await measure_one_slo(_ctx(RecordingSession()), "no_such_slo")


def _raised_name(node: ast.Raise) -> str | None:
    target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _validator_line_ranges(tree: ast.AST) -> list[range]:
    """Line ranges of pydantic validators, plus the helpers only they delegate to.

    Inside a validator, ``raise ValueError`` is not a bare builtin escaping to the
    500 handler — it is the framework's declared protocol, and pydantic turns it
    into a 422 that the app's own RequestValidationError handler wraps in the v2
    envelope. Flagging it would push the code toward raising a DomainError from
    a validator, which pydantic does NOT catch: that one really does escape.

    The exemption follows the call as well as the decorator, because this module
    factors the timezone check into ``_aware`` and calls it from two validator
    bodies — the raise sits one frame away from the decorator, inside the only
    code that can reach it.
    """
    names = {"field_validator", "model_validator", "validator"}
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    validators: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        functions[node.name] = node
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            label = getattr(target, "id", None) or getattr(target, "attr", None)
            if label in names:
                validators.append(node)
                break

    exempt = list(validators)
    for validator in validators:
        for call in (n for n in ast.walk(validator) if isinstance(n, ast.Call)):
            if isinstance(call.func, ast.Name):
                helper = functions.get(call.func.id)
                if helper is not None:
                    exempt.append(helper)
    return [range(node.lineno, node.end_lineno + 1) for node in exempt]


def test_no_operations_code_raises_a_bare_python_error() -> None:
    """Nothing under ``operations/`` may raise outside ``app.core.errors``.

    A ``ValueError``/``KeyError``/``RuntimeError`` reaches the 500 handler, so
    the module's own input validation is reported to the client as a server
    crash — and as ``retryable``, which is worse.
    """
    offenders: list[str] = []
    for path in sorted((BACKEND_ROOT / "app" / "modules" / "operations").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        exempt = _validator_line_ranges(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and _raised_name(node) in {
                "ValueError",
                "TypeError",
                "KeyError",
                "RuntimeError",
                "Exception",
            }:
                if any(node.lineno in span for span in exempt):
                    continue
                offenders.append(f"{path.name}:{node.lineno} raises {_raised_name(node)}")
    assert not offenders, (
        "raise a DomainError from app.core.errors — a bare builtin answers as "
        "500 internal_error/retryable: " + "; ".join(offenders)
    )


# ==========================================================================
# 4. the task endpoints honour their own request models
# ==========================================================================


async def test_update_task_status_applies_the_assignee_it_declares() -> None:
    """``TaskUpdate.assignee_user_id`` was in the model and dropped by the route.

    The handler read ``body.status`` and ``body.priority`` only, so
    ``{"assignee_user_id": ...}`` answered 200 while reassigning nothing — the
    caller's one signal that a task moved to another agent.
    """
    assignee = uuid.uuid4()
    task = _task()
    session = RecordingSession(row=task)

    await update_task_status(
        _ctx(session), task.id, TaskUpdate(status="in_progress", assignee_user_id=assignee)
    )

    assert task.status == "in_progress"
    assert task.assignee_user_id == assignee, "the route accepted an assignee and discarded it"
    assert session.flushes >= 1


async def test_update_task_status_rejects_an_out_of_range_priority() -> None:
    """``create`` bounds priority at 1..3; ``update`` had no bound at all.

    Both halves are pinned because they refuse in different places: the request
    model bounds it at the door (a pydantic 422 over HTTP), and the service still
    bounds it for a caller that reaches it without the model's help — so the body
    is built with ``model_construct``, which skips validation on purpose.
    """
    task = _task()
    with pytest.raises(PydanticValidationError):
        TaskUpdate(priority=99)

    session = RecordingSession(row=task)
    with pytest.raises(ValidationError):
        await update_task_status(
            _ctx(session), task.id, TaskUpdate.model_construct(priority=99)
        )

    assert task.priority == 2, "the row was written before it was refused"


async def test_update_task_status_reports_a_missing_task_as_404() -> None:
    """The service layer's own 404, not a ``NoneType`` attribute error."""
    with pytest.raises(NotFoundError):
        await TaskService.update_status(
            RecordingSession(row=None), uuid.uuid4(), uuid.uuid4(), status="done"
        )


async def test_task_service_get_is_the_loader_the_status_route_uses() -> None:
    """``TaskService.get`` had no caller at all: wired, retired, wired, retired.

    Verdict WIRE — every task read in this module must be tenant-scoped in one
    place, or the next endpoint that forgets the ``tenant_id`` predicate is a
    cross-tenant leak the boundary tests cannot see.
    """
    calls: list[Any] = []
    original = TaskService.get

    async def _spy(session: Any, tenant_id: Any, task_id: Any) -> Any:
        calls.append(task_id)
        return await original(session, tenant_id, task_id)

    TaskService.get = staticmethod(_spy)  # type: ignore[method-assign]
    try:
        task = _task()
        await TaskService.update_status(
            RecordingSession(row=task), uuid.uuid4(), task.id, status="done"
        )
    finally:
        TaskService.get = original  # type: ignore[method-assign]

    assert calls, "TaskService.update_status still queries Task directly"


async def test_create_task_forwards_the_due_date_it_declares(monkeypatch) -> None:
    """``TaskCreate.due_date`` was parsed by nobody and passed by nobody.

    ``TaskService.create_task`` takes a ``due_date``; the route built the call
    without it, so every task created over HTTP was undated whatever the client
    sent — and the §83 overdue views had nothing to age.
    """
    captured: dict[str, Any] = {}

    async def _spy(_session: Any, _tenant_id: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return _task()

    monkeypatch.setattr(TaskService, "create_task", staticmethod(_spy))
    await create_task(
        _ctx(RecordingSession()),
        TaskCreate(title="Chase the quote", due_date="2026-02-01T09:00:00Z"),
    )

    assert captured.get("due_date") is not None, (
        f"due_date never reached the service: {sorted(captured)}"
    )


# ==========================================================================
# 5. dead-code verdicts, pinned
# ==========================================================================


def test_the_status_route_goes_through_the_service_layer() -> None:
    """§13-14: the router must not re-implement a task mutation inline.

    ``create_task`` already delegates to ``TaskService`` and says so; the status
    route carried the same comment and did its own ``select(Task)``. That split
    is exactly how the assignee and the priority bound went missing — the
    service held the rules and the route never asked it.
    """
    src = (BACKEND_ROOT / "app" / "modules" / "operations" / "router.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    handler = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "update_task_status"
    )
    called = {
        (node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id)
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert "update_status" in called, (
        "POST /tasks/{id}/status must mutate through TaskService.update_status"
    )
    assert "select" not in called, "the route is doing its own ORM query again"


def test_find_calendar_or_404_is_retired_not_kept() -> None:
    """Verdict RETIRE. Evidence, in order:

    * zero references anywhere under ``app/``, ``scripts/`` or ``migrations/``
      outside its own ``def`` and its own ``__all__`` entry;
    * it searched a *list of rows* by id, but the SLA surface upserts calendars
      by ``name`` (``PUT /sla/calendars``) and exposes no ``/calendars/{id}``
      route, so no caller exists and none can be written without inventing
      product surface;
    * a helper whose only job is to raise ``NotFoundError`` for a lookup nobody
      performs is the failure mode this module keeps producing.
    """
    assert not hasattr(sla, "find_calendar_or_404")
    assert "find_calendar_or_404" not in sla.__all__


# ==========================================================================
# 6. the job endpoints keep the state machine they document
# ==========================================================================


async def test_retry_of_a_completed_job_is_a_conflict_and_not_retryable() -> None:
    session = RecordingSession(row=_job(status="completed"))
    with pytest.raises(ConflictError) as excinfo:
        await retry_job(uuid.uuid4(), _ctx(session))
    assert excinfo.value.http_status == 409
    assert excinfo.value.retryable is False
    assert session.flushes == 0


async def test_cancel_of_a_terminal_job_is_refused_without_writing() -> None:
    job = _job(status="cancelled")
    session = RecordingSession(row=job)
    with pytest.raises(ConflictError):
        await cancel_job(job.id, _ctx(session))
    assert session.flushes == 0, "a refused cancel still touched the row"


async def test_job_replies_share_one_named_contract() -> None:
    """``GET /jobs`` and ``GET /jobs/{id}`` must answer from one model.

    Two hand-built dicts drift: the list view grows a field, the detail view
    does not, and a row the client paged past is unexplainable when opened.
    """
    job = _job()
    detail = await get_job(_ctx(RecordingSession(row=job)), job.id)
    listing = await list_jobs(_ctx(RecordingSession(rows=(_job(kind="bulk_export"),))))

    assert detail.id == job.id
    assert detail.status == "failed"
    assert listing.items[0].kind == "bulk_export"
