"""The POS money path honours ``Idempotency-Key`` (a double tap must not double charge).

A cashier taps Pay, the network drops AFTER the server committed the sale, the
client retries. Without a replay guard that second request is a second sale: the
customer is charged twice and the shelf is decremented twice.

``POST /api/v1/orders`` is guarded (``IDEMPOTENT_PATHS``); ``/api/v1/pos`` was
not, so ``sell`` / ``refunds`` / ``returns`` / ``exchanges`` / ``cash-movements``
all re-executed on a retry. These tests mount the REAL POS router behind the REAL
middleware (same pattern as ``test_order_idempotency.py``) and fail if a route is
not opted in.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.errors import DomainError, build_error_body
from app.core.idempotency import IDEMPOTENT_PATHS, IdempotencyMiddleware
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.pos.router import router as pos_router
from app.modules.pos.service import PosService
from tests.test_order_idempotency import MemoryStore

KEY_HEADER = "Idempotency-Key"
SESSION = "33333333-3333-3333-3333-333333333333"
ORDER = "44444444-4444-4444-4444-444444444444"
VARIANT = "22222222-2222-2222-2222-222222222222"

SELL_BODY = {
    "items": [{"variant_id": VARIANT, "quantity": 2}],
    "tenders": [{"method": "cash", "amount": "50.00"}],
}
OTHER_SELL_BODY = {
    "items": [{"variant_id": VARIANT, "quantity": 3}],
    "tenders": [{"method": "cash", "amount": "75.00"}],
}

# (method path suffix, body, PosService method it must reach exactly once)
MONEY_ROUTES = {
    "sell": (f"/api/v1/pos/sessions/{SESSION}/sell", SELL_BODY, "sell"),
    "refund": (
        f"/api/v1/pos/sessions/{SESSION}/refunds",
        {"order_id": ORDER, "amount": "10.00", "method": "cash"},
        "refund",
    ),
    "return": (
        f"/api/v1/pos/sessions/{SESSION}/returns",
        {"order_id": ORDER, "lines": [{"variant_id": VARIANT, "quantity": 1}]},
        "return_sale",
    ),
    "exchange": (
        f"/api/v1/pos/sessions/{SESSION}/exchanges",
        {
            "order_id": ORDER,
            "return_lines": [{"variant_id": VARIANT, "quantity": 1}],
            "new_lines": [{"variant_id": VARIANT, "quantity": 1}],
        },
        "exchange",
    ),
    "cash_movement": (
        f"/api/v1/pos/sessions/{SESSION}/cash-movements",
        {"direction": "out", "reason": "pay_out", "amount": "20.00"},
        "record_cash_movement",
    ),
}


def _build_app(store: Any, tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=build_error_body(exc))

    app.include_router(pos_router, prefix="/api/v1")
    app.add_middleware(IdempotencyMiddleware, store=store)

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=None,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="owner"),
            tenant_id=tenant_id,
            role_code="owner",
            permission_codes={"pos:write", "pos:read", "orders:write"},
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


def test_pos_is_on_the_idempotency_allow_list() -> None:
    """The guard is opt-in by path: a route not on the list is unprotected."""
    assert any(
        p.rstrip("/") == "/api/v1/pos" or "/api/v1/pos".startswith(p) for p in IDEMPOTENT_PATHS
    ), "POS money routes (sell/refund/return/exchange/cash-movement) are not retry-safe"


async def test_sell_replays_and_charges_once(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_sell(session, tenant_id, session_id, **kwargs):
        calls.append(kwargs)
        n = len(calls)
        return {"order_id": uuid.uuid4(), "number": f"POS-{n:04d}", "grand_total": "50.00"}

    monkeypatch.setattr(PosService, "sell", staticmethod(fake_sell))
    app = _build_app(MemoryStore(), uuid.uuid4())
    path = MONEY_ROUTES["sell"][0]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        first = await client.post(path, json=SELL_BODY, headers={KEY_HEADER: "sell-1"})
        second = await client.post(path, json=SELL_BODY, headers={KEY_HEADER: "sell-1"})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json(), "a retry must return the FIRST sale's receipt"
    assert second.headers.get("idempotency-replayed") == "true"
    assert len(calls) == 1, "a retried Pay tap must not sell twice"


async def test_sell_key_reuse_with_a_different_cart_is_refused(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_sell(session, tenant_id, session_id, **kwargs):
        calls.append(kwargs)
        return {"order_id": uuid.uuid4(), "number": "POS-0001", "grand_total": "50.00"}

    monkeypatch.setattr(PosService, "sell", staticmethod(fake_sell))
    app = _build_app(MemoryStore(), uuid.uuid4())
    path = MONEY_ROUTES["sell"][0]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        await client.post(path, json=SELL_BODY, headers={KEY_HEADER: "sell-2"})
        conflict = await client.post(path, json=OTHER_SELL_BODY, headers={KEY_HEADER: "sell-2"})

    assert conflict.status_code == 409, conflict.text
    assert len(calls) == 1


async def test_sell_without_a_key_keeps_the_old_behaviour(monkeypatch) -> None:
    """Opt-in: existing clients that send no key are unchanged."""
    calls: list[dict] = []

    async def fake_sell(session, tenant_id, session_id, **kwargs):
        calls.append(kwargs)
        return {"order_id": uuid.uuid4(), "number": f"POS-{len(calls):04d}", "grand_total": "50.00"}

    monkeypatch.setattr(PosService, "sell", staticmethod(fake_sell))
    app = _build_app(MemoryStore(), uuid.uuid4())
    path = MONEY_ROUTES["sell"][0]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        await client.post(path, json=SELL_BODY)
        await client.post(path, json=SELL_BODY)

    assert len(calls) == 2


@pytest.mark.parametrize("name", ["refund", "return", "exchange", "cash_movement"])
async def test_every_other_pos_money_route_is_retry_safe(monkeypatch, name) -> None:
    """refund / return / exchange / cash-movement: a replay must not repeat the effect."""
    path, body, service_method = MONEY_ROUTES[name]
    calls: list[int] = []

    async def fake(*args, **kwargs):
        calls.append(1)
        return _fake_result(name)

    # A wrong name must FAIL loudly: a skip here would hide an unguarded money route.
    assert hasattr(PosService, service_method), f"PosService.{service_method} does not exist"
    monkeypatch.setattr(PosService, service_method, staticmethod(fake))
    app = _build_app(MemoryStore(), uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        first = await client.post(path, json=body, headers={KEY_HEADER: f"{name}-1"})
        second = await client.post(path, json=body, headers={KEY_HEADER: f"{name}-1"})

    assert first.status_code < 500, first.text
    assert second.headers.get("idempotency-replayed") == "true", (
        f"{name} is not guarded: a retry re-ran the money effect"
    )
    assert len(calls) == 1


def _fake_result(name: str) -> Any:
    """The exact shape each route reads from its service call."""
    from datetime import UTC, datetime
    from types import SimpleNamespace

    if name == "return":
        return {"receipt_id": uuid.uuid4(), "number": "POS-RET-1", "refund_total": "10.00"}
    if name == "exchange":
        return {
            "return_receipt_id": uuid.uuid4(),
            "new_receipt_id": uuid.uuid4(),
            "net": "0.00",
        }
    if name == "cash_movement":
        return SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            direction="out",
            reason="pay_out",
            amount="20.00",
            reference_id=None,
            created_at=datetime.now(UTC),
            created_by=None,
        )
    return {"order_id": uuid.uuid4(), "refund_id": uuid.uuid4(), "amount": "10.00"}


# ---------------------------------------------------------------------------
# DB-backed: the real route, the real service, real stock, real drawer
# ---------------------------------------------------------------------------


async def test_a_retried_sell_charges_once_against_the_database(db, tenant_ctx) -> None:
    """The cashier-visible promise: tap Pay twice, the customer pays ONCE."""
    from decimal import Decimal

    import sqlalchemy as sa

    from app.modules.inventory.service import InventoryService
    from app.modules.orders.models import Order
    from tests.test_order_idempotency import SessionStore
    from tests.test_pos_flow import _register, _sellable_variant

    tenant_id = tenant_ctx.tenant_id
    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)  # 5 on hand, price 25.00

    app = _build_app(SessionStore(db), tenant_id)

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            # the drawer row has a real FK to users: the actor must be the seeded owner
            user=AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_id, role_code="owner"),
            tenant_id=tenant_id,
            role_code="owner",
            permission_codes={"pos:write", "pos:read", "orders:write"},
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    path = f"/api/v1/pos/sessions/{pos_session.id}/sell"
    body = {
        "items": [{"variant_id": str(variant.id), "quantity": 1}],
        "tenders": [{"method": "cash", "amount": "25.00"}],
        "tendered_cash": "30.00",
    }
    key = f"sell-{uuid.uuid4().hex}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        first = await client.post(path, json=body, headers={KEY_HEADER: key})
        second = await client.post(path, json=body, headers={KEY_HEADER: key})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json(), "the retry must hand back the SAME receipt"
    assert second.headers.get("idempotency-replayed") == "true"

    orders = (
        (
            await db.execute(
                sa.select(Order).where(Order.tenant_id == tenant_id, Order.channel == "pos")
            )
        )
        .scalars()
        .all()
    )
    assert len(orders) == 1, "two sales were recorded for one tap"

    balances = await InventoryService.list_balances(db, tenant_id)
    mine = [b for b in balances if b.variant_id == variant.id]
    assert mine and mine[0].on_hand == 4, f"stock decremented twice: on_hand={mine[0].on_hand}"

    detail = await PosService.get_session(db, tenant_id, pos_session.id)
    assert detail["inflow"] == Decimal("25.00"), f"drawer booked cash twice: {detail['inflow']}"
