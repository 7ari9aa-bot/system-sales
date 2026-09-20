"""WS-B1: the customers PATCH is the first adopter of the G-15 conditional-write
surface in ``app.core.idempotency``.

Before this, nothing on the request path read ``If-Match`` or set ``ETag`` — the
atomic compare-and-swap helper existed but was never wired to a route. These
tests pin the contract of that first adopter:

* ``GET /customers/{id}`` exposes the row's ``version`` and returns it as a
  strong ``ETag``;
* ``PATCH`` with a STALE ``If-Match`` is refused with 409 (the project's
  existing ``ConflictError``) and the row is NOT written;
* ``PATCH`` with the CURRENT ``ETag`` succeeds and the returned ``ETag``
  advances, so a client can chain edits;
* no ``If-Match`` keeps the pre-existing unconditional behaviour.

Two layers: the DB-free tests drive the real router through the ASGI app against
a fake session, which proves the header wiring and the 409/ETag contract without
a database. The DB-backed tests run in CI against a real Postgres and prove the
UPDATE is genuinely conditional (the DB, not Python, decides the winner).
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx

# ---------------------------------------------------------------------------
# Doubles — enough of a session/context for the conditional-write path
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, version: int | None) -> None:
        self._version = version

    def scalar_one_or_none(self) -> int | None:
        return self._version


class _FakeSession:
    """Stands in for ``AsyncSession`` for ``apply_versioned_update``.

    ``returned`` is what the conditional UPDATE's ``RETURNING version`` yields:
    the new version when the ``WHERE id AND version`` matched, ``None`` when it
    did not (the stale case). ``statements`` records every execute so a test can
    prove the write really went through the atomic helper.
    """

    def __init__(self, returned: int | None) -> None:
        self.returned = returned
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult(self.returned)


def _async_return(value: object):
    async def _inner(*_args: object, **_kwargs: object) -> object:
        return value

    return _inner


def _customer(version: int, name: str = "Acme") -> Customer:
    return Customer(id=uuid.uuid4(), tenant_id=uuid.uuid4(), name=name, version=version)


def _ctx(session: object, tenant_id: uuid.UUID) -> TenantContext:
    return TenantContext(
        session=session,  # type: ignore[arg-type] — the fake satisfies the path used
        user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="owner"),
        tenant_id=tenant_id,
        role_code="owner",
        permission_codes={"customers:read", "customers:write"},
    )


def _app(session: object, tenant_id: uuid.UUID):
    """The real app with auth/tenant resolution replaced by a fixed context.

    Only the tenant dependency is overridden, so the route, the ``If-Match``
    header parsing and the response-header merge are all the production ones.
    """
    app = create_app()
    ctx = _ctx(session, tenant_id)

    async def _override() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _override
    return app


async def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# DB-free: GET emits the version + ETag
# ---------------------------------------------------------------------------


async def test_get_customer_emits_version_and_etag(monkeypatch) -> None:
    customer = _customer(version=4)
    monkeypatch.setattr(CustomerService, "get", _async_return(customer))
    for name in ("list_tags", "list_identities", "list_addresses", "list_notes"):
        monkeypatch.setattr(CustomerService, name, _async_return([]))

    async with await _client(_app(_FakeSession(4), uuid.uuid4())) as client:
        response = await client.get(f"/api/v1/customers/{customer.id}")

    assert response.status_code == 200
    assert response.headers["etag"] == '"4"', "the read must advertise the version"
    assert response.json()["version"] == 4, "the version must be in the body too"


# ---------------------------------------------------------------------------
# DB-free: PATCH honours If-Match
# ---------------------------------------------------------------------------


async def test_patch_with_stale_if_match_conflicts_and_does_not_write(
    monkeypatch,
) -> None:
    customer = _customer(version=4)
    # The conditional UPDATE matched no row -> the helper raises ConflictError.
    session = _FakeSession(returned=None)
    monkeypatch.setattr(CustomerService, "get", _async_return(customer))

    async with await _client(_app(session, uuid.uuid4())) as client:
        response = await client.patch(
            f"/api/v1/customers/{customer.id}",
            json={"name": "Hacked"},
            headers={"If-Match": '"2"'},
        )

    assert response.status_code == 409, "a stale ETag must be a conflict, not a 500"
    assert response.json()["error"]["code"] == "conflict"
    assert customer.name == "Acme", "the stale write must not have been applied"
    assert session.statements, "the conditional UPDATE must have run"


async def test_patch_with_current_etag_succeeds_and_advances(monkeypatch) -> None:
    customer = _customer(version=4)
    # The conditional UPDATE matched and bumped the row to 5.
    session = _FakeSession(returned=5)
    monkeypatch.setattr(CustomerService, "get", _async_return(customer))

    async with await _client(_app(session, uuid.uuid4())) as client:
        response = await client.patch(
            f"/api/v1/customers/{customer.id}",
            json={"name": "Renamed"},
            headers={"If-Match": '"4"'},
        )

    assert response.status_code == 200
    assert response.headers["etag"] == '"5"', "the ETag must advance for chaining"
    assert customer.name == "Renamed"
    assert customer.version == 5


async def test_patch_without_if_match_stays_unconditional(monkeypatch) -> None:
    customer = _customer(version=4)
    # A conflict would be raised if the version guard ran; it must not.
    session = _FakeSession(returned=None)
    seen: dict[str, object] = {}

    async def _update(session, tenant_id, customer_id, **fields):  # noqa: ANN001
        seen["fields"] = fields
        return customer

    monkeypatch.setattr(CustomerService, "update_customer", _update)

    async with await _client(_app(session, uuid.uuid4())) as client:
        response = await client.patch(
            f"/api/v1/customers/{customer.id}", json={"name": "X"}
        )

    assert response.status_code == 200
    assert seen["fields"] == {"name": "X"}
    assert session.statements == [], "no If-Match means no version constraint"


async def test_malformed_if_match_is_a_client_error(monkeypatch) -> None:
    customer = _customer(version=4)
    monkeypatch.setattr(CustomerService, "get", _async_return(customer))
    monkeypatch.setattr(CustomerService, "update_customer", _async_return(customer))

    async with await _client(_app(_FakeSession(4), uuid.uuid4())) as client:
        response = await client.patch(
            f"/api/v1/customers/{customer.id}",
            json={"name": "X"},
            headers={"If-Match": "not-a-version"},
        )

    assert response.status_code == 400, "a malformed ETag is the client's bug"


# ---------------------------------------------------------------------------
# DB-backed (CI): the database decides
# ---------------------------------------------------------------------------


def _db_app(db: AsyncSession, tenant_ctx) -> object:
    app = create_app()
    ctx = TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"customers:read", "customers:write"},
    )

    async def _override() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _override
    return app


async def test_stale_if_match_conflicts_and_current_etag_advances(
    db: AsyncSession, tenant_ctx
) -> None:
    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Acme")
    db.add(customer)
    await db.flush()
    start_version = customer.version
    assert start_version == 1
    app = _db_app(db, tenant_ctx)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        fetched = await client.get(f"/api/v1/customers/{customer.id}")
        assert fetched.status_code == 200
        assert fetched.headers["etag"] == f'"{start_version}"'
        assert fetched.json()["version"] == start_version

        stale = await client.patch(
            f"/api/v1/customers/{customer.id}",
            json={"name": "Hacked"},
            headers={"If-Match": '"999"'},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "conflict"

        # The row is untouched: a stale If-Match must not write.
        await db.refresh(customer)
        assert customer.name == "Acme"
        assert customer.version == start_version

        current = await client.patch(
            f"/api/v1/customers/{customer.id}",
            json={"name": "Renamed"},
            headers={"If-Match": f'"{start_version}"'},
        )
        assert current.status_code == 200
        assert current.headers["etag"] == f'"{start_version + 1}"'

    await db.refresh(customer)
    assert customer.name == "Renamed"
    assert customer.version == start_version + 1
