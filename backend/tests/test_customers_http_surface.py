"""The ``customers`` module's HTTP surface: typed responses, ONE sort key, gates.

Three measured gaps from ``docs/GAP_REGISTER.md``:

* **P8** — "~45 of 62 routes untyped (no ``response_model``)". Every one of the
  19 routes in ``app/modules/customers/router.py`` is in that set: ZERO declared
  ``response_model``, so the OpenAPI document describes an empty ``{}`` for the
  whole CRM surface and a generated client produces a contract with no fields.
  Money sits inside that hole: ``lifetime_value`` and the 360's order/payment
  aggregates are ``Decimal`` in Python and must leave as the exact string
  ``str(Decimal)`` (ADR-053/§47 — see ``tests/test_customer_money_wire.py``). An
  untyped route cannot express that, and a lazily-typed ``float`` field would
  quietly break it at the serialization boundary.
* **P7** — "two sort keys between page 1 and page N (customers, conversations)".
  ``CustomerService.list_customers`` ordered the uncursed page by
  ``(created_at DESC, name ASC)`` and every cursor page by
  ``(created_at DESC, id DESC)``. The cursor itself is a ``(created_at, id)``
  position (``core/pagination.py``), so page 2's ``WHERE (created_at, id) < …``
  predicate is a comparison against a row selected under a different ordering:
  tied rows re-appear or are skipped. Here it is pinned twice — the ORDER BY of
  both pages is read off the statements the code actually sent (DB-free), and a
  real two-page walk over five rows that genuinely tie runs on PostgreSQL (CI).
* **P4** — "RBAC patchy vs seeded matrix: … customers read … ungated". The five
  customer READ routes resolved tenancy (``TenantCtxDep``) and checked no
  permission, while every write in the same file required ``customers:write``.
  The matrix ``scripts/provision.py`` seeds ``customers:read`` as a distinct
  grant, so a token without it must be refused by the API and not by the UI.

Method: DB-free wherever the claim is structural, reusing the harness patterns
of ``tests/test_platform_http_surface.py`` (real app, fabricated
``TenantContext``, a session that RECORDS its statements) and
``tests/test_customers_if_match.py`` (service seams monkeypatched so the route,
the dependency chain and the response serialization are all the production
ones). The one case that measures the defect instead of its shape — pages over
rows that really tie — needs ``DATABASE_URL_APP_ADMIN`` and skips locally.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.customers.models import Address, Customer, CustomerIdentity, Note, Tag
from app.modules.customers.router import platform_router
from app.modules.customers.router import router as customers_router
from app.modules.customers.service import CustomerService
from app.modules.customers.timeline import Customer360Service
from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER = uuid.UUID("22222222-2222-2222-2222-222222222222")
CUSTOMER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
BASE = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

#: NUMERIC(14,2) at the top of its range — the cent a float64 cannot hold, which
#: is exactly what a `float`-typed response field would destroy.
LTV = Decimal("999999999999.99")

#: The measured size of the module's HTTP surface: 15 routes on the customers
#: router plus the 4 platform routes that live in the same file. A route added
#: here changes the gap-register claim P8 is written against, so it must be an
#: explicit edit rather than a silent drift.
CUSTOMERS_ROUTE_COUNT = 15
PLATFORM_ROUTE_COUNT = 4

#: Routes that answer 204 and therefore have NO body to type. Enumerated by
#: path+method rather than filtered by status code, so a new 204 has to be
#: declared here on purpose.
NO_BODY_ROUTES: frozenset[str] = frozenset(
    {
        "DELETE /customers/{customer_id}/tags/{tag_name}",
        "DELETE /invitations/{invitation_id}",
    }
)

#: P4, read off ``scripts/provision.py``'s ROLE_MATRIX: ``customers:read`` and
#: ``customers:write`` are separate grants, and the settings screen is a
#: ``settings:*`` surface. Every route in the module maps to exactly one code.
GATED_READS: dict[str, str] = {
    "GET /customers": "customers:read",
    "GET /customers/{customer_id}": "customers:read",
    "GET /customers/{customer_id}/360": "customers:read",
    "GET /customers/{customer_id}/tags": "customers:read",
    "GET /customers/{customer_id}/notes": "customers:read",
    "GET /integrations": "settings:read",
}
GATED_WRITES: dict[str, str] = {
    "POST /customers/merge": "customers:write",
    "POST /customers/{customer_id}/block": "customers:write",
    "POST /customers/{customer_id}/unblock": "customers:write",
    "POST /customers/{customer_id}/archive": "customers:write",
    "PATCH /customers/{customer_id}": "customers:write",
    "POST /customers/{customer_id}/tags": "customers:write",
    "DELETE /customers/{customer_id}/tags/{tag_name}": "customers:write",
    "POST /customers/{customer_id}/notes": "customers:write",
    "GET /customers/contact-data-issues": "customers:write",
    "POST /customers/{customer_id}/contact-issue/resolve": "customers:write",
    "POST /integrations": "settings:write",
    "GET /invitations": "settings:write",
    "DELETE /invitations/{invitation_id}": "settings:write",
}


# --------------------------------------------------------------------------- harness


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Result:
        return self

    def mappings(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def one(self) -> Any:
        return self._rows[0]

    def one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0] if self._rows else 0

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _RecordingSession:
    """Inert session that keeps every statement it was handed.

    ``statements`` is what lets these tests say "the ORDER BY the code BUILT"
    rather than "the rows looked sane", and answer the reads with whatever rows
    the test needs.
    """

    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = list(rows or [])
        self.statements: list[Any] = []

    async def execute(self, stmt: Any, *_args: Any, **_kwargs: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self._rows)

    def add(self, instance: Any) -> None:
        return None

    async def flush(self) -> None:
        return None


def _routes() -> list[Any]:
    out = [r for r in customers_router.routes if getattr(r, "methods", None)]
    out += [r for r in platform_router.routes if getattr(r, "methods", None)]
    return out


def _key(route: Any) -> str:
    methods = sorted(m for m in route.methods if m != "HEAD")
    assert len(methods) == 1, f"route {route.path} answers {methods}"
    return f"{methods[0]} {route.path}"


def _app_for(
    rows: list[Any] | None = None,
    *,
    permissions: set[str] | None = None,
    session: Any = None,
):
    """The real app with auth + tenancy swapped; nothing else is stubbed.

    The two middlewares that open their own Redis/Postgres connection are
    removed: which permission codes the caller holds is decided by the route's
    dependency chain, and leaving them in makes a DB-free run reach the
    provisioned host.
    """
    ctx = TenantContext(
        session=session if session is not None else _RecordingSession(rows),
        user=AuthedUser(id=USER, tenant_id=TENANT, role_code="owner"),
        tenant_id=TENANT,
        role_code="owner",
        permission_codes=set(permissions or ()),
    )
    app = create_app()
    app.user_middleware = [
        m for m in app.user_middleware if m.cls not in {IdempotencyMiddleware, RateLimitMiddleware}
    ]
    app.middleware_stack = None  # force Starlette to rebuild the stack

    async def _session() -> Any:
        yield ctx.session

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _session
    return app


async def _call(
    method: str,
    path: str,
    *,
    rows: list[Any] | None = None,
    permissions: set[str] | None = None,
    params: dict[str, Any] | None = None,
    body: Any = None,
    headers: dict[str, str] | None = None,
):
    session = _RecordingSession(rows)
    app = _app_for(permissions=permissions, session=session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=10) as client:
        response = await client.request(
            method, path, params=params, json=body, headers=headers or {}
        )
    return response, session


def _async_return(value: Any):
    async def _inner(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return _inner


async def _patch(monkeypatch: pytest.MonkeyPatch, target: Any, pairs: Any) -> None:
    """setattr for a batch of (name, replacement) pairs on one target."""
    for name, replacement in pairs:
        monkeypatch.setattr(target, name, replacement)


def _order_by(statement: Any) -> str:
    sql = str(statement.compile(dialect=postgresql.dialect()))
    parts = sql.split("ORDER BY", 1)
    assert len(parts) == 2, f"statement has no ORDER BY: {sql}"
    tail = parts[1]
    for stop in (" LIMIT", " OFFSET"):
        tail = tail.split(stop, 1)[0]
    return tail.strip()


def _customer(**overrides: Any) -> Customer:
    values: dict[str, Any] = {
        "id": CUSTOMER_ID,
        "tenant_id": TENANT,
        "name": "فاتن",
        "phone": "+201001234567",
        "email": "faten@example.test",
        "locale": "ar",
        "lifetime_value": LTV,
        "is_blocked": False,
        "extra": {},
        "version": 4,
        "created_at": BASE,
        "updated_at": BASE,
    }
    values.update(overrides)
    return Customer(**values)


def _schemas() -> dict[str, Any]:
    document = create_app().openapi()
    return document.get("components", {}).get("schemas", {})


def _resolve(schema: dict, components: dict | None = None) -> dict:
    components = components if components is not None else _schemas()
    seen: set[str] = set()
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        assert name not in seen, f"cyclic $ref {name}"
        seen.add(name)
        schema = components[name]
    return schema


def _response_schema(method: str, path: str, code: str = "200") -> dict:
    document = create_app().openapi()
    operation = document["paths"][f"/api/v1{path}"][method.lower()]
    content = operation["responses"][code].get("content") or {}
    return _resolve(content["application/json"]["schema"], document["components"]["schemas"])


# --------------------------------------------------------------- 1. types (P8)


def test_the_module_surface_is_the_measured_route_count() -> None:
    routes = _routes()
    assert len([r for r in routes if r in customers_router.routes]) == CUSTOMERS_ROUTE_COUNT
    assert len([r for r in platform_router.routes if getattr(r, "methods", None)]) == (
        PLATFORM_ROUTE_COUNT
    )


def test_every_customers_route_declares_a_response_model() -> None:
    """P8: a route with no ``response_model`` publishes no contract at all."""
    missing = sorted(
        _key(route)
        for route in _routes()
        if route.response_model is None and _key(route) not in NO_BODY_ROUTES
    )
    assert not missing, (
        f"{len(missing)} customers/platform routes declare no response_model, so "
        "OpenAPI describes nothing real for them (and money on the wire is "
        "whatever the handler happened to build):\n" + "\n".join(f"  {k}" for k in missing)
    )


def test_every_customers_response_schema_documents_its_fields() -> None:
    """Not merely "a model is attached" — the DOCUMENT must carry the fields.

    ``response_model=dict`` would satisfy the declaration test while leaving the
    contract as empty as no model at all.

    The success code is read PER ROUTE, never assumed. This module answers 201 on
    its creates (POST /integrations' 201 is pinned by
    `tests/test_channel_account_lifecycle.py`) and 204 on the two NO_BODY routes,
    so the version of this test that hardcoded `responses["200"]` could not pass —
    and the router answered it by documenting a 200 those routes never send, which
    is exactly the lie a client generator compiles into a broken call. So a 204
    here must carry NO JSON schema, and every other route must have at least one
    2xx response whose schema names its properties.
    """
    document = create_app().openapi()
    components = document.get("components", {}).get("schemas", {})
    paths = {p: ops for p, ops in document["paths"].items() if p.startswith("/api/v1")}

    untyped: list[str] = []
    for key in (_key(r) for r in _routes()):
        method, path = key.split(" ", 1)
        operations = paths.get(f"/api/v1{path}")
        assert operations, f"{key} is not in the OpenAPI document at all"
        responses = operations[method.lower()]["responses"]
        if key in NO_BODY_ROUTES:
            claimed = sorted(
                code
                for code, resp in responses.items()
                if code.startswith("2") and (resp.get("content") or {}).get("application/json")
            )
            assert not claimed, (
                f"{key} is declared NO_BODY (a 204 has no body to type) yet the "
                f"document publishes a JSON schema for it on {claimed}"
            )
            continue
        typed: list[str] = []
        for code, response in responses.items():
            if not code.startswith("2"):
                continue
            schema = (response.get("content") or {}).get("application/json", {}).get("schema")
            if schema is None:
                continue
            body = _resolve(schema, components)
            if body.get("type") == "array":
                body = _resolve(body.get("items") or {}, components)
            if not body.get("properties"):
                untyped.append(f"{key} -> {code}: free-form object")
            else:
                typed.append(code)
        if not typed:
            untyped.append(f"{key}: no 2xx response carries a schema")
    assert not untyped, (
        "these customers responses are documented as nothing in particular:\n"
        + "\n".join(f"  {line}" for line in untyped)
    )


# ------------------------------------------------------- 2. money on the wire


#: ``str(Decimal)`` fields (§47/ADR-053). A response model typed ``float`` — or
#: no model at all, which lets a bare Decimal reach ``jsonable_encoder`` — turns
#: ``999999999999.99`` into ``999999999999.99``-as-a-double, i.e. a lost cent.
MONEY_FIELDS_BY_SCHEMA: dict[str, tuple[str, ...]] = {
    "CustomerSummary": ("lifetime_value",),
    "CustomerDetail": ("lifetime_value",),
    "Customer360Profile": ("lifetime_value",),
    "Customer360Order": ("grand_total",),
    "Customer360Payments": (
        "orders_total",
        "paid_total",
        "refunded_total",
        "net_collected",
        "outstanding",
    ),
    "Customer360Stats": ("net_collected", "outstanding"),
}


def test_every_money_field_of_the_customers_surface_is_a_string() -> None:
    """The OpenAPI type for each amount is ``string``, not number.

    The orders module's rule is that an amount leaves as the string of the
    ``Decimal`` it is stored as; declaring the field ``str`` is what states that
    on the wire instead of leaving it to a handler's ``str()`` call.
    """
    components = _schemas()
    offenders: list[str] = []
    for name, fields in MONEY_FIELDS_BY_SCHEMA.items():
        schema = components.get(name)
        if schema is None:
            offenders.append(f"  {name}: no such component (schema not published)")
            continue
        for field in fields:
            prop = schema.get("properties", {}).get(field)
            if prop is None:
                offenders.append(f"  {name}.{field}: absent from the schema")
            elif prop.get("type") != "string":
                offenders.append(f"  {name}.{field}: type={prop.get('type')} (want string)")
    assert not offenders, (
        "money must leave as str(Decimal) (§47) — these fields are not typed as "
        "strings, so a client may parse them as a float and lose the cent:\n"
        + "\n".join(offenders)
    )


async def test_the_list_and_detail_routes_ship_lifetime_value_as_the_exact_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same column, read two ways, answers one way — and survives typing."""
    row = _customer()

    async def _list(*_a: Any, **_k: Any) -> list[Customer]:
        return [row]

    await _patch(
        monkeypatch,
        CustomerService,
        [
            ("list_customers", _list),
            ("get", _async_return(row)),
            ("list_tags", _async_return([])),
            ("list_identities", _async_return([])),
            ("list_addresses", _async_return([])),
            ("list_notes", _async_return([])),
        ],
    )

    listed, _ = await _call(
        "GET", "/api/v1/customers", rows=[row], permissions={"customers:read", "pii:read"}
    )
    detail, _ = await _call(
        "GET", f"/api/v1/customers/{CUSTOMER_ID}", permissions={"customers:read", "pii:read"}
    )

    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    assert listed.json()["items"][0]["lifetime_value"] == "999999999999.99"
    assert detail.json()["lifetime_value"] == "999999999999.99"
    assert isinstance(listed.json()["items"][0]["lifetime_value"], str)
    assert isinstance(detail.json()["lifetime_value"], str)


async def test_a_twelve_figure_amount_survives_the_response_model_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drift the string rule exists to prevent, measured after typing.

    ``999999999999.99`` and ``999999999999.98`` are both storable in
    NUMERIC(14,2); as doubles they are the same number to two decimals. A
    response model that coerced them to a float would make the two rows agree.
    """
    high = _customer(lifetime_value=LTV)
    low = _customer(lifetime_value=Decimal("999999999999.98"))

    async def _list(_a: Any, _b: Any, **_k: Any) -> list[Customer]:
        return [high, low]

    monkeypatch.setattr(CustomerService, "list_customers", _list)
    response, _ = await _call(
        "GET", "/api/v1/customers", permissions={"customers:read", "pii:read"}
    )

    assert response.status_code == 200, response.text
    values = [Decimal(item["lifetime_value"]) for item in response.json()["items"]]
    assert values[0] - values[1] == Decimal("0.01"), values
    assert float(values[0]) - float(values[1]) != 0.01, (
        "the premise itself is wrong — these two amounts are distinguishable as floats"
    )


# ------------------------------------------- 3. the model must not lie or drop


async def test_the_detail_route_sends_every_key_it_has_always_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response_model silently DROPS undeclared fields (P8's sharp edge).

    The record page reads tags/identities/addresses/notes off this one call; if
    the model named fewer keys than the handler builds, the drawer would go blank
    with a 200.
    """
    row = _customer()
    tag = Tag(id=uuid.uuid4(), tenant_id=TENANT, name="VIP", color="#f00")
    identity = CustomerIdentity(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        customer_id=row.id,
        channel="whatsapp",
        external_id="wa-1",
        created_at=BASE,
    )
    address = Address(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        customer_id=row.id,
        label="home",
        line1="1 Tahrir",
        line2=None,
        city="Cairo",
        region=None,
        postal_code=None,
        country=None,
        is_default=True,
        created_at=BASE,
    )
    note = Note(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        customer_id=row.id,
        author_user_id=USER,
        body="prefers cash",
        created_at=BASE,
    )

    await _patch(
        monkeypatch,
        CustomerService,
        [
            ("get", _async_return(row)),
            ("list_tags", _async_return([tag])),
            ("list_identities", _async_return([identity])),
            ("list_addresses", _async_return([address])),
            ("list_notes", _async_return([note])),
        ],
    )

    response, _ = await _call(
        "GET", f"/api/v1/customers/{CUSTOMER_ID}", permissions={"customers:read", "pii:read"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert {
        "id",
        "name",
        "phone",
        "email",
        "locale",
        "version",
        "lifetime_value",
        "is_blocked",
        "extra",
        "deleted_at",
        "created_at",
        "updated_at",
        "tags",
        "identities",
        "addresses",
        "notes",
    } <= set(body), f"the typed response dropped keys: {sorted(set(body))}"
    assert body["tags"] == [{"id": str(tag.id), "name": "VIP", "color": "#f00"}]
    assert body["addresses"][0]["line1"] == "1 Tahrir"
    assert body["notes"][0]["body"] == "prefers cash"
    assert body["version"] == 4
    assert response.headers["etag"] == '"4"', "the CAS token is not a body field"


async def test_the_360_projection_ships_its_money_and_timeline_through_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The richest payload on this surface, typed end to end."""
    row = _customer()
    order = {
        "id": str(uuid.uuid4()),
        "number": "ORD-1",
        "status": "confirmed",
        "currency": "EGP",
        "grand_total": str(Decimal("150.00")),
        "channel": "dashboard",
        "placed_at": BASE.isoformat(),
        "created_at": BASE.isoformat(),
    }
    conversation = {
        "id": str(uuid.uuid4()),
        "channel": "whatsapp",
        "status": "open",
        "unread_count": 2,
        "assignee_user_id": str(USER),
        "last_message_at": BASE.isoformat(),
        "created_at": BASE.isoformat(),
    }
    task = {
        "id": str(uuid.uuid4()),
        "title": "call back",
        "status": "todo",
        "priority": "high",
        "source": "manual",
        "assignee_user_id": None,
        "due_date": None,
        "created_at": BASE.isoformat(),
    }
    payments = {
        "currency": "EGP",
        "orders_total": "150.00",
        "paid_total": "100.00",
        "refunded_total": "25.00",
        "net_collected": "75.00",
        "outstanding": "75.00",
        "payment_count": 2,
    }

    await _patch(
        monkeypatch,
        CustomerService,
        [
            ("get", _async_return(row)),
            ("list_tags", _async_return([])),
            ("list_identities", _async_return([])),
            ("list_addresses", _async_return([])),
            (
                "list_notes",
                _async_return(
                    [
                        Note(
                            id=uuid.uuid4(),
                            tenant_id=TENANT,
                            customer_id=row.id,
                            author_user_id=None,
                            body="note",
                            created_at=BASE,
                        )
                    ]
                ),
            ),
            ("list_events", _async_return([])),
        ],
    )
    await _patch(
        monkeypatch,
        Customer360Service,
        [
            ("_orders", _async_return([order])),
            ("_conversations", _async_return([conversation])),
            ("_tasks", _async_return([task])),
            ("_payments", _async_return(payments)),
        ],
    )

    response, _ = await _call(
        "GET", f"/api/v1/customers/{CUSTOMER_ID}/360", permissions={"customers:read", "pii:read"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) >= {
        "customer",
        "tags",
        "identities",
        "addresses",
        "notes",
        "orders",
        "conversations",
        "tasks",
        "payments",
        "stats",
        "timeline",
    }, f"the typed 360 lost a section: {sorted(body)}"
    assert body["customer"]["lifetime_value"] == "999999999999.99"
    assert body["orders"][0]["grand_total"] == "150.00"
    assert body["stats"]["net_collected"] == "75.00"
    assert isinstance(body["payments"]["outstanding"], str)
    assert {entry["kind"] for entry in body["timeline"]} == {
        "order",
        "conversation",
        "task",
        "note",
    }, f"every section must reach the merged timeline: {body['timeline']}"


# ---------------------------------------- 4. §146 redaction survives typing


async def test_a_caller_without_pii_read_still_gets_a_200_with_redacted_contacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The typed model must allow what the redactor writes.

    ``_customer_summary`` replaces ``phone``/``email`` with ``None`` for a
    caller without ``pii:read``; a model declaring them ``str`` would raise
    while serializing and turn a privacy feature into a 500.
    """
    row = _customer()

    async def _list(*_a: Any, **_k: Any) -> list[Customer]:
        return [row]

    monkeypatch.setattr(CustomerService, "list_customers", _list)
    response, _ = await _call("GET", "/api/v1/customers", permissions={"customers:read"})

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["phone"] is None and item["email"] is None
    assert item["name"] == "فاتن"
    assert item["lifetime_value"] == "999999999999.99"


# ------------------------------------------------------------------ 5. P4 gates


@pytest.mark.parametrize(
    ("path", "method", "code"),
    [
        ("/customers", "GET", "customers:read"),
        (f"/customers/{CUSTOMER_ID}", "GET", "customers:read"),
        (f"/customers/{CUSTOMER_ID}/360", "GET", "customers:read"),
        (f"/customers/{CUSTOMER_ID}/tags", "GET", "customers:read"),
        (f"/customers/{CUSTOMER_ID}/notes", "GET", "customers:read"),
        ("/integrations", "GET", "settings:read"),
    ],
    ids=["list", "detail", "360", "tags", "notes", "integrations"],
)
async def test_a_read_route_without_its_permission_is_refused_at_the_gate(
    path: str, method: str, code: str
) -> None:
    """P4: the matrix grants this read separately, so the API must honour that.

    A caller who is a member of the tenant (so tenancy resolves) but does not
    hold the code must be refused BEFORE any query runs — reaching the handler
    here would answer 200/404 from the stub session, which is the hole.
    """
    response, session = await _call(method, f"/api/v1{path}", permissions=set())

    assert response.status_code == 403, (
        f"{method} {path} answered {response.status_code} for a caller without "
        f"'{code}' — the route resolves tenancy but checks no permission"
    )
    assert session.statements == [], "the refusal still ran a query"


@pytest.mark.parametrize(
    ("path", "method", "code"),
    [
        ("/customers", "GET", "customers:read"),
        (f"/customers/{CUSTOMER_ID}/tags", "GET", "customers:read"),
        (f"/customers/{CUSTOMER_ID}/notes", "GET", "customers:read"),
        ("/integrations", "GET", "settings:read"),
    ],
    ids=["list", "tags", "notes", "integrations"],
)
async def test_the_same_read_reaches_the_handler_for_its_holder(
    monkeypatch: pytest.MonkeyPatch, path: str, method: str, code: str
) -> None:
    """The non-vacuity half: the gate is a permission test, not a blanket denial.

    Only routes whose handler is satisfied by an empty row set are checked here;
    ``CustomerService.get`` is stubbed because the tag/note lists resolve the
    customer first and an empty stub session answers "no such customer".
    """
    monkeypatch.setattr(CustomerService, "get", _async_return(_customer()))
    response, _ = await _call(method, f"/api/v1{path}", rows=[], permissions={code})

    assert response.status_code == 200, (
        f"{method} {path} refused a caller holding '{code}' with "
        f"{response.status_code}: {response.text[:200]}"
    )


def test_every_customers_route_declares_exactly_one_permission_code() -> None:
    """The P4 verdict as an executable inventory.

    Each route in the module must map to one code from the seeded matrix, and
    the walk over the dependency tree is what proves the code is a GATE and not
    a comment. A route that appears in neither table is the gap; a route that
    declares a code the matrix never grants is a route nobody can call.
    """
    expected = {**GATED_READS, **GATED_WRITES}
    assert len(expected) == len(GATED_READS) + len(GATED_WRITES), "table overlap"

    offenders: list[str] = []
    for route in _routes():
        key = _key(route)
        codes: set[str] = set()
        stack = list(route.dependant.dependencies)
        while stack:
            dependant = stack.pop()
            code = getattr(dependant.call, "code", None)
            if code:
                codes.add(code)
            stack.extend(dependant.dependencies)
        want = expected.get(key)
        if want is None:
            offenders.append(f"  {key}: not in the gate inventory at all")
        elif codes != {want}:
            offenders.append(f"  {key}: gates={sorted(codes) or 'NONE (tenancy only)'} want {want}")
    assert not offenders, (
        "the customers surface is not fully gated against "
        "scripts/provision.py's ROLE_MATRIX (P4):\n" + "\n".join(offenders)
    )


def test_the_gates_are_the_permission_strings_the_seed_actually_grants() -> None:
    """A typo in a code is a route nobody can reach — check against the seed."""
    import importlib.util
    from pathlib import Path

    provision = Path(__file__).resolve().parents[1] / "scripts" / "provision.py"
    spec = importlib.util.spec_from_file_location("_provision_seed", provision)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    granted = {code for codes in module.ROLE_MATRIX.values() for code in codes}

    unknown = sorted({code for code in [*GATED_READS.values(), *GATED_WRITES.values()]} - granted)
    assert not unknown, (
        f"these codes are enforced by no seeded role: {unknown} — the matrix grants "
        f"{sorted(granted)}"
    )


# ---------------------------------------------------------------- 6. P7 sort


async def test_page_1_and_a_cursor_page_sort_on_the_same_key() -> None:
    """P7, read off the SQL: the ORDER BY must not change between pages.

    The cursor is a ``(created_at, id)`` position, so page 2's keyset predicate
    only agrees with an ordering whose tie-break is ``id``. Ordering page 1 by
    ``name`` instead made the boundary meaningless.
    """
    rows = [_customer(id=uuid.uuid4(), created_at=BASE, name=f"n{i}") for i in range(3)]
    first, session = await _call(
        "GET", "/api/v1/customers", rows=rows, permissions={"customers:read"}, params={"limit": 2}
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor, "a 3-row list with limit=2 must hand back a cursor"

    _second, paged_session = await _call(
        "GET",
        "/api/v1/customers",
        rows=rows,
        permissions={"customers:read"},
        params={"limit": 2, "cursor": cursor},
    )
    assert paged_session.statements, "the cursor page sent no statement"

    page_one = _order_by(session.statements[0])
    page_n = _order_by(paged_session.statements[0])
    assert page_one == page_n, (
        "the customer list has two sort keys: page 1 is ordered "
        f"{page_one!r} while a cursor page is ordered {page_n!r}. Rows tied on "
        "the first key repeat on one page and disappear from the next (P7)"
    )
    assert "customers.id" in page_one, (
        f"neither page breaks the created_at tie: ORDER BY {page_one}"
    )


async def test_the_keyset_predicate_uses_the_same_pair_as_the_order_by() -> None:
    """A cursor filter on ``(created_at, id)`` and an ORDER BY on anything else
    is the same defect wearing a different hat — check the predicate too."""
    rows = [_customer(id=uuid.uuid4())]
    _first, session = await _call(
        "GET", "/api/v1/customers", rows=rows, permissions={"customers:read"}, params={"limit": 1}
    )
    _second, paged = await _call(
        "GET",
        "/api/v1/customers",
        rows=rows,
        permissions={"customers:read"},
        params={
            "limit": 1,
            "cursor": _cursor_for(BASE, uuid.uuid4()),
        },
    )
    sql = str(paged.statements[0].compile(dialect=postgresql.dialect()))
    assert "customers.created_at" in _order_by(paged.statements[0])
    assert "customers.id" in _order_by(paged.statements[0]), sql
    assert session.statements, "page 1 sent nothing — the harness is broken"


def _cursor_for(created_at: datetime, row_id: uuid.UUID) -> str:
    from app.core.pagination import encode_cursor

    return encode_cursor(created_at, row_id)


# ------------------------------------------------- 7. P7 on real PostgreSQL
#
# The defect is a DATABASE behaviour: only tied rows prove that a page overlaps
# its neighbour. These need DATABASE_URL_APP_ADMIN, skip locally, and CI runs
# them — same shape as tests/test_platform_http_surface.py's tied-row paging.


async def _rows_at(db: Any, tenant_id: uuid.UUID, *, created_at: datetime, n: int) -> list[Any]:
    from app.modules.customers.models import Customer as CustomerRow

    rows = []
    for i in range(n):
        row = CustomerRow(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=f"Tied {i}",
            phone=None,
            created_at=created_at,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    return rows


async def _client(db: Any, tenant_id: uuid.UUID, user_id: uuid.UUID, permissions: set[str]):
    app = _app_for(permissions=permissions)

    async def _session() -> Any:
        yield db

    app.dependency_overrides[get_tenant_ctx] = lambda: TenantContext(
        session=db,
        user=AuthedUser(id=user_id, tenant_id=tenant_id, role_code="owner"),
        tenant_id=tenant_id,
        role_code="owner",
        permission_codes=set(permissions),
    )
    app.dependency_overrides[get_db] = _session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=20)


@pytest.mark.parametrize("created_at", [BASE], ids=["tied"])
async def test_pages_over_tied_created_at_show_every_customer_exactly_once(
    db: Any, tenant_ctx: Any, created_at: datetime
) -> None:
    """Five rows sharing one created_at, pages of two: each exactly once.

    With ``ORDER BY created_at DESC, name ASC`` on page 1 and ``…, id DESC`` on
    page 2, the boundary row of page 1 is chosen by name and skipped by a tuple
    comparison built on id — so some tied row is served twice and another never.
    """
    await _rows_at(db, tenant_ctx.tenant_id, created_at=created_at, n=5)

    seen: list[str] = []
    async with _client(
        db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"customers:read", "pii:read"}
    ) as client:
        cursor: str | None = None
        for _ in range(3):
            params: dict[str, Any] = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            response = await client.get("/api/v1/customers", params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            seen.extend(item["id"] for item in page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                break

    assert len(seen) == len(set(seen)) == 5, (
        f"paging over 5 tied customers must show each exactly once, saw {seen}"
    )
