"""§82 — the segments surface: a typed response contract, and a DSL compiler
that binds exactly the parameters its generated SQL names.

Three things are pinned here. Two are defects, one is a claim that turned out to
be stale, and the difference between them is only established by running them.

1. **No route declares a response model.** Six routes answer with hand-built
   dicts, so the state a segment exists for — ``definition``, ``is_active``,
   ``last_count``, ``last_evaluated_at`` — is whatever the dict happened to
   carry today. A response model is the only place that claim becomes checkable:
   an untyped ``dict`` is the hole a field disappears into.

2. **``_compile_where`` binds a parameter the SQL never names** (suspected at
   ``segments/service.py:140``, the ``op == "in"`` branch). The deciding test
   uses the driver's own bookkeeping rather than an opinion: ``Compiled.positiontup``
   is the ordered list of values the asyncpg adapter sends as ``$1…$n``
   (``AsyncAdapt_asyncpg_cursor._prepare_and_execute`` calls
   ``prepared_stmt.fetch(*parameters)``), so a key of the params dict that is
   absent from it is a value the compiler believes it passed and the database
   never received. The verdict: a DEAD BINDING, not a 500 — which is exactly why
   the suspicion needed a test rather than a guess in either direction.

   Following the same branch does surface a case that fails for real:
   ``{"op": "in", "value": []}`` passes ``validate_dsl`` — which only requires
   that a value is present — and compiles to ``(... IN ())``, which PostgreSQL
   rejects as a syntax error. ``/segments/preview``'s own docstring promises an
   invalid definition "is rejected by the whitelist compiler as a
   ``ValidationError`` (HTTP 400), never a 500". The empty list is that
   forbidden 500, so the fix belongs in the validator.

3. **The GAP_REGISTER line about this module is stale, and is verified rather
   than repeated.** It says the ``segments`` migration was empty and the model is
   unregistered, so the table and its RLS policy may not exist. The first half is
   true of ``24037e2ebc05_segments_table.py`` (a generated stub whose
   ``upgrade()`` is ``pass``) and irrelevant since: ``b2c3d4e5f6a7`` creates the
   table in ``_segments_table()`` BEFORE its dynamic RLS loop runs, and
   ``app/core/model_registry.py`` imports ``Segment``. Both are pinned below
   DB-free; the database half (does the policy exist on a migrated schema?)
   needs ``DATABASE_URL_APP_ADMIN`` and is therefore CI-only — labelled as such,
   never claimed as watched.
"""

from __future__ import annotations

import pathlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.segments.router import _segment_dict
from app.modules.segments.router import router as segments_router
from app.modules.segments.service import (
    Segment,
    SegmentService,
    _compile_where,
    validate_dsl,
)

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
VERSIONS = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "versions"
HARDENING_MIGRATION = VERSIONS / "b2c3d4e5f6a7_hardening_rls_segments_worker_columns.py"
EMPTY_SEGMENTS_MIGRATION = VERSIONS / "24037e2ebc05_segments_table.py"

# Two rules on the SAME field (one an `in`, one a scalar) plus a `contains`, so
# the monotonic p0/p1/… minting and the per-item `_0`/`_1` suffixing are both
# exercised in one statement.
MIXED_RULE: dict[str, Any] = {
    "all": [
        {"field": "source", "op": "in", "value": ["instagram", "whatsapp"]},
        {"field": "source", "op": "eq", "value": "direct"},
        {"field": "orders_count", "op": "gt", "value": 3},
        {"field": "source", "op": "contains", "value": "insta"},
    ]
}

ALL_RULES = [
    pytest.param(MIXED_RULE, id="mixed"),
    pytest.param({"field": "source", "op": "in", "value": ["instagram"]}, id="single-in"),
    pytest.param({"field": "lifetime_value", "op": "gte", "value": 500}, id="scalar"),
    pytest.param(
        {"not": {"all": [{"field": "source", "op": "in", "value": ["a", "b", "c"]}]}},
        id="nested-in",
    ),
]


def _compiled(node: dict) -> tuple[str, dict, list]:
    """(SQL text, params dict, values the driver would actually be handed).

    ``construct_params`` + ``positiontup`` are what
    ``AsyncAdapt_asyncpg_cursor`` turns into ``prepared_stmt.fetch(*parameters)``,
    so the third element is the real wire, not a paraphrase of it.
    """
    params: dict = {"t": TENANT}
    where = _compile_where(node, params)
    sql = f"SELECT id FROM customers WHERE tenant_id = :t AND deleted_at IS NULL AND {where}"
    compiled = text(sql).compile(dialect=asyncpg.dialect())
    bound = compiled.construct_params(params)
    return sql, params, [bound[name] for name in compiled.positiontup]


def _named_binds(sql: str) -> set[str]:
    """Every ``:name`` the generated SQL actually references."""
    return set(re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", sql))


# ---------------------------------------------------------------------------
# 1. The suspected unreferenced bind — decided by the driver's bookkeeping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("node", ALL_RULES)
def test_every_bound_parameter_is_named_by_the_generated_sql(node: dict) -> None:
    """No parameter may be computed, bound, and then never sent.

    The ``in`` branch stored the whole list under the leaf's own key
    (``p1``) and then minted the per-item keys beside it (``p1_0``, ``p1_1``),
    so ``p1`` matched nothing in the SQL. asyncpg silently never sees it — the
    defect is a value the compiler believes it passed, and the next person to
    read ``params[key] = value`` as "this is where the leaf binds" can build on
    it.
    """
    sql, params, sent = _compiled(node)
    unreferenced = set(params) - _named_binds(sql)

    assert not unreferenced, (
        f"bound parameters the SQL never references: {sorted(unreferenced)} — "
        f"they are dropped before the driver call. SQL: {sql}"
    )
    assert len(sent) == len(params), f"{len(sent)} values sent for {len(params)} bound"


@pytest.mark.parametrize("node", ALL_RULES)
def test_an_in_list_reaches_sql_as_one_bind_per_element(node: dict) -> None:
    """The database compares scalars; a list may never be a single bind value.

    ``asyncpg`` has no list-to-``IN`` adaptation for a bare ``text()`` bind, so
    the per-item keys are the only way a rule value can arrive. GREEN ON ARRIVAL
    by design — it is the guard that the whole-list binding really is dead, so
    removing it cannot change which customers a rule matches, and the assertion
    that fails is the one above, not this one.
    """
    _sql, _params, sent = _compiled(node)

    assert not any(isinstance(value, list) for value in sent), (
        f"a rule value list reached the driver as one bind: {sent}"
    )


# ---------------------------------------------------------------------------
# 2. The empty `in` list: the 500 this module's docstring already forbids
# ---------------------------------------------------------------------------


def test_an_empty_in_list_is_rejected_by_the_whitelist_validator() -> None:
    """§82: a bad definition is a 400 from the compiler, never a database error.

    ``validate_dsl`` checked that a condition carries a value, never that an
    ``in`` has something in it, so ``[]`` travelled to Postgres as ``IN ()``.
    """
    with pytest.raises(ValidationError):
        validate_dsl({"all": [{"field": "source", "op": "in", "value": []}]})


def test_an_empty_in_list_never_compiles_to_unusable_sql() -> None:
    """Defense in depth: the compiler must not emit ``IN ()`` even if called
    directly (every service path validates first, but ``_compile_where`` is
    imported by name in three test files, so it is not a private helper)."""
    with pytest.raises(ValidationError):
        _compile_where({"field": "source", "op": "in", "value": []}, {})


class _EmptyResult:
    def scalars(self) -> _EmptyResult:
        return self

    def all(self) -> list:
        return []


class _RecordingSession:
    """Answers every query with "no rows" and records what it was asked.

    A stub that fails loudly would hide the real symptom: today the route
    ANSWERS 200 with `count: 0`, and the same definition is a syntax error
    against a real PostgreSQL. Recording the statements is what proves the
    un-compilable SQL was actually sent.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement, params=None):  # noqa: ANN001
        self.statements.append(str(statement))
        return _EmptyResult()

    async def flush(self) -> None:
        return None


def _segments_only_app() -> FastAPI:
    """The routes, mounted as ``app/main.py`` mounts them, for schema walking.

    Deliberately NOT ``create_app()`` here: an OpenAPI walk of six routes should
    not depend on seventeen modules importing cleanly. ``/api/v1`` is the prefix
    ``main.py`` uses, so the paths below are the paths a client calls.
    """
    app = FastAPI()
    app.include_router(segments_router, prefix="/api/v1")
    return app


def _client(session: Any, tenant_id: uuid.UUID = TENANT) -> Any:
    """A request-bound app, for behaviour that is the APP'S contract.

    The 400 body and its ``error.code`` are produced by ``main.py``'s
    ``DomainError`` handler, so this half has to run the real app; the schema
    walk above does not.

    ``tenant_id`` defaults to the module's synthetic ``TENANT`` because every
    caller but one is DB-free and only ever reads the response. The exception
    passes ``tenant_ctx``'s REAL tenant: the fake context's ``tenant_id`` is
    what the service writes into ``segments.tenant_id``, and that column is
    FK-checked against ``tenants`` — so a made-up uuid can only 500.
    """
    ctx = TenantContext(
        session=session,
        user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="owner"),
        tenant_id=tenant_id,
        role_code="owner",
        permission_codes={"marketing:write"},
    )

    app = create_app()

    async def _fake_ctx() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _fake_ctx
    return app


async def test_preview_rejects_an_empty_in_list_before_touching_sql() -> None:
    """The promise ``/segments/preview`` makes, tested at its own boundary.

    Before the fix this route answered 200 ``{"count": 0}`` against a stub — and
    against PostgreSQL the same definition raised a syntax error, so the two
    halves of one defect: an invalid definition neither rejected nor reported.
    """
    session = _RecordingSession()
    transport = ASGITransport(app=_client(session))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/segments/preview",
            json={"definition": {"all": [{"field": "source", "op": "in", "value": []}]}},
        )

    assert response.status_code == 400, (
        f"an empty `in` list must be a 400 from the whitelist compiler, got "
        f"{response.status_code}: {response.text[:300]}"
    )
    assert not [s for s in session.statements if "FROM customers" in s], (
        f"the un-compilable `IN ()` query was sent to the database: {session.statements}"
    )
    assert response.json()["error"]["code"] == "validation_error", response.text


# ---------------------------------------------------------------------------
# 3. Typed responses for the six routes
# ---------------------------------------------------------------------------


def _resolve(document: dict, node: dict) -> dict:
    """Follow ``$ref`` / array-of-object shapes to the object schema itself."""
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


def _response_properties(path: str, method: str) -> dict:
    document = _segments_only_app().openapi()
    entry = document["paths"][path][method.lower()]
    statuses = [s for s in entry["responses"] if s.startswith("2") and s != "204"]
    assert statuses, f"{method.upper()} {path} declares no 2xx body"
    schema = entry["responses"][statuses[0]]["content"]["application/json"]["schema"]
    return _resolve(document, schema).get("properties") or {}


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/segments", "get"),
        ("/api/v1/segments", "post"),
        ("/api/v1/segments/preview", "post"),
        ("/api/v1/segments/{segment_id}", "get"),
        ("/api/v1/segments/{segment_id}", "put"),
        ("/api/v1/segments/{segment_id}", "delete"),
    ],
)
def test_each_segment_route_declares_a_typed_response(path: str, method: str) -> None:
    """No route may answer with an open object.

    A schema with no ``properties`` is the OpenAPI spelling of "any key may
    appear, any key may be missing" — the hand-built dict, just documented.
    """
    properties = _response_properties(path, method)
    assert properties, (
        f"{method.upper()} {path} answers with an untyped object, so the "
        "segment's state can be dropped without anything noticing"
    )


def _segment_row() -> Segment:
    segment = Segment(
        tenant_id=TENANT,
        name="High value",
        definition={"all": [{"field": "orders_count", "op": "gt", "value": 3}]},
    )
    segment.id = uuid.uuid4()
    segment.is_active = True
    segment.last_count = 12
    segment.last_evaluated_at = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
    segment.created_at = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    return segment


def test_the_segment_response_types_every_field_the_handler_builds() -> None:
    """Whatever the handler assembles must be declared, or it is dropped.

    ``_segment_dict`` is the single place the shape is built, so comparing its
    keys against the declared properties is a real check: add a field to one and
    forget the other and this fails.
    """
    keys = set(_segment_dict(_segment_row()))
    properties = _response_properties("/api/v1/segments/{segment_id}", "get")

    missing = keys - set(properties)
    assert not missing, f"fields the handler builds but the response type omits: {missing}"
    extra = set(properties) - keys
    assert not extra, f"fields the response type promises the handler never builds: {extra}"


def test_segment_state_is_typed_and_keeps_its_nullability() -> None:
    """``last_count``/``last_evaluated_at`` are nullable BY DESIGN.

    A segment that has never been evaluated must answer ``null``, not a silent
    ``0`` — the difference between "the recompute has not run" and "it ran and
    matched nobody", which is exactly what §82's job runner has to be able to
    tell. ``definition`` stays an object: it is the DSL AST, arbitrary JSON by
    contract, and the one place a bare dict is the honest type.
    """
    properties = _response_properties("/api/v1/segments/{segment_id}", "get")

    for field in ("definition", "is_active", "last_count", "last_evaluated_at", "created_at"):
        assert field in properties, f"{field} is absent from the typed segment response"

    assert properties["definition"].get("type") == "object", properties["definition"]
    for field in ("last_count", "last_evaluated_at"):
        types = {
            s.get("type")
            for s in properties[field].get("anyOf", [properties[field]])
            if isinstance(s, dict)
        }
        assert None in types or "null" in types, f"{field} is typed NOT NULL: {properties[field]}"


def test_the_preview_response_is_typed_as_a_count_and_a_sample_of_ids() -> None:
    properties = _response_properties("/api/v1/segments/preview", "post")

    assert set(properties) >= {"count", "sample"}, properties
    assert properties["count"]["type"] == "integer", properties["count"]
    items = properties["sample"].get("items", {})
    assert items.get("type") == "string", (
        f"a customer id must leave as a string, not a raw UUID object: {items}"
    )


def test_the_archive_response_keeps_the_flag_it_exists_to_set() -> None:
    """Archive is a soft delete: the body says the row is now inactive."""
    properties = _response_properties("/api/v1/segments/{segment_id}", "delete")

    assert set(properties) >= {"id", "is_active", "archived"}, properties


# ---------------------------------------------------------------------------
# 4. The stale register line, verified against the tree rather than repeated
# ---------------------------------------------------------------------------


def test_segments_table_is_registered_created_and_rls_swept() -> None:
    """GAP_REGISTER O2's claim, checked three ways. Two of the three are stale.

    * the model IS in the registry, so ``Base.metadata`` knows the table;
    * the table IS created, by ``b2c3d4e5f6a7._segments_table()``, which runs
      BEFORE that migration's dynamic RLS loop — the loop enumerates every
      ``public`` table with a ``tenant_id`` column, so ordering is the whole
      difference between "has a policy" and "has none";
    * the migration the register line names IS still an empty stub — which is
      the reason the later one exists, and no longer a missing table.
    """
    from app.core.model_registry import Base  # registers every module's models

    assert "segments" in Base.metadata.tables, (
        "Segment is not registered: no metadata means provision.py's RLS sweep "
        "never sees the table, which is the gap the register line described"
    )
    table = Base.metadata.tables["segments"]
    assert {"tenant_id", "definition", "last_count", "last_evaluated_at"} <= set(
        table.columns.keys()
    )

    source = HARDENING_MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "_segments_table()" in upgrade_body, "the hardening migration no longer creates segments"
    assert upgrade_body.index("_segments_table()") < upgrade_body.index("_rls_do_block()"), (
        "segments is now created AFTER the RLS sweep, so a migrated database has "
        "the table with no tenant_isolation policy"
    )

    stub = EMPTY_SEGMENTS_MIGRATION.read_text(encoding="utf-8")
    stub_body = stub.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert re.search(r"^\s+pass\s*$", stub_body, re.MULTILINE), (
        "24037e2ebc05 is no longer an empty stub — either the table was created "
        "twice or the register line needs rewriting; check both"
    )


def test_the_dsl_compiler_never_interpolates_a_value_into_sql_text() -> None:
    """The whitelist is the injection defence, so the defence stays structural.

    Passes on arrival — it is the tripwire, not the proof: ``/preview`` accepts
    ``definition`` from a browser, and the one property that makes that safe is
    that a rule value is only ever BOUND.
    """
    hostile = {
        "all": [
            {"field": "source", "op": "eq", "value": "x'); DROP TABLE customers; --"},
            {"field": "source", "op": "in", "value": ["1=1", "2=2"]},
        ]
    }
    sql, params, sent = _compiled(hostile)

    for value in params.values():
        if isinstance(value, str):
            assert value not in sql, f"a rule value was interpolated into SQL text: {value}"
    assert "DROP TABLE" not in sql
    assert sent.count("1=1") == 1 and sent.count("2=2") == 1


# ---------------------------------------------------------------------------
# 5. CI-only: the database half (skips without DATABASE_URL_APP_ADMIN)
# ---------------------------------------------------------------------------


async def test_segments_table_carries_force_rls_and_a_policy(db: AsyncSession) -> None:
    """``relrowsecurity``/``relforcerowsecurity`` + ``tenant_isolation``, from pg_class.

    CI-only: without ``DATABASE_URL_APP_ADMIN`` the ``db`` fixture skips, so this
    verdict is published by CI and nowhere else. The DB-free test above proves
    the migration ORDER; this one proves the RESULT.
    """
    import sqlalchemy as sa

    flags = (
        await db.execute(
            sa.text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'segments' AND relnamespace = "
                "(SELECT oid FROM pg_namespace WHERE nspname = 'public')"
            )
        )
    ).one()
    assert flags.relrowsecurity is True, "segments is not RLS-enabled"
    assert flags.relforcerowsecurity is True, "segments is not RLS-forced"

    policies = (
        await db.execute(
            sa.text(
                "SELECT count(*) FROM pg_policies WHERE tablename = 'segments' "
                "AND policyname = 'tenant_isolation'"
            )
        )
    ).scalar_one()
    assert policies == 1, f"expected one tenant_isolation policy on segments, got {policies}"


async def test_an_in_rule_selects_exactly_the_matching_customers(
    db: AsyncSession, tenant_ctx
) -> None:
    """End-to-end proof that the per-item binds are the ones that decide.

    Two customers, blocked and not. ``is_blocked IN (false)`` must return only
    the unblocked one, and ``IN (false, true)`` both — so dropping the dead
    whole-list binding removes noise, never a match.
    """
    from app.modules.customers.models import Customer

    blocked = Customer(
        tenant_id=tenant_ctx.tenant_id, name="Blocked", is_blocked=True, email="b@example.test"
    )
    open_customer = Customer(
        tenant_id=tenant_ctx.tenant_id, name="Open", is_blocked=False, email="o@example.test"
    )
    db.add_all([blocked, open_customer])
    await db.flush()

    only_open = Segment(
        tenant_id=tenant_ctx.tenant_id,
        name="not blocked",
        definition={"all": [{"field": "is_blocked", "op": "in", "value": [False]}]},
    )
    matched = await SegmentService.evaluate(db, tenant_ctx.tenant_id, only_open)
    assert matched == [open_customer.id], matched
    assert only_open.last_count == 1

    both = Segment(
        tenant_id=tenant_ctx.tenant_id,
        name="either",
        definition={"all": [{"field": "is_blocked", "op": "in", "value": [False, True]}]},
    )
    matched_both = await SegmentService.evaluate(db, tenant_ctx.tenant_id, both)
    assert set(matched_both) == {blocked.id, open_customer.id}, matched_both


async def test_the_http_surface_round_trips_a_typed_segment(
    db: AsyncSession, tenant_ctx
) -> None:
    """Create → read back: every declared field arrives, none renamed away.

    CI-only. This is the case that catches a response model typing the right
    NAMES with the wrong nullability, which no OpenAPI walk can see.
    """
    # The real get_tenant_ctx verifies membership AND binds the RLS GUC; the
    # fake in `_client` replaces it wholesale, so this test binds the GUC to the
    # tenant the fake context claims — and claims `tenant_ctx`'s REAL tenant row
    # rather than the module's synthetic `TENANT`. Two separate refusals sit
    # behind that: with no bind at all CI's `sales_app` role rejects the POST's
    # INSERT INTO segments as a row-level security violation, and with a
    # synthetic bind the RLS check passes and the statement dies one step later
    # on `fk_segments_tenant_id_tenants` — 'DETAIL: Key is not present in table
    # "tenants"' (run on c85e130).
    from app.core.db import bind_tenant

    await bind_tenant(db, tenant_ctx.tenant_id)
    transport = ASGITransport(app=_client(db, tenant_ctx.tenant_id))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/segments",
            json={
                "name": "VIP",
                "definition": {"all": [{"field": "orders_count", "op": "gt", "value": 3}]},
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["is_active"] is True
        assert body["last_count"] is None, "an un-evaluated segment must not report a count"
        assert body["definition"]["all"][0]["field"] == "orders_count"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.+]*", body["created_at"]), body["created_at"]

        fetched = await client.get(f"/api/v1/segments/{body['id']}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json() == body

        listed = await client.get("/api/v1/segments")
        assert [s["id"] for s in listed.json()] == [body["id"]]


def test_no_segment_route_answers_without_a_declared_model() -> None:
    """The same claim as the OpenAPI walk, asserted where it is authored.

    ``route.response_model`` is the declaration; the OpenAPI document is the
    consequence. Both are checked because a route can carry a model and still
    publish an untyped body if the model is ``dict``.
    """
    untyped = sorted(
        f"{sorted(route.methods)} {route.path}"
        for route in segments_router.routes
        if isinstance(route, APIRoute)
        and route.status_code != 204
        and (
            route.response_model in (None, dict)
            or getattr(route.response_model, "model_fields", None) == {}
        )
    )
    assert not untyped, (
        "routes still answering through an untyped body:\n  " + "\n  ".join(untyped)
    )
