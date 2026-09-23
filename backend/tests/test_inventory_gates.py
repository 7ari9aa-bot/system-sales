"""M9/P4 — a stock movement is an accounting event, so writing one is a
permission, not a property of being logged in.

`POST /inventory/movements` took any authenticated member of the tenant
(`TenantCtxDep` only) and let them move `on_hand` wherever they liked — a staff
account that is not even granted `inventory:write` in the seeded role matrix
could invent a restock. `POST /billing/usage` had the same hole for the metering
table the tenant's own invoice is built from (`tests/test_billing_gates.py`).

Both are now gated with the project's own mechanism, `require_permission`
(`identity/deps.py:357`) — 403 `permission_denied`, not a service-layer flag —
because that is what every other write route in the codebase uses
(`catalog/router.py:20`, `billing/router.py:97`).

The first two cases are DB-free and check the ROUTE, so a future refactor that
moves the check into the endpoint body (where a caller could bypass it) shows up
here. The rest drive the real ASGI app and assert the status and the error code.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.identity.deps import (
    AuthedUser,
    TenantContext,
    get_tenant_ctx,
)
from app.modules.inventory.models import InventoryMovement
from app.modules.inventory.router import router as inventory_router


def _permission_codes(routes, path: str, method: str) -> set[str]:
    """RBAC codes a route declares, found by walking its dependency tree."""
    for route in routes:
        if route.path == path and method in route.methods:
            codes: set[str] = set()
            stack = list(route.dependant.dependencies)
            while stack:
                dependant = stack.pop()
                code = getattr(dependant.call, "code", None)
                if code:
                    codes.add(code)
                stack.extend(dependant.dependencies)
            return codes
    raise AssertionError(f"{method} {path} is not routed")


def _app_for(db: AsyncSession, tenant_id: uuid.UUID, *, permissions: set[str]):
    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="staff"),
        tenant_id=tenant_id,
        role_code="staff",
        permission_codes=permissions,
    )

    app = create_app()

    async def _ctx() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


async def _post_movement(app, payload: dict):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/v1/inventory/movements", json=payload)


@pytest.fixture
async def stocked(db: AsyncSession, tenant_ctx):
    """A variant with 10 on hand, recorded the way the module records it: one
    `in`/purchase ledger row, so "nothing was written" is a count of 1."""
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.models import Warehouse
    from app.modules.inventory.service import InventoryService

    warehouse = Warehouse(
        tenant_id=tenant_ctx.tenant_id,
        name="Gate WH",
        code=f"GW-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="Gate Product", slug=f"g-{uuid.uuid4().hex[:10]}"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, price="10.00"
    )
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=10,
        reason="purchase",
    )
    return variant, warehouse


async def _ledger_count(db: AsyncSession, variant) -> int:
    """Rows on the ledger for this variant — 1 means 'nothing was written'."""
    return (
        await db.execute(
            select(func.count())
            .select_from(InventoryMovement)
            .where(InventoryMovement.variant_id == variant.id)
        )
    ).scalar_one()


def _movement_payload(variant, warehouse, **over) -> dict:
    payload = {
        "variant_id": str(variant.id),
        "warehouse_id": str(warehouse.id),
        "direction": "in",
        "quantity": 5,
        "reason": "purchase",
    }
    payload.update(over)
    return payload


# ------------------------------------------------------------- the routes -----


def test_recording_a_movement_requires_inventory_write() -> None:
    assert _permission_codes(
        inventory_router.routes, "/inventory/movements", "POST"
    ) == {"inventory:write"}


def test_reading_the_ledger_stays_open_to_every_member() -> None:
    """The gate is on the write. Staff are granted `inventory:read` and must keep
    seeing balances and the ledger; a read gate would be a second, unseeded
    permission surface."""
    assert _permission_codes(inventory_router.routes, "/inventory/movements", "GET") == set()
    assert _permission_codes(inventory_router.routes, "/inventory/balances", "GET") == set()


# --------------------------------------------------------- refusal, for real --


async def test_the_movement_route_refuses_a_member_without_the_permission(
    db: AsyncSession, tenant_ctx, stocked
) -> None:
    variant, warehouse = stocked
    app = _app_for(db, tenant_ctx.tenant_id, permissions={"inventory:read"})

    response = await _post_movement(app, _movement_payload(variant, warehouse))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert await _ledger_count(db, variant) == 1  # only the fixture's row


async def test_the_movement_route_accepts_a_member_who_has_it(
    db: AsyncSession, tenant_ctx, stocked
) -> None:
    from app.modules.inventory.service import InventoryService

    variant, warehouse = stocked
    app = _app_for(db, tenant_ctx.tenant_id, permissions={"inventory:write"})

    response = await _post_movement(
        app, _movement_payload(variant, warehouse, direction="out", quantity=2, reason="damage")
    )

    assert response.status_code == 201, response.text
    balance = await InventoryService.get_balance(
        db, tenant_ctx.tenant_id, variant.id, warehouse.id
    )
    assert balance.on_hand == 8
    reason = (
        await db.execute(
            select(InventoryMovement.reason).where(
                InventoryMovement.variant_id == variant.id,
                InventoryMovement.direction == "out",
            )
        )
    ).scalar_one()
    assert reason == "damage"


@pytest.mark.parametrize("reason", ["lost-and-found", "Reservation", ""])
async def test_a_junk_reason_is_refused_before_anything_is_written(
    db: AsyncSession, tenant_ctx, stocked, reason: str
) -> None:
    """M9's other half: the gate says WHO may write; the closed vocabulary says
    WHAT may be written. 422 from the request model, and no ledger row."""
    variant, warehouse = stocked
    app = _app_for(db, tenant_ctx.tenant_id, permissions={"inventory:write"})

    response = await _post_movement(
        app, _movement_payload(variant, warehouse, quantity=1, reason=reason)
    )

    assert response.status_code == 422
    assert await _ledger_count(db, variant) == 1
