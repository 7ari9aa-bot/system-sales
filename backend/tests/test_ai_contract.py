"""§47/ADR-053, §157/§158, §135 — the AI surface must answer with a typed
contract, and its money must still be money on the other side of the wire.

``app/modules/ai/router.py`` carries 24 routes and, before this file, not one of
them declared a ``response_model``: the return annotations were ``dict`` /
``list[dict]``, which FastAPI publishes as an open object — "any key may appear,
any key may be missing". That is the same hole as a hand-built dict, just
documented, and it is where governed state goes to disappear:

* a knowledge item's ``status`` and §157 ``visibility`` (the two columns that
  decide whether retrieval may show it at all);
* an agent's guardrail configuration (``run_limits``, ``temperature``,
  ``max_output_tokens``) — ``is_active`` alone is not "the governance state of
  this agent";
* a memory's review state (``source``, ``status``, ``actor_id``,
  ``verified_at``/``invalidated_at``/``expires_at``) — §158 is a review loop, and
  a claim whose retirement timestamp can quietly stop being sent is not
  reviewable;
* §135's approval binding (``payload_hash``, ``approved_by_user_id``) — the hash
  is the thing that makes an approval cover the arguments it approved;
* the usage period total §55 requires the ROUTE to compute.

The money rule is the other half, and it is a floor this repo has already been
shown through: ``ai_usage.cost``, ``agent_runs.cost`` and ``model_calls.cost``
are ``Numeric(18,8)``, whose entire reason to exist is the eight places BELOW
one cent that a float64 cannot hold. ``test_ai_money_wire.py`` pins the
``ai_usage`` rollup at the function level; what nothing pinned is the boundary
that actually publishes bytes — a route may still turn an amount into a number,
or into ``Decimal``'s scientific spelling (``2E-8``), after the function
returned. These cases assert on the raw HTTP body, so the response model itself
is on trial.

DB-free throughout except the last case, which needs a real ``ai_usage`` row and
so skips without ``DATABASE_URL_APP_ADMIN`` — CI-only, labelled as such.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.approvals import ApprovalService  # noqa: F401  (typing the stub)
from app.modules.ai.models import Agent, AIUsage, ApprovalRequest, Memory
from app.modules.ai.router import (
    _approval_out,
    _evaluation_out,
    _memory_out,
    _policy_out,
)
from app.modules.ai.router import (
    router as ai_router,
)
from app.modules.ai.trace import AITraceService

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")
AGENT = uuid.UUID("33333333-3333-3333-3333-333333333333")
RUN = uuid.UUID("44444444-4444-4444-4444-444444444444")

# ``AI_COST`` is Numeric(18,8): ten integer digits plus eight places. The big
# figure is the float64 probe (18 significant digits cannot survive a float);
# the small one is the SPELLING probe — Python renders it `2E-8`, which is exact
# but is not a decimal the client is promised.
BIG = Decimal("9999999999.12345678")
SUB_CENT = Decimal("0.00000002")

assert str(SUB_CENT) == "2E-8", "the probe relies on Decimal's scientific spelling"
assert Decimal(str(float(BIG))) != BIG, "the probe relies on float64 losing digits"


# ---------------------------------------------------------------------------
# harness: this router alone, mounted as main.py mounts it
# ---------------------------------------------------------------------------


def _app(session: Any = None) -> FastAPI:
    """The AI routes on a bare app, with the tenant dependency faked.

    Not ``create_app()``: a contract check on these 24 routes should not depend
    on seventeen other modules importing cleanly. Money/field assertions below
    read the RAW body, so the response model under test is the real one —
    FastAPI builds it here exactly as it does in production.
    """
    from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

    ctx = TenantContext(
        session=session,
        user=AuthedUser(id=USER, tenant_id=TENANT, role_code="owner"),
        tenant_id=TENANT,
        role_code="owner",
        permission_codes={"settings:write"},
    )

    app = FastAPI()
    app.include_router(ai_router, prefix="/api/v1")

    async def _fake_ctx() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _fake_ctx
    return app


def _routes() -> list[APIRoute]:
    return [r for r in ai_router.routes if isinstance(r, APIRoute)]


def _resolve(document: dict, node: dict) -> dict:
    for _ in range(4):
        if "$ref" in node:
            node = document["components"]["schemas"][node["$ref"].rsplit("/", 1)[1]]
        elif node.get("type") == "array":
            node = node["items"]
        else:
            break
    if "$ref" in node:
        node = document["components"]["schemas"][node["$ref"].rsplit("/", 1)[1]]
    return node


def _properties(path: str, method: str) -> dict:
    """Declared properties of one route's 2xx JSON body, as a client sees it."""
    document = _app().openapi()
    entry = document["paths"][path][method.lower()]
    statuses = [s for s in entry["responses"] if s.startswith("2") and s != "204"]
    assert statuses, f"{method.upper()} {path} declares no 2xx body"
    schema = entry["responses"][statuses[0]]["content"]["application/json"]["schema"]
    return _resolve(document, schema).get("properties") or {}


# ---------------------------------------------------------------------------
# 1. The gate: 24 routes, none of them typed
# ---------------------------------------------------------------------------


def _is_untyped(model: Any) -> bool:
    """Is this response model "anything may appear" rather than a contract?

    ``dict``, ``list``, an empty ``BaseModel``, and a ``list[dict]`` element all
    publish an open object, so all four are the same hole.
    """
    if model is None or model in (dict, list):
        return True
    fields = getattr(model, "model_fields", None)
    if fields is not None:
        return not fields
    args = getattr(model, "__args__", None)
    if args:
        return any(_is_untyped(arg) for arg in args)
    return False


def test_no_ai_route_answers_through_an_untyped_body() -> None:
    """Every AI route declares a response model with declared properties.

    A ``dict`` return annotation is not a contract: it publishes an open object
    and lets any key vanish without anything failing. The 204 is the one shape
    that needs no model — it has no body to mis-type.
    """
    untyped = sorted(
        f"{sorted(r.methods)} {r.path}"
        for r in _routes()
        if not (r.status_code == 204 and r.response_model is None) and _is_untyped(r.response_model)
    )
    assert not untyped, (
        "AI routes still answering through an untyped body:\n  " + "\n  ".join(untyped)
    )


def test_the_openapi_document_publishes_no_open_object_for_ai() -> None:
    """The consequence, checked where clients read it: the OpenAPI document.

    ``route.response_model`` can be a model and still publish ``{"type":
    "object"}`` with no properties if that model is a bare dict. This walk is
    the externally visible half of the gate.
    """
    document = _app().openapi()
    open_bodies: list[str] = []
    for path, entry in document["paths"].items():
        if not path.startswith("/api/v1/ai"):
            continue
        for method, operation in entry.items():
            for status, response in operation["responses"].items():
                if status == "204" or "content" not in response:
                    continue
                schema = response["content"]["application/json"]["schema"]
                resolved = _resolve(document, schema)
                if not resolved.get("properties"):
                    open_bodies.append(f"{method.upper()} {path} [{status}]")
    assert not open_bodies, (
        "these AI responses are typed as an object with no properties, which is "
        "the schema-level permission to drop any field:\n  " + "\n  ".join(sorted(open_bodies))
    )


def test_the_ai_surface_has_24_routes_to_cover() -> None:
    """Keeps the gate honest: a walk over an empty route list passes anything."""
    assert len(_routes()) == 24, f"expected 24 AI routes, found {len(_routes())}"


# ---------------------------------------------------------------------------
# 2. Governed state, field by field
# ---------------------------------------------------------------------------


def test_knowledge_routes_declare_status_and_visibility() -> None:
    """§157: ``status`` and ``visibility`` ARE the governance of a knowledge item.

    Retrieval filters on both before a row may reach a model's context, so the
    staff surface that reviews them cannot be allowed to answer "whatever the
    dict carried". ``list_knowledge`` shipped only id/title/status/created_at —
    the visibility column was never on the wire at all.
    """
    page = _properties("/api/v1/ai/knowledge", "get")
    assert {"items", "next_cursor"} <= set(page), page
    item = _resolve(_app().openapi(), page["items"]["items"])["properties"]
    for field in ("id", "title", "source_type", "source_ref", "status", "visibility", "created_at"):
        assert field in item, f"GET /ai/knowledge item schema has no {field}: {sorted(item)}"

    # `_properties` ALREADY resolves to the field-name → schema mapping (it ends
    # in `_resolve(...).get("properties")`), so re-resolving it and indexing
    # ["properties"] asks for a field named "properties" that no schema here has.
    hit = _properties("/api/v1/ai/knowledge/search", "get")
    for field in ("id", "title", "source_type", "content", "distance", "visibility"):
        assert field in hit, f"search hit has no {field}: {sorted(hit)}"

    ingested = _properties("/api/v1/ai/knowledge", "post")
    assert {"id", "status", "visibility"} <= set(ingested), ingested


def test_agents_surface_declares_its_guardrails_and_withholds_its_prompt() -> None:
    """Both halves of the agent contract: what must be there, what must not.

    ``run_limits`` is the per-agent execution guardrail block (§44/§135 runtime
    limits), ``temperature``/``max_output_tokens`` shape every call the agent
    makes, and ``is_active`` is the kill switch — none of them were reachable
    through ``AgentOut``, which typed four columns. ``system_prompt`` stays off:
    ``GET /ai/agents`` is open to any authenticated member of the tenant, not
    only to ``settings:write`` staff, and the prompt is the one field whose
    disclosure is a business secret rather than governance state.
    """
    properties = _properties("/api/v1/ai/agents", "get")
    item = properties
    for field in (
        "id",
        "name",
        "model",
        "is_active",
        "temperature",
        "max_output_tokens",
        "run_limits",
        "version",
    ):
        assert field in item, f"agent response has no {field}: {sorted(item)}"
    assert "system_prompt" not in item, (
        "GET /ai/agents is tenant-authenticated, not settings:write — the prompt "
        "text must not ride along with the list"
    )
    created = _properties("/api/v1/ai/agents", "post")
    assert created.keys() == item.keys(), (
        "the create and list halves of one agent must describe it the same way"
    )


def test_memory_review_state_is_typed_end_to_end() -> None:
    """§158: review / edit / invalidate / delete is a state machine, so the
    state has to be on the contract rather than in whoever-happens-to-read-the-
    dict folklore. ``source`` is the provenance that makes "customer said X"
    different from "system verified X"; the three timestamps are the audit."""
    page = _properties("/api/v1/ai/memories", "get")
    assert {"items", "next_cursor"} <= set(page), page
    item = _resolve(_app().openapi(), page["items"]["items"])["properties"]

    for field in (
        "id",
        "kind",
        "content",
        "source",
        "status",
        "confidence",
        "customer_id",
        "conversation_id",
        "actor_id",
        "created_at",
        "verified_at",
        "invalidated_at",
        "expires_at",
    ):
        assert field in item, f"memory response has no {field}: {sorted(item)}"

    for path, method in (
        ("/api/v1/ai/memories", "post"),
        ("/api/v1/ai/memories/{memory_id}", "patch"),
        ("/api/v1/ai/memories/{memory_id}/invalidate", "post"),
    ):
        properties = _properties(path, method)
        missing = set(item) - set(properties)
        assert not missing, f"{method.upper()} {path} drops {sorted(missing)} of the memory state"


def test_approvals_declare_the_binding_that_makes_an_approval_specific() -> None:
    """§135 review G-02: ``payload_hash`` is why an approval covers the
    arguments it approved instead of merely the action NAME. A queue a reviewer
    cannot audit after the fact — who decided, when, on what digest — is not a
    governance surface, and neither field was typed.
    """
    page = _properties("/api/v1/ai/approvals", "get")
    assert {"items", "truncated"} <= set(page), page
    item = _resolve(_app().openapi(), page["items"]["items"])["properties"]

    for field in (
        "id",
        "status",
        "action",
        "risk_level",
        "entity_type",
        "entity_id",
        "payload",
        "payload_hash",
        "requested_by",
        "expires_at",
        "decided_at",
        "consumed_at",
        "approved_by_user_id",
        "rejection_reason",
        "created_at",
    ):
        assert field in item, f"approval response has no {field}: {sorted(item)}"

    decided = _properties("/api/v1/ai/approvals/{approval_id}/decide", "post")
    assert set(item) <= set(decided), "decide must return the same approval shape"
    assert decided["resumed"]["type"] == "boolean", decided.get("resumed")


def test_provider_policy_and_evaluation_surfaces_are_typed() -> None:
    """§43 egress governance and §169 rollout state, both as objects."""
    listing = _properties("/api/v1/ai/provider-policies", "get")
    policy = _resolve(_app().openapi(), listing["items"]["items"])["properties"]
    for field in (
        "provider",
        "status",
        "allowed_models",
        "pii_redaction_required",
        "data_classification",
        "data_residency",
        "retention_terms",
        "updated_at",
    ):
        assert field in policy, f"provider policy has no {field}: {sorted(policy)}"
    assert _properties("/api/v1/ai/provider-policies", "put").keys() == policy.keys()

    evaluations = _properties("/api/v1/ai/evaluations", "get")
    evaluation = _resolve(_app().openapi(), evaluations["items"]["items"])["properties"]
    for field in (
        "id",
        "agent_id",
        "prompt_version",
        "dataset_ref",
        "status",
        "quality_metrics",
        "rollout_status",
        "notes",
    ):
        assert field in evaluation, f"evaluation has no {field}: {sorted(evaluation)}"

    for path, method in (
        ("/api/v1/ai/evaluations", "post"),
        ("/api/v1/ai/evaluations/{evaluation_id}", "patch"),
        ("/api/v1/ai/evaluations/submit", "post"),
        ("/api/v1/ai/evaluations/{agent_version_id}/status", "get"),
        ("/api/v1/ai/evaluations/{agent_version_id}/approve", "post"),
    ):
        missing = set(evaluation) - set(_properties(path, method))
        assert not missing, f"{method.upper()} {path} drops {sorted(missing)} of the evaluation"


def test_trace_routes_type_the_evidence_they_exist_to_produce() -> None:
    """§44: "what did the AI do, and why" — tokens are counts, cost is money.

    The trace payload is the one AI surface that reports spend PER CALL, and it
    was assembled from a dict of ``Decimal`` values with no declared shape.
    ``by_correlation`` returns the run-summary list; ``for_run`` adds the model
    and tool children.
    """
    run = _properties("/api/v1/ai/trace/runs/{run_id}", "get")
    for field in (
        "run_id",
        "agent_id",
        "status",
        "tokens_in",
        "tokens_out",
        "cost",
        "model",
        "provider",
        "latency_ms",
        "fallback",
        "tools",
        "errors",
        "model_calls",
        "tool_calls",
        "correlation_id",
        "causation_id",
    ):
        assert field in run, f"trace run has no {field}: {sorted(run)}"
    assert run["cost"].get("type") == "string", f"run cost is not a decimal string: {run['cost']}"

    call = _resolve(_app().openapi(), run["model_calls"]["items"])["properties"]
    assert call["cost"].get("type") == "string", f"per-call cost: {call['cost']}"

    summary = _properties("/api/v1/ai/trace/summary", "get")
    assert summary["total_cost"].get("type") == "string", summary["total_cost"]
    for field in ("runs", "failures", "fallback_count", "tokens_in", "tokens_out", "total_tokens"):
        assert summary[field]["type"] == "integer", (field, summary[field])

    correlation = _properties("/api/v1/ai/trace/correlation/{correlation_id}", "get")
    assert {"correlation_id", "runs"} <= set(correlation), correlation
    first_run = _resolve(_app().openapi(), correlation["runs"]["items"])["properties"]
    assert first_run["cost"].get("type") == "string", first_run["cost"]


# ---------------------------------------------------------------------------
# 3. Money on the wire: raw bytes, not the handler's return value
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, *, rows: list = (), scalar: Any = None, one: Any = None) -> None:
        self._rows, self._scalar, self._one = rows, scalar, one

    def scalars(self) -> _Result:
        return self

    def all(self) -> list:
        return list(self._rows)

    def one(self) -> Any:
        return self._one

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._one


class _Session:
    """Answers just enough for the read paths under test, by table name."""

    def __init__(self, *, rollup: list = (), run: Any = None, calls: list = ()) -> None:
        self.rollup, self.run, self.calls = rollup, run, list(calls)

    async def execute(self, statement, params=None):  # noqa: ANN001
        sql = str(statement)
        if "ai_usage" in sql:
            return _Result(rows=self.rollup)
        if "model_calls" in sql:
            return _Result(rows=[c for c in self.calls if "cost" in repr(c)])
        if "tool_calls" in sql:
            return _Result(rows=[c for c in self.calls if "cost" not in repr(c)])
        if "count(" in sql and "agent_runs" in sql:
            return _Result(one=(2, 1, 100, 50, SUB_CENT + BIG))
        if "model_calls" in sql:
            return _Result(scalar=0)
        return _Result(one=self.run)


def _usage_rows() -> list[tuple]:
    return [
        (date(2026, 9, 1), 1200, 800, BIG),
        (date(2026, 9, 2), 100, 50, SUB_CENT),
    ]


async def test_the_usage_summary_money_survives_the_response_model() -> None:
    """§47: an AMOUNT crosses JSON as a string, at the boundary that publishes it.

    ``test_ai_money_wire`` proved the handler returns ``str(Decimal)``. That is
    half the path: a response model typed ``float`` would undo it in the
    serialiser, and a model typed ``str`` would accept ``"2E-8"`` — exact, but
    not the fixed-point decimal the field promises. Asserted on raw text.
    """
    transport = ASGITransport(app=_app(_Session(rollup=_usage_rows())))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/ai/usage/summary")

    assert response.status_code == 200, response.text
    body = response.text
    document = response.json()
    day = document["summary"][1]

    assert isinstance(day["cost"], str), f"cost left the wire as {type(day['cost'])}"
    assert day["cost"] == "0.00000002", (
        f"a sub-cent spend must be published as a plain fixed-point decimal, got {day['cost']!r}"
    )
    assert '"2E-8"' not in body and "2e-8" not in body.lower(), body
    assert Decimal(document["summary"][0]["cost"]) == BIG, document["summary"][0]
    assert Decimal(document["totals"]["cost"]) == BIG + SUB_CENT, document["totals"]
    # The other half of §47's line: counts stay counts.
    assert day["tokens_in"] == 100 and isinstance(day["tokens_in"], int)


async def test_trace_money_is_a_decimal_string_and_never_a_float() -> None:
    """The per-call and rollup costs of §44 are the same money as §47's.

    ``AITraceService`` hands the route ``Decimal`` values inside a bare dict.
    Untyped, that reaches a client as whatever the default encoder makes of a
    ``Decimal`` — which is the float-on-the-wire bug class this repo already
    fixed in ``marketing`` and ``orders``, arriving through a door nobody was
    watching.
    """
    run = SimpleNamespace(
        id=RUN,
        agent_id=AGENT,
        conversation_id=None,
        status="succeeded",
        tokens_in=100,
        tokens_out=50,
        cost=BIG,
        error=None,
        started_at=None,
        finished_at=None,
        created_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
        input={},
    )
    model_call = SimpleNamespace(
        id=uuid.uuid4(),
        alias="strong",
        provider="openai",
        model="gpt-test",
        tokens_in=100,
        tokens_out=50,
        cost=SUB_CENT,
        latency_ms=12,
        status="ok",
    )
    session = _Session(run=run, calls=[model_call])
    transport = ASGITransport(app=_app(session))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        traced = await client.get(f"/api/v1/ai/trace/runs/{RUN}")
        summary = await client.get("/api/v1/ai/trace/summary")

    assert traced.status_code == 200, traced.text
    assert traced.json()["cost"] == "9999999999.12345678", traced.json()["cost"]
    assert traced.json()["model_calls"][0]["cost"] == "0.00000002", traced.json()["model_calls"]
    assert summary.status_code == 200, summary.text
    # The rollup stub answers `one=(2, 1, 100, 50, SUB_CENT + BIG)`, so the total
    # is BIG + SUB_CENT = 9999999999.12345680 — the same sum this file pins two
    # assertions earlier (`Decimal(totals["cost"]) == BIG + SUB_CENT`). The old
    # literal was exactly 1.0 higher (it had swallowed the tuple's `failures`
    # element), and `ai_usage.cost` is Numeric(18,8): ten integer digits, so
    # 10000000000.12345680 is not a value this column can ever hold.
    assert summary.json()["total_cost"] == "9999999999.12345680", summary.json()["total_cost"]
    for text in (traced.text, summary.text):
        assert "2E-8" not in text, text


# ---------------------------------------------------------------------------
# 4. Nothing the handler builds may be filtered away by the model
# ---------------------------------------------------------------------------


def _memory() -> Memory:
    memory = Memory(
        tenant_id=TENANT,
        kind="fact",
        content="prefers whatsapp",
        customer_id=None,
        conversation_id=None,
    )
    memory.id = uuid.uuid4()
    memory.source = "staff_entered"
    memory.status = "active"
    memory.confidence = Decimal("0.9000")
    memory.actor_id = USER
    memory.created_at = datetime(2026, 9, 1, 8, tzinfo=UTC)
    memory.verified_at = None
    memory.invalidated_at = None
    memory.expires_at = None
    return memory


def _approval() -> ApprovalRequest:
    approval = ApprovalRequest(
        tenant_id=TENANT,
        entity_type="order",
        entity_id="abc",
        action="create_order",
    )
    approval.id = uuid.uuid4()
    approval.status = "PENDING"
    approval.risk_level = "HIGH"
    approval.payload = {"arguments": {"quantity": 1}}
    approval.requested_by = "ai"
    approval.created_at = datetime(2026, 9, 1, 8, tzinfo=UTC)
    approval.conversation_id = None
    approval.run_id = None
    approval.expires_at = None
    approval.decided_at = None
    approval.consumed_at = None
    approval.rejection_reason = None
    return approval


@pytest.mark.parametrize(
    ("builder", "path", "method", "wrapper"),
    [
        (_memory_out, "/api/v1/ai/memories/{memory_id}", "patch", None),
        (_approval_out, "/api/v1/ai/approvals", "get", "items"),
        (_policy_out, "/api/v1/ai/provider-policies", "put", None),
        (_evaluation_out, "/api/v1/ai/evaluations", "get", "items"),
    ],
)
def test_every_field_a_handler_builds_is_declared(
    builder: Any, path: str, method: str, wrapper: str | None
) -> None:
    """A response model is a FILTER as much as a document.

    Keys the handler builds and the model does not declare are dropped in
    silence. Each pair here is compared against the real builder's output, so
    adding a field to one side and forgetting the other fails this test — which
    is the mechanism, not a restatement of the models.
    """
    row = _memory() if builder is _memory_out else _approval() if builder is _approval_out else None
    if builder is _policy_out:
        from app.modules.ai.models import AIProviderPolicy

        row = AIProviderPolicy(tenant_id=TENANT, provider="openai", status="allowed")
        row.id = uuid.uuid4()
        row.allowed_models = ["gpt-test"]
        row.pii_redaction_required = False
        row.data_classification = "internal"
        row.updated_at = datetime(2026, 9, 1, 8, tzinfo=UTC)
    if builder is _evaluation_out:
        from app.modules.ai.models import AIEvaluation

        row = AIEvaluation(tenant_id=TENANT, agent_id=AGENT, status="pending")
        row.id = uuid.uuid4()
        row.prompt_version = 1
        row.quality_metrics = {}
        row.rollout_status = "none"
        row.created_at = datetime(2026, 9, 1, 8, tzinfo=UTC)
        row.updated_at = datetime(2026, 9, 1, 8, tzinfo=UTC)

    built = set(builder(row))
    properties = _properties(path, method)
    if wrapper:
        properties = _resolve(_app().openapi(), properties[wrapper]["items"])["properties"]

    dropped = built - set(properties)
    assert not dropped, (
        f"{method.upper()} {path} drops fields the handler builds: {sorted(dropped)}"
    )


def test_no_field_is_declared_that_no_handler_builds() -> None:
    """The other direction: a typed contract that promises a key the code never
    produces is a client bug waiting for the first null check to be removed."""
    built = {
        "memory": set(_memory_out(_memory())),
        "approval": set(_approval_out(_approval())),
    }
    declared = {
        "memory": set(
            _resolve(_app().openapi(), _properties("/api/v1/ai/memories", "get")["items"]["items"])[
                "properties"
            ]
        ),
        "approval": set(
            _resolve(
                _app().openapi(), _properties("/api/v1/ai/approvals", "get")["items"]["items"]
            )["properties"]
        ),
    }
    for name in built:
        extra = declared[name] - built[name]
        assert not extra, f"{name} response declares keys no handler builds: {sorted(extra)}"


def test_the_trace_service_dict_and_the_typed_model_agree() -> None:
    """``AITraceService.for_run`` assembles ~30 keys; the model must cover them.

    The service is the producer, so it is asked directly — with a stub session —
    for the key set, and the route is then asked what it declares. This is the
    guard against typing the trace response from memory of the docstring.
    """
    run = SimpleNamespace(
        id=RUN,
        agent_id=AGENT,
        conversation_id=None,
        status="succeeded",
        tokens_in=1,
        tokens_out=1,
        cost=SUB_CENT,
        error=None,
        started_at=None,
        finished_at=None,
        created_at=datetime(2026, 9, 1, 8, tzinfo=UTC),
        input={"correlation_id": "corr-1"},
    )
    session = _Session(run=run, calls=[])
    produced = set(asyncio.run(AITraceService.for_run(session, TENANT, RUN)))
    declared = set(_properties("/api/v1/ai/trace/runs/{run_id}", "get"))

    missing = produced - declared
    assert not missing, (
        f"the trace service returns keys the route does not declare: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# 5. CI-only: the same money through a real Numeric(18,8) column
# ---------------------------------------------------------------------------


async def test_a_real_numeric_cost_row_leaves_the_api_as_an_exact_string(
    db: AsyncSession, tenant_ctx
) -> None:
    """asyncpg → Numeric(18,8) → route → bytes, with nothing rounded away.

    CI-only (needs ``DATABASE_URL_APP_ADMIN``). The stubbed cases above prove the
    serialiser; this proves the column's scale is what the serialiser sees, which
    a stub can only assume.
    """
    from app.modules.ai.usage import bucket_row_id

    period = date.today()
    db.add(
        AIUsage(
            id=bucket_row_id(tenant_ctx.tenant_id, period, None),
            tenant_id=tenant_ctx.tenant_id,
            period_date=period,
            tokens_in=7,
            tokens_out=3,
            cost=SUB_CENT,
        )
    )
    await db.flush()

    from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=USER, tenant_id=tenant_ctx.tenant_id, role_code="owner"),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"settings:write"},
    )

    async def _fake_ctx() -> TenantContext:
        return ctx

    app = _app()
    app.dependency_overrides[get_tenant_ctx] = _fake_ctx
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/ai/usage/summary", params={"days": 1})

    assert response.status_code == 200, response.text
    payload = json.loads(response.text)
    row = next(r for r in payload["summary"] if r["tokens_in"] == 7)
    assert row["cost"] == "0.00000002", row
    assert Decimal(payload["totals"]["cost"]) == SUB_CENT, payload["totals"]


def test_agent_model_carries_the_columns_the_response_now_declares() -> None:
    """The response model may not invent columns. Cheap metadata cross-check."""
    columns = set(Agent.__table__.c.keys())
    declared = set(_properties("/api/v1/ai/agents", "get"))
    assert declared <= columns | {"run_limits"}, (
        f"agent response declares non-columns: {sorted(declared - columns)}"
    )


def test_memory_model_carries_the_state_the_review_surface_declares() -> None:
    columns = set(Memory.__table__.c.keys())
    declared = set(
        _resolve(_app().openapi(), _properties("/api/v1/ai/memories", "get")["items"]["items"])[
            "properties"
        ]
    )
    assert declared <= columns, (
        f"memory response declares non-columns: {sorted(declared - columns)}"
    )


def test_the_approval_list_service_is_the_only_producer_of_the_queue_shape() -> None:
    """``ApprovalService.list_for_tenant`` returns (rows, truncated) — the model
    must carry BOTH or the queue loses its own completeness flag."""
    import inspect

    signature = inspect.signature(ApprovalService.list_for_tenant)
    page = _properties("/api/v1/ai/approvals", "get")
    assert {"items", "truncated"} <= set(page), page
    assert len(signature.parameters) >= 3, signature
