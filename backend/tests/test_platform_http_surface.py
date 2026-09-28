"""The ``platform`` module's HTTP surface: typed responses, bounded paging, stable sorts.

Three measured gaps from ``docs/GAP_REGISTER.md`` line P8 ("~45 of 62 routes
untyped (no response_model) → OpenAPI useless") and line P7 ("two sort keys
between page 1 and page N; negative/unbounded ``limit/offset``"):

1. ZERO of the 29 platform routes declared a ``response_model``, so the OpenAPI
   document described an empty ``{}`` schema for every one of them — a client
   generator produced a contract with no fields in it.
2. Paging knobs were refused only where they happened to be bounded.
   ``GET /platform/webhook-events`` clamps ``limit``/``offset``; the three other
   list routes had no knob at all, so ``?limit=-1`` (SQL ``LIMIT -1`` = every
   row) and ``?offset=-1`` were not *rejected*, they were silently IGNORED —
   which is worse than a 500: the caller believes it asked for page 2 and
   receives page 1 again, forever.
3. The list routes sorted on a key that is not a total order
   (``saved_views.name`` has no unique constraint, ``tenants.created_at`` has
   no tie-break), so rows repeat or vanish between page 1 and page N.

Every case here is DB-free except the last two, which need real PostgreSQL and
skip locally (``ENVIRONMENT=local`` without ``DATABASE_URL_APP_ADMIN``); CI runs
them. The route-driven cases reuse the fake-session pattern from
``tests/test_contract_reachability.py``: the real app, a fabricated
``TenantContext``, and a session that RECORDS the statements it was sent — which
is what lets these tests say "the bad parameter never reached the database"
rather than merely "the response looked fine".
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
from app.modules.platform.models import FeatureFlag, SavedView, WebhookEvent
from app.modules.platform.router import router as platform_router

API = "/api/v1/platform"
TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")

#: The measured size of the module's HTTP surface. A route added or removed
#: here changes the gap-register claim P8 is written against, so it must be an
#: explicit edit rather than a silent drift.
PLATFORM_ROUTE_COUNT = 31


# --------------------------------------------------------------------------- harness


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0] if self._rows else 0

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _RecordingSession:
    """Inert session that keeps every statement it was handed.

    ``statements`` is what the "never reached the database" assertions read:
    a rejected query parameter must produce ZERO statements, not an error page
    after the row set has already been pulled.

    A ``COUNT`` is answered with ``0`` rather than the row set, because
    ``int()`` of an ORM row is a TypeError and the fake must not fail for a
    reason unrelated to the assertion under test.
    """

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.statements: list[Any] = []
        self.added: list[Any] = []

    async def execute(self, stmt: Any, *_args: Any, **_kwargs: Any) -> _Result:
        self.statements.append(stmt)
        if "count(" in str(stmt.compile()).lower():
            return _Result([])
        return _Result(self._rows)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None

    async def delete(self, _instance: Any) -> None:
        return None


def _platform_routes() -> list[Any]:
    return [r for r in platform_router.routes if getattr(r, "methods", None)]


def _app_for(
    rows: list[Any],
    *,
    permissions: set[str] | None = None,
    platform_admin: bool = False,
):
    """The real app with auth + session swapped; nothing else is stubbed."""
    session = _RecordingSession(rows)
    user = AuthedUser(
        id=USER, tenant_id=TENANT, role_code="owner", is_platform_admin=platform_admin
    )
    ctx = TenantContext(
        session=session,
        user=user,
        tenant_id=TENANT,
        role_code="owner",
        permission_codes=set(permissions or ()),
    )
    app = create_app()

    async def _session() -> Any:
        yield session

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _session
    return app, session


async def _call(
    method: str,
    path: str,
    rows: list[Any],
    *,
    permissions: set[str] | None = None,
    platform_admin: bool = False,
    params: dict[str, Any] | None = None,
    body: Any = None,
):
    app, session = _app_for(rows, permissions=permissions, platform_admin=platform_admin)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=10) as client:
        response = await client.request(method, path, params=params, json=body)
    return response, session


def _order_by(sql: str) -> str:
    parts = sql.split("ORDER BY", 1)
    assert len(parts) == 2, f"statement has no ORDER BY: {sql}"
    tail = parts[1]
    for stop in (" LIMIT", " OFFSET"):
        tail = tail.split(stop, 1)[0]
    return tail


def _sql_with(session: _RecordingSession, needle: str) -> str:
    """The compiled SQL of the one statement mentioning ``needle``."""
    hits = [str(stmt.compile()) for stmt in session.statements]
    rows_sql = [sql for sql in hits if needle in sql]
    assert rows_sql, f"no statement mentions {needle!r} in {hits}"
    return rows_sql[-1]


def _saved_view(**overrides: Any) -> SavedView:
    values: dict[str, Any] = {
        # a real row always arrives with its primary key; an unflushed ORM object
        # has id=None and the serializer would emit the string "None", which is a
        # fixture artifact and not a contract the response model should model.
        "id": uuid.uuid4(),
        "tenant_id": TENANT,
        "name": "My view",
        "entity": "customers",
        "definition": {"filters": []},
        "visibility": "private",
        "owner_user_id": USER,
    }
    values.update(overrides)
    return SavedView(**values)


def _webhook_event(**overrides: Any) -> WebhookEvent:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "provider": "whatsapp",
        "external_event_id": "ext-1",
        "tenant_id": TENANT,
        "signature_valid": True,
        "payload": {"entry": []},
        "processing_status": "failed",
        "attempts": 3,
        "last_error": "boom",
    }
    values.update(overrides)
    return WebhookEvent(**values)


# --------------------------------------------------------------------------- 1. types
#
# P8: a route without a response_model contributes `"schema": {}` to the
# document, which is OpenAPI for "anything". The whole point of publishing the
# schema is lost, so both halves are pinned: the declaration on the route and a
# real, field-level schema in the rendered document.


def test_the_platform_surface_is_the_measured_routes() -> None:
    assert len(_platform_routes()) == PLATFORM_ROUTE_COUNT


def test_every_platform_route_declares_a_response_model() -> None:
    missing = sorted(
        f"{sorted(route.methods)} {route.path}" for route in _platform_routes()
        if route.response_model is None
    )
    assert not missing, (
        f"{len(missing)} of {PLATFORM_ROUTE_COUNT} platform routes publish no "
        "response_model, so OpenAPI describes nothing real for them (P8):\n"
        + "\n".join(f"  {entry}" for entry in missing)
    )


def test_every_platform_response_schema_documents_its_fields() -> None:
    """Not merely "a model is attached" — the DOCUMENT must carry the fields.

    ``response_model=dict`` would satisfy the declaration test while leaving the
    contract as empty as no model at all, so this reads the rendered schema and
    requires named properties on every 2xx response of the module.
    """
    document = create_app().openapi()
    components = document.get("components", {}).get("schemas", {})

    def resolve(schema: dict) -> dict:
        seen: set[str] = set()
        while "$ref" in schema:
            name = schema["$ref"].rsplit("/", 1)[-1]
            assert name not in seen, f"cyclic $ref {name}"
            seen.add(name)
            schema = components[name]
        return schema

    untyped: list[str] = []
    for path, operations in document["paths"].items():
        if not path.startswith(API):
            continue
        for method, operation in operations.items():
            for code, response in operation.get("responses", {}).items():
                if not code.startswith("2"):
                    continue
                schema = (response.get("content") or {}).get("application/json", {}).get("schema")
                if schema is None:
                    untyped.append(f"{method.upper()} {path} -> {code}: no schema")
                    continue
                body = resolve(schema)
                if body.get("type") == "array":
                    body = resolve(body.get("items") or {})
                if not body.get("properties"):
                    untyped.append(
                        f"{method.upper()} {path} -> {code}: free-form object "
                        f"(properties={sorted(body.get('properties', {}))})"
                    )
    assert not untyped, "these platform responses are documented as nothing in particular:\n" + (
        "\n".join(f"  {line}" for line in untyped)
    )


async def test_a_response_model_that_lies_about_the_wire_shape_is_caught() -> None:
    """The model must describe what the handler SENDS, not what we wish.

    Driven end to end for the richest rows: every key the route emits has to
    survive validation (a response_model silently DROPS undeclared fields, which
    is how a declared model can be worse than none at all).
    """
    response, _ = await _call(
        "GET",
        f"{API}/webhook-events",
        [_webhook_event()],
        permissions=set(),
        platform_admin=True,
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["provider"] == "whatsapp"
    assert item["last_error"] == "boom"
    assert item["attempts"] == 3
    assert item["processing_status"] == "failed"


# ----------------------------------------------------------------------- 2. envelope
#
# Three list envelopes exist in this codebase (P8). ``platform`` already speaks
# `{items: [...]}` on five of its seven list routes (saved-views,
# metrics/definitions, admin/tenants, webhook-events, security-events), so THAT
# is the module shape; the two bare arrays are the outliers. The frontend reads
# only `/platform/saved-views` (``{items}``) and `/platform/health`, so nothing
# on the client breaks — see the mission note in the module docstring.


async def test_flags_list_uses_the_module_envelope() -> None:
    row = FeatureFlag(
        tenant_id=TENANT, feature="voice.enabled", enabled=True, rollout_percent=100
    )
    response, _ = await _call("GET", f"{API}/flags", [row], permissions=set())

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {
                "feature": "voice.enabled",
                "enabled": True,
                "workspace_id": None,
                "role_code": None,
                "rollout_percent": 100,
            }
        ]
    }, "GET /platform/flags must answer with the module's {items} envelope"


async def test_metric_registry_list_uses_the_module_envelope() -> None:
    response, _ = await _call("GET", f"{API}/metrics", [], permissions=set())

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items"}, "GET /platform/metrics must answer with {items}"
    assert all({"name", "definition", "version"} <= set(entry) for entry in body["items"])
    assert body["items"], "the registry payload must still reach the client"


# ---------------------------------------------------------------------- 3. paging
#
# The four list routes that take a page. Each knob is refused at the edge — a
# 422 with ZERO statements sent — rather than reaching SQL, where ``LIMIT -1``
# means "no limit" and ``OFFSET -1`` is an error.


#: (path, rows to answer the fake read with, permissions, platform-admin?)
_PAGED_LISTS: list[tuple[str, list[Any], set[str], bool]] = [
    (f"{API}/webhook-events", [_webhook_event()], set(), True),
    (f"{API}/saved-views", [_saved_view()], set(), False),
    (f"{API}/security-events", [], {"settings:read"}, False),
    (f"{API}/admin/tenants", [], set(), True),
]

_BAD_PAGES = [
    {"limit": -1},  # SQL LIMIT -1 == every row in the table
    {"limit": 0},
    {"limit": 100000},  # the unbounded dump knob
    {"offset": -1},
]


@pytest.mark.parametrize("query", _BAD_PAGES, ids=lambda q: f"{list(q)[0]}={list(q.values())[0]}")
@pytest.mark.parametrize(
    ("path", "rows", "permissions", "platform_admin"),
    _PAGED_LISTS,
    ids=["webhook-events", "saved-views", "security-events", "admin-tenants"],
)
async def test_a_paged_list_refuses_an_out_of_range_page_without_touching_the_db(
    path: str, rows: list[Any], permissions: set[str], platform_admin: bool, query: dict
) -> None:
    response, session = await _call(
        "GET", path, rows, permissions=permissions, platform_admin=platform_admin, params=query
    )

    assert response.status_code == 422, (
        f"{path}?{query} answered {response.status_code}; an out-of-range page must be "
        "refused at the edge — a negative limit is `LIMIT -1` (every row) and a "
        "negative offset is a database error"
    )
    assert session.statements == [], (
        f"{path}?{query} was refused but the query still ran: {len(session.statements)} "
        "statement(s) reached the database"
    )


async def test_a_valid_page_is_echoed_back_with_the_total() -> None:
    """The caller must be able to tell a short page from a truncated one."""
    response, _ = await _call(
        "GET",
        f"{API}/webhook-events",
        [_webhook_event()],
        permissions=set(),
        platform_admin=True,
        params={"limit": 7, "offset": 3},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["limit"] == 7 and body["offset"] == 3
    assert isinstance(body["total"], int)


@pytest.mark.parametrize(
    ("path", "rows", "table", "permissions", "platform_admin"),
    [
        (f"{API}/saved-views", [_saved_view()], "saved_views", set(), False),
        (f"{API}/security-events", [], "security_events", {"settings:read"}, False),
        (f"{API}/admin/tenants", [], "tenants", set(), True),
        (f"{API}/webhook-events", [_webhook_event()], "webhook_events", set(), True),
    ],
    ids=["saved-views", "security-events", "admin-tenants", "webhook-events"],
)
async def test_a_paged_list_sorts_on_a_total_order(
    path: str,
    rows: list[Any],
    table: str,
    permissions: set[str],
    platform_admin: bool,
) -> None:
    """ORDER BY must end in a unique column or pages overlap and drop rows.

    ``saved_views.name`` is not unique (no constraint on it) and
    ``tenants.created_at`` carries no tie-break, so PostgreSQL is free to return
    tied rows in a different order on every read: row 3 on page 1 becomes row 3
    on page 2 as well, and whatever moved past the boundary is never seen again.
    """
    _response, session = await _call(
        "GET",
        path,
        rows,
        permissions=permissions,
        platform_admin=platform_admin,
        params={"limit": 10, "offset": 0},
    )

    order_by = _order_by(_sql_with(session, table))
    assert f"{table}.id" in order_by, (
        f"{path} pages on a sort that is not a total order — ORDER BY {order_by.strip()} "
        f"has no unique tie-break, so rows repeat or vanish between page 1 and page N"
    )


@pytest.mark.parametrize(
    ("path", "table", "permissions", "platform_admin"),
    [
        (f"{API}/saved-views", "saved_views", set(), False),
        (f"{API}/security-events", "security_events", {"settings:read"}, False),
        (f"{API}/admin/tenants", "tenants", set(), True),
    ],
    ids=["saved-views", "security-events", "admin-tenants"],
)
async def test_a_paged_list_sends_the_offset_it_was_given(
    path: str, table: str, permissions: set[str], platform_admin: bool
) -> None:
    """An ignored ``offset`` is worse than a 500: page 2 silently IS page 1."""
    _response, session = await _call(
        "GET", path, [], permissions=permissions, platform_admin=platform_admin,
        params={"limit": 10, "offset": 25},
    )

    rows_sql = _sql_with(session, table)
    assert "OFFSET" in rows_sql.upper(), (
        f"{path} accepted offset=25 and never sent it: {rows_sql}"
    )


# ------------------------------------------------------- CI-only: real PostgreSQL
#
# The defect is a database behaviour (tied ORDER BY), so the only *proof* is
# pages over rows that genuinely tie. These need DATABASE_URL_APP_ADMIN and skip
# locally; CI runs them.


async def _rows_for(db, tenant_id: uuid.UUID, path: str, params: dict) -> list[dict]:
    app = create_app()
    user = AuthedUser(
        id=USER, tenant_id=tenant_id, role_code="owner", is_platform_admin=True
    )

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=user,
            tenant_id=tenant_id,
            role_code="owner",
            permission_codes={"settings:read", "settings:write"},
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=20
    ) as client:
        response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def test_pages_over_tied_sort_keys_show_every_row_exactly_once(db, tenant_ctx) -> None:
    """Five same-named views, pages of two: the union must be those five rows.

    This is P7's "two sort keys between page 1 and page N" as an executable
    statement. With ``ORDER BY name`` alone the tied rows have no defined order,
    so pages overlap (a row appears twice) and the row pushed past the boundary
    never appears at all.
    """
    for _ in range(5):
        db.add(
            SavedView(
                tenant_id=tenant_ctx.tenant_id,
                name="Identical",
                entity="customers",
                definition={},
                visibility="team",
                owner_user_id=tenant_ctx.user.id,
            )
        )
    await db.flush()

    seen: list[str] = []
    for offset in (0, 2, 4):
        page = await _rows_for(
            db, tenant_ctx.tenant_id, f"{API}/saved-views", {"limit": 2, "offset": offset}
        )
        seen.extend(item["id"] for item in page)

    assert len(set(seen)) == len(seen) == 5, (
        f"three pages of two over five tied rows must show each row exactly once, saw {seen}"
    )


async def test_total_reports_the_filtered_size_not_the_page_size(db, tenant_ctx) -> None:
    """``total`` is what tells a client the list was truncated at the page cap."""
    for index in range(3):
        db.add(
            SavedView(
                tenant_id=tenant_ctx.tenant_id,
                name=f"View {index}",
                entity="orders",
                definition={},
                visibility="team",
                owner_user_id=tenant_ctx.user.id,
            )
        )
    await db.flush()

    app = create_app()
    user = AuthedUser(id=USER, tenant_id=tenant_ctx.tenant_id, role_code="owner")

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=user,
            tenant_id=tenant_ctx.tenant_id,
            role_code="owner",
            permission_codes={"settings:read", "settings:write"},
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=20
    ) as client:
        response = await client.get(f"{API}/saved-views", params={"limit": 2, "entity": "orders"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
