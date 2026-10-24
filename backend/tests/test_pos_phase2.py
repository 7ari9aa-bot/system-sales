"""§189 POS Phase 2 — held carts and refunds.

Two test classes, per AGENT_BRIEF §7:

* **DB-free guards** run everywhere: the new routes are mounted, the new wire
  models validate, and the refund's pure shape rules hold without a database.
* **DB-backed** tests run only where a database URL is configured (CI); conftest
  skips them locally. They are reported as UNVERIFIED when only local runs were
  possible.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.main import create_app
from app.modules.errors import ValidationError

HELD_CARTS_PATH = "/api/v1/pos/sessions/{session_id}/held-carts"
HELD_CART_PATH = "/api/v1/pos/held-carts/{held_cart_id}"


# --------------------------------------------------------- DB-free guards --


def test_phase_two_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {HELD_CARTS_PATH, HELD_CART_PATH} <= paths


def test_hold_cart_wire_validates() -> None:
    from app.modules.pos.router import HoldCartRequest

    body = HoldCartRequest(
        items=[{"variant_id": str(uuid.uuid4()), "quantity": 2}],
        label="Ahmed — 2 shirts",
    )
    assert body.label == "Ahmed — 2 shirts"
    assert body.discount_total is None


def test_hold_cart_wire_needs_at_least_one_item() -> None:
    from app.modules.pos.router import HoldCartRequest

    with pytest.raises(PydanticValidationError):
        HoldCartRequest(items=[])


def test_clean_held_items_normalises_and_refuses_junk() -> None:
    from app.modules.pos.service import PosService

    variant_id = uuid.uuid4()
    clean = PosService._clean_held_items([{"variant_id": str(variant_id), "quantity": "3"}])
    # Quantities are coerced to int, ids canonicalised to str.
    assert clean == [{"variant_id": str(variant_id), "quantity": 3}]

    with pytest.raises(ValidationError):
        PosService._clean_held_items([])
    with pytest.raises(ValidationError):
        PosService._clean_held_items([{"variant_id": "not-a-uuid", "quantity": 1}])
    with pytest.raises(ValidationError):
        PosService._clean_held_items([{"variant_id": str(variant_id), "quantity": 0}])


# ----------------------------------------------------------- DB-backed ----


async def _sellable_variant(db, tenant_ctx, *, price: str, stock: int):
    import uuid as _uuid

    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService

    warehouse = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="بضاعة", slug=f"p-{_uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="قطعة", price=price
    )
    await InventoryService.move(
        db,
        tenant_ctx.tenant_id,
        variant.id,
        warehouse.id,
        direction="in",
        quantity=stock,
        reason="purchase",
    )
    return warehouse, variant


async def _customer(db, tenant_ctx):
    from app.modules.customers.service import CustomerService

    return await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="زبون", source="pos"
    )


async def _open_session(db, tenant_ctx, warehouse):
    from app.modules.pos.service import PosService

    register = await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="REG",
        code=f"REG-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )
    return await PosService.open_session(db, tenant_ctx.tenant_id, register.id)


async def test_hold_cart_round_trip_reserves_nothing(db, tenant_ctx):
    from app.modules.inventory.service import InventoryService
    from app.modules.pos.service import PosService

    warehouse, variant = await _sellable_variant(db, tenant_ctx, price="10.00", stock=5)
    pos_session = await _open_session(db, tenant_ctx, warehouse)
    customer = await _customer(db, tenant_ctx)

    held = await PosService.hold_cart(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        customer_id=customer.id,
        label="Ahmed",
    )
    assert held.id is not None
    assert held.items[0]["quantity"] == 2

    listed = await PosService.list_held_carts(db, tenant_ctx.tenant_id, pos_session.id)
    assert any(h.id == held.id for h in listed)

    # Holding reserves NOTHING — the shelf is exactly where it was.
    balances = await InventoryService.list_balances(db, tenant_ctx.tenant_id)
    mine = [b for b in balances if b.variant_id == variant.id]
    assert mine and mine[0].on_hand == 5
    assert mine[0].reserved == 0

    await PosService.release_held_cart(db, tenant_ctx.tenant_id, held.id)
    remaining = await PosService.list_held_carts(db, tenant_ctx.tenant_id, pos_session.id)
    assert all(h.id != held.id for h in remaining)


async def test_held_cart_cannot_be_parked_on_a_closed_session(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    warehouse, variant = await _sellable_variant(db, tenant_ctx, price="10.00", stock=3)
    pos_session = await _open_session(db, tenant_ctx, warehouse)
    await PosService.close_session(db, tenant_ctx.tenant_id, pos_session.id)
    with pytest.raises(ConflictError):
        await PosService.hold_cart(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
        )
