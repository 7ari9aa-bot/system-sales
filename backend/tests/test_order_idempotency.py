"""Order creation honours ``Idempotency-Key`` (the money path, M11).

``POST /api/v1/orders`` is on the idempotency allow-list (``IDEMPOTENT_PATHS``
in ``app/core/idempotency.py``), so a client retry carrying the SAME
``Idempotency-Key`` must return the FIRST order rather than creating a second
one: a duplicated order is a duplicated charge AND a doubled stock hold.

``tests/test_request_integrity.py`` proves the middleware in isolation (a fake
endpoint behind a fake store) and the store in isolation. Neither proves the
REAL orders route is guarded — the repo's own roadmap calls that out as its
dominant failure mode: "built, tested in isolation, and never called". These
tests close that gap at the two levels that matter:

* ``test_order_creation_*`` — DB-free: the real router, mounted at the real
  path, behind the real middleware. Fails if the endpoint is not opted in.
* ``test_order_creation_is_idempotent_against_the_database`` — DB-backed: the
  same route against Postgres with the real store, the real service and the
  real stock reservation (skips locally when no database URL is configured).
"""

from __future__ import annotations

import base64
import uuid
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, build_error_body
from app.core.idempotency import (
    CONFLICT,
    NEW,
    REPLAY,
    IdempotencyClaim,
    IdempotencyMiddleware,
    IdempotencyService,
)
from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.inventory.models import InventoryBalance, Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import Order
from app.modules.orders.router import router as orders_router
from app.modules.orders.service import OrderService
from app.modules.platform.models import OutboxEvent

ORDERS_PATH = "/api/v1/orders"
KEY_HEADER = "Idempotency-Key"

_ITEM = {"variant_id": "22222222-2222-2222-2222-222222222222", "quantity": 2}
ORDER_BODY = {
    "customer_id": "11111111-1111-1111-1111-111111111111",
    "items": [_ITEM],
}
# Same key, DIFFERENT body: a client bug, not a retry — must be refused.
OTHER_BODY = {
    "customer_id": "11111111-1111-1111-1111-111111111111",
    "items": [{**_ITEM, "quantity": 3}],
}


# ---------------------------------------------------------------------------
# Test doubles / app wiring
# ---------------------------------------------------------------------------


class MemoryStore:
    """In-memory stand-in for ``DbIdempotencyStore`` with the same outcomes."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}

    async def begin(self, *, scope: str, key: str, request_hash: str) -> IdempotencyClaim:
        record = self._records.get((scope, key))
        if record is None:
            self._records[(scope, key)] = {"hash": request_hash, "response": None}
            return IdempotencyClaim(NEW)
        if record["hash"] != request_hash:
            return IdempotencyClaim(CONFLICT)
        if record["response"] is None:
            return IdempotencyClaim("in_progress")
        return IdempotencyClaim(REPLAY, record["response"])

    async def complete(
        self, *, scope: str, key: str, status_code: int, body: bytes, content_type: str
    ) -> None:
        self._records[(scope, key)]["response"] = {
            "status": status_code,
            "body": base64.b64encode(body).decode(),
            "content_type": content_type,
        }

    async def fail(
        self, *, scope: str, key: str, status_code: int | None = None
    ) -> None:
        self._records.pop((scope, key), None)

    async def release(self, *, scope: str, key: str) -> None:
        self._records.pop((scope, key), None)


class SessionStore:
    """The REAL ``IdempotencyService``, bound to the test's transaction.

    The middleware's own store opens (and commits) its own session; inside a
    test that transaction has to stay rolled back, so the store plumbing is
    swapped for the test session while the store LOGIC is unchanged.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def begin(self, *, scope: str, key: str, request_hash: str) -> IdempotencyClaim:
        return await IdempotencyService.begin(
            self._session, scope=scope, key=key, request_hash=request_hash
        )

    async def complete(
        self, *, scope: str, key: str, status_code: int, body: bytes, content_type: str
    ) -> None:
        await IdempotencyService.complete(
            self._session,
            scope=scope,
            key=key,
            status_code=status_code,
            body=body,
            content_type=content_type,
        )

    async def fail(
        self, *, scope: str, key: str, status_code: int | None = None
    ) -> None:
        await IdempotencyService.fail(
            self._session, scope=scope, key=key, status_code=status_code
        )

    async def release(self, *, scope: str, key: str) -> None:
        await IdempotencyService.release(self._session, scope=scope, key=key)


def _build_app(*, store: Any, tenant_id: uuid.UUID, session: Any) -> FastAPI:
    """The real orders router behind the real idempotency middleware.

    Auth is replaced by a pre-built ``TenantContext`` so the test can focus on
    the idempotency wiring; the route, its path and the middleware are the
    production ones.
    """
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=build_error_body(exc))

    app.include_router(orders_router, prefix="/api/v1")
    app.add_middleware(IdempotencyMiddleware, store=store)

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=session,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="owner"),
            tenant_id=tenant_id,
            role_code="owner",
            permission_codes={"orders:write"},
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


def _counting_create_order(created: list[uuid.UUID]):
    """``OrderService.create_order`` stand-in that records every call."""

    async def create_order(
        session: Any,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        items: list[dict],
        *,
        channel: str | None = None,
        shipping_address: dict | None = None,
        warehouse_id: uuid.UUID | None = None,
        # This stand-in is about the MIDDLEWARE, not the money: it takes what the
        # route passes so a new service kwarg cannot make these three tests red.
        **_kwargs: Any,
    ) -> Any:
        order_id = uuid.uuid4()
        created.append(order_id)
        return SimpleNamespace(
            id=order_id,
            number=f"ORD-TEST-{len(created):04d}",
            status="pending",
            subtotal="50.00",
            discount_total="0.00",
            shipping_total="0.00",
            tax_total="0.00",
            grand_total="50.00",
            currency="EGP",
        )

    return create_order


async def _post(client: AsyncClient, body: dict, key: str | None):
    headers = {KEY_HEADER: key} if key else {}
    return await client.post(ORDERS_PATH, json=body, headers=headers)


# ---------------------------------------------------------------------------
# DB-free: the real route behind the real middleware
# ---------------------------------------------------------------------------


async def test_order_creation_replays_and_creates_one_order(monkeypatch) -> None:
    created: list[uuid.UUID] = []
    monkeypatch.setattr(OrderService, "create_order", _counting_create_order(created))
    app = _build_app(store=MemoryStore(), tenant_id=uuid.uuid4(), session=None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post(client, ORDER_BODY, "order-key-1")
        second = await _post(client, ORDER_BODY, "order-key-1")

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json(), "a retry must return the FIRST order"
    assert second.headers.get("idempotency-replayed") == "true"
    assert len(created) == 1, "a retried request must not create a second order"


async def test_order_creation_rejects_key_reuse_with_a_different_body(monkeypatch) -> None:
    created: list[uuid.UUID] = []
    monkeypatch.setattr(OrderService, "create_order", _counting_create_order(created))
    app = _build_app(store=MemoryStore(), tenant_id=uuid.uuid4(), session=None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _post(client, ORDER_BODY, "order-key-2")
        conflict = await _post(client, OTHER_BODY, "order-key-2")

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "conflict"
    assert len(created) == 1, "a rejected reuse must not reach the route again"


async def test_order_creation_without_the_header_is_unchanged(monkeypatch) -> None:
    """Opt-in: a client that sends no key keeps the plain, retryable semantics."""
    created: list[uuid.UUID] = []
    monkeypatch.setattr(OrderService, "create_order", _counting_create_order(created))
    app = _build_app(store=MemoryStore(), tenant_id=uuid.uuid4(), session=None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post(client, ORDER_BODY, None)
        second = await _post(client, ORDER_BODY, None)

    assert first.status_code == 201 and second.status_code == 201
    assert second.json() != first.json()
    assert len(created) == 2


# ---------------------------------------------------------------------------
# DB-backed: real store, real service, real stock reservation
# ---------------------------------------------------------------------------


async def _seed_checkout(db: AsyncSession, tenant_id: uuid.UUID):
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Idem Buyer"
    )
    warehouse = Warehouse(
        tenant_id=tenant_id, name="Idem WH", code=f"WH-{uuid.uuid4().hex[:6].upper()}"
    )
    db.add(warehouse)
    await db.flush()
    product = await CatalogService.create_product(
        db, tenant_id, title="Idem Widget", slug=f"iw-{uuid.uuid4().hex[:10]}"
    )
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, sku=f"IWG-{uuid.uuid4().hex[:6].upper()}", price="25.50"
    )
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=10,
        reason="purchase",
    )
    return customer, variant, warehouse


async def test_order_creation_is_idempotent_against_the_database(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, variant, warehouse = await _seed_checkout(db, tenant_id)
    app = _build_app(store=SessionStore(db), tenant_id=tenant_id, session=db)
    key = f"order-{uuid.uuid4().hex}"
    payload = {
        "customer_id": str(customer.id),
        "items": [{"variant_id": str(variant.id), "quantity": 3}],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post(client, payload, key)
        second = await _post(client, payload, key)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json(), "a retry must return the FIRST order"
    order_id = uuid.UUID(first.json()["id"])

    orders = (
        await db.execute(
            sa.select(Order).where(
                Order.tenant_id == tenant_id, Order.customer_id == customer.id
            )
        )
    ).scalars().all()
    assert len(orders) == 1, "the retry must not create a second order"

    # The stock hold is part of the same unit of work as the order: replayed
    # requests must not reserve it twice.
    balance = (
        await db.execute(
            sa.select(InventoryBalance).where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.variant_id == variant.id,
                InventoryBalance.warehouse_id == warehouse.id,
            )
        )
    ).scalar_one()
    assert balance.reserved == 3

    # ...and the order.created event is staged exactly once.
    events = (
        await db.execute(
            sa.select(OutboxEvent).where(OutboxEvent.aggregate_id == order_id)
        )
    ).scalars().all()
    assert len(events) == 1


async def test_order_creation_conflicts_on_key_reuse_against_the_database(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, variant, _warehouse = await _seed_checkout(db, tenant_id)
    app = _build_app(store=SessionStore(db), tenant_id=tenant_id, session=db)
    key = f"order-{uuid.uuid4().hex}"
    payload = {
        "customer_id": str(customer.id),
        "items": [{"variant_id": str(variant.id), "quantity": 1}],
    }
    other = {
        "customer_id": str(customer.id),
        "items": [{"variant_id": str(variant.id), "quantity": 2}],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post(client, payload, key)
        conflict = await _post(client, other, key)

    assert first.status_code == 201, first.text
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "conflict"

    orders = (
        await db.execute(
            sa.select(Order).where(
                Order.tenant_id == tenant_id, Order.customer_id == customer.id
            )
        )
    ).scalars().all()
    assert len(orders) == 1
