"""§17 Wave-2 — conditional writes for the remaining mutating versioned entities.

Customers and orders were the first adopters (see test_customers_if_match.py);
this closes the surface where versioned rows actually change through HTTP:

* ``workflows`` — no ``VersionMixin`` at all today. The row is mutated by the
  status PATCH and by ``current_version`` bumps on publish, so two writers can
  silently clobber each other. This adds the column (migration), routes every
  write through the atomic ``apply_versioned_update`` (version bumps on EVERY
  write, conditional or not — an ETag that failed to advance would lie), and
  accepts ``If-Match`` on status/publish writes plus an ``ETag`` on the read.
* ``orders`` GET detail — the row version exists and If-Match already works on
  the status route, but the read never advertised the version, so no client
  could ever produce a correct ``If-Match``.

Campaign / Agent / Refund rows are not mutated by ANY HTTP endpoint today
(create-only surfaces), so there is no conditional-write seam to wire — that
exemption is recorded in ``app.core.idempotency``'s docstring, not silently
dropped.

Two layers mirror the customers file: DB-free tests drive the real routers
through ``create_app()`` with fake sessions (header wiring, 409/ETag contract);
the DB-backed test (CI) proves the UPDATE is genuinely conditional.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.automation.models import Workflow
from app.modules.automation.service import WorkflowService
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.orders.models import Order
from app.modules.orders.service import OrderService

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, version: int | None) -> None:
        self._version = version

    def scalar_one_or_none(self) -> int | None:
        return self._version

    def scalar_one(self) -> int:
        # The derived money read sums payments and refunds; against this double
        # nothing has moved, which is the honest "no money yet" answer.
        return 0


class _FakeSession:
    """Enough of AsyncSession for apply_versioned_update (+ service inserts).

    ``returned`` is what the conditional UPDATE's RETURNING yields: the new
    version when WHERE id AND version matched, None when it did not.
    """

    def __init__(self, returned: int | None) -> None:
        self.returned = returned
        self.statements: list[object] = []
        self.added: list[object] = []

    async def execute(self, statement: object, params: object = None) -> _FakeResult:
        # ``params`` is part of the real ``AsyncSession.execute`` signature — the
        # §66 audit writer passes bound parameters, so a double without it would
        # fail on the SECOND positional argument rather than on anything it is
        # here to observe.
        self.statements.append(statement)
        return _FakeResult(self.returned)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


def _async_return(value: object):
    async def _inner(*_args: object, **_kwargs: object) -> object:
        return value

    return _inner


def _now() -> datetime:
    return datetime.now(UTC)


def _workflow(version: int, status: str = "draft") -> Workflow:
    return Workflow(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="wf",
        trigger_event="order.created",
        status=status,
        current_version=1,
        version=version,
        created_at=_now(),
        updated_at=_now(),
    )


def _order(version: int) -> Order:
    order = Order(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        number="ORD-T-1",
        customer_id=uuid.uuid4(),
        status="pending",
        currency="EGP",
        created_at=_now(),
        updated_at=_now(),
    )
    order.version = version
    order.items = []  # the detail route serializes getattr(order, "items", [])
    return order


def _app(
    session: object,
    tenant_id: uuid.UUID,
    permissions: set[str],
    user_id: uuid.UUID | None = None,
):
    app = create_app()
    ctx = TenantContext(
        session=session,  # type: ignore[arg-type]
        user=AuthedUser(id=user_id or uuid.uuid4(), tenant_id=tenant_id, role_code="owner"),
        tenant_id=tenant_id,
        role_code="owner",
        permission_codes=permissions,
    )

    async def _override() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _override
    return app


async def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Model guard (DB-free): the concurrency column is part of the mapping
# ---------------------------------------------------------------------------


def test_workflow_row_carries_a_version_column():
    """§17: without VersionMixin there is no CAS token to gate workflow writes."""
    assert "version" in Workflow.__table__.c


# ---------------------------------------------------------------------------
# Workflows — DB-free router contract
# ---------------------------------------------------------------------------


async def test_get_workflow_emits_version_and_etag(monkeypatch) -> None:
    workflow = _workflow(version=4)
    monkeypatch.setattr(WorkflowService, "get", _async_return(workflow))

    tenant = uuid.uuid4()
    async with await _client(_app(_FakeSession(4), tenant, {"settings:write"})) as client:
        response = await client.get(f"/api/v1/workflows/{workflow.id}")

    assert response.status_code == 200
    assert response.headers["etag"] == '"4"', "the read must advertise the version"
    assert response.json()["version"] == 4


async def test_workflow_status_stale_if_match_409_and_no_write(monkeypatch) -> None:
    workflow = _workflow(version=4)
    session = _FakeSession(returned=None)  # conditional UPDATE matched no row
    monkeypatch.setattr(WorkflowService, "get", _async_return(workflow))

    tenant = uuid.uuid4()
    async with await _client(_app(session, tenant, {"settings:write"})) as client:
        response = await client.patch(
            f"/api/v1/workflows/{workflow.id}/status",
            json={"status": "active"},
            headers={"If-Match": '"2"'},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert workflow.status == "draft", "the stale write must not have been applied"
    assert session.statements, "the conditional UPDATE must have run"


async def test_workflow_status_current_etag_advances_for_chaining(monkeypatch) -> None:
    workflow = _workflow(version=4)
    session = _FakeSession(returned=5)
    monkeypatch.setattr(WorkflowService, "get", _async_return(workflow))

    tenant = uuid.uuid4()
    async with await _client(_app(session, tenant, {"settings:write"})) as client:
        response = await client.patch(
            f"/api/v1/workflows/{workflow.id}/status",
            json={"status": "active"},
            headers={"If-Match": '"4"'},
        )

    assert response.status_code == 200
    assert response.headers["etag"] == '"5"'
    assert workflow.status == "active"
    assert workflow.version == 5


async def test_workflow_status_without_if_match_still_bumps_the_version(
    monkeypatch,
) -> None:
    """Unconditional writes pass through the SAME single statement — an ETag
    that only advanced on conditional writes would lie to every reader."""
    workflow = _workflow(version=4)
    session = _FakeSession(returned=5)
    monkeypatch.setattr(WorkflowService, "get", _async_return(workflow))

    tenant = uuid.uuid4()
    async with await _client(_app(session, tenant, {"settings:write"})) as client:
        response = await client.patch(
            f"/api/v1/workflows/{workflow.id}/status", json={"status": "active"}
        )

    assert response.status_code == 200
    assert response.headers["etag"] == '"5"'
    assert session.statements, "the write went through the versioned UPDATE"


async def test_workflow_publish_gates_on_if_match_and_advances(monkeypatch) -> None:
    workflow = _workflow(version=4)
    session = _FakeSession(returned=5)
    monkeypatch.setattr(WorkflowService, "get", _async_return(workflow))

    tenant = uuid.uuid4()
    async with await _client(_app(session, tenant, {"settings:write"})) as client:
        session.returned = None  # the stale conditional UPDATE matches no row
        stale = await client.post(
            f"/api/v1/workflows/{workflow.id}/versions",
            json={"definition": {"steps": []}},
            headers={"If-Match": '"1"'},
        )
        assert stale.status_code == 409
        assert session.added == [], "a lost race must not insert a snapshot"

        session.returned = 5  # now the WHERE id AND version matches
        fresh = await client.post(
            f"/api/v1/workflows/{workflow.id}/versions",
            json={"definition": {"steps": []}},
            headers={"If-Match": '"4"'},
        )

    assert fresh.status_code == 201
    assert fresh.headers["etag"] == '"5"'
    assert workflow.current_version == 2
    assert len(session.added) == 1
    assert session.added[0].version == 2


async def test_workflow_malformed_if_match_is_400(monkeypatch) -> None:
    workflow = _workflow(version=4)
    monkeypatch.setattr(WorkflowService, "get", _async_return(workflow))

    tenant = uuid.uuid4()
    async with await _client(_app(_FakeSession(4), tenant, {"settings:write"})) as client:
        response = await client.patch(
            f"/api/v1/workflows/{workflow.id}/status",
            json={"status": "active"},
            headers={"If-Match": "not-a-version"},
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Orders — the read must carry the CAS token If-Match needs
# ---------------------------------------------------------------------------


async def test_get_order_emits_version_and_etag(monkeypatch) -> None:
    order = _order(version=3)
    monkeypatch.setattr(OrderService, "get", _async_return(order))

    tenant = uuid.uuid4()
    async with await _client(_app(_FakeSession(3), tenant, {"orders:read"})) as client:
        response = await client.get(f"/api/v1/orders/{order.id}")

    assert response.status_code == 200
    assert response.headers["etag"] == '"3"'
    assert response.json()["version"] == 3


# ---------------------------------------------------------------------------
# DB-backed (CI): the database decides the winner
# ---------------------------------------------------------------------------


def _db_app(db: AsyncSession, tenant_ctx, permissions: set[str]) -> object:
    # FK-guarded paths read the caller's user id, so it must be a real users
    # row — a fabricated uuid4 violates FKs the moment CI runs this.
    return _app(
        db,
        tenant_ctx.tenant_id,
        permissions | {"settings:write", "orders:write"},
        user_id=tenant_ctx.user.id,
    )


async def test_workflow_conditional_writes_against_the_database(
    db: AsyncSession, tenant_ctx
) -> None:
    workflow = await WorkflowService.create(
        db,
        tenant_ctx.tenant_id,
        name="wf-db",
        trigger_event="order.created",
        definition={"steps": []},
    )
    await db.flush()
    await db.refresh(workflow)
    start_version = workflow.version
    assert start_version == 1, "server default on the new column"

    async with await _client(_db_app(db, tenant_ctx, set())) as client:
        fetched = await client.get(f"/api/v1/workflows/{workflow.id}")
        assert fetched.headers["etag"] == '"1"'

        stale = await client.patch(
            f"/api/v1/workflows/{workflow.id}/status",
            json={"status": "active"},
            headers={"If-Match": '"999"'},
        )
        assert stale.status_code == 409

        await db.refresh(workflow)
        assert workflow.status == "draft" and workflow.version == 1

        ok = await client.patch(
            f"/api/v1/workflows/{workflow.id}/status",
            json={"status": "active"},
            headers={"If-Match": '"1"'},
        )
        assert ok.status_code == 200
        assert ok.headers["etag"] == '"2"'

        published = await client.post(
            f"/api/v1/workflows/{workflow.id}/versions",
            json={"definition": {"steps": []}},
            headers={"If-Match": '"2"'},
        )
        assert published.status_code == 201
        assert published.json()["version"] == 2

    await db.refresh(workflow)
    assert workflow.status == "active"
    assert workflow.current_version == 2
    assert workflow.version == 3


async def test_order_status_if_match_round_trip_against_the_database(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.customers.service import CustomerService

    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_ctx.tenant_id,
        "whatsapp",
        f"wamid.ifmatch.{uuid.uuid4().hex[:8]}",
    )
    order = Order(
        tenant_id=tenant_ctx.tenant_id,
        number=f"ORD-T-{uuid.uuid4().hex[:8]}",
        customer_id=customer.id,
        status="pending",
    )
    db.add(order)
    await db.flush()
    await db.refresh(order)

    async with await _client(_db_app(db, tenant_ctx, {"orders:read"})) as client:
        fetched = await client.get(f"/api/v1/orders/{order.id}")
        assert fetched.status_code == 200
        assert fetched.headers["etag"] == f'"{order.version}"'

        stale = await client.post(
            f"/api/v1/orders/{order.id}/status",
            json={"status": "confirmed"},
            headers={"If-Match": '"999"'},
        )
        assert stale.status_code == 409

        ok = await client.post(
            f"/api/v1/orders/{order.id}/status",
            json={"status": "confirmed"},
            headers={"If-Match": f'"{order.version}"'},
        )
        assert ok.status_code == 200

    await db.refresh(order)
    assert order.status == "confirmed"
