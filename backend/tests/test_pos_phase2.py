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
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.main import create_app
from app.modules.errors import ValidationError

HELD_CARTS_PATH = "/api/v1/pos/sessions/{session_id}/held-carts"
HELD_CART_PATH = "/api/v1/pos/held-carts/{held_cart_id}"
REFUND_PATH = "/api/v1/pos/sessions/{session_id}/refunds"


# --------------------------------------------------------- DB-free guards --


def test_phase_two_routes_are_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert {HELD_CARTS_PATH, HELD_CART_PATH, REFUND_PATH} <= paths


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


def test_refund_wire_defaults_to_cash_and_no_restock() -> None:
    from app.modules.pos.router import RefundRequest

    body = RefundRequest(order_id=uuid.uuid4(), amount="25.00")
    assert body.method == "cash"
    assert body.restock is False
    assert body.reason == "customer_return"


def test_refund_wire_refuses_unknown_method() -> None:
    from app.modules.pos.router import RefundRequest

    with pytest.raises(PydanticValidationError):
        RefundRequest(order_id=uuid.uuid4(), amount="25.00", method="crypto")


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
    await PosService.close_session(db, tenant_ctx.tenant_id, pos_session.id, counted_cash="0.00")
    with pytest.raises(ConflictError):
        await PosService.hold_cart(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
        )


async def test_refund_is_a_ledger_row_capped_by_capture(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    warehouse, variant = await _sellable_variant(db, tenant_ctx, price="20.00", stock=5)
    pos_session = await _open_session(db, tenant_ctx, warehouse)
    customer = await _customer(db, tenant_ctx)

    sale = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        method="cash",
        amount="20.00",
    )
    assert sale["grand_total"] == "20.00"

    # A refund larger than the sale captured is refused by the orders ledger.
    with pytest.raises(ConflictError):
        await PosService.refund(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            order_id=sale["order_id"],
            amount="25.00",
            method="cash",
        )

    # The honest refund is recorded and the drawer shows it leaving.
    result = await PosService.refund(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sale["order_id"],
        amount="20.00",
        method="cash",
    )
    assert result["amount"] == "20.00"

    detail = await PosService.get_session(db, tenant_ctx.tenant_id, pos_session.id)
    # 20.00 in from the sale, 20.00 out from the refund → drawer back to zero.
    assert detail["inflow"] == Decimal("20.00")
    assert detail["outflow"] == Decimal("20.00")


async def test_money_only_refund_never_puts_goods_back_on_the_shelf(db, tenant_ctx):
    """A money-only refund cannot know which goods came back, so ``restock`` is ignored."""
    from app.modules.inventory.service import InventoryService
    from app.modules.pos.service import PosService

    warehouse, variant = await _sellable_variant(db, tenant_ctx, price="15.00", stock=4)
    pos_session = await _open_session(db, tenant_ctx, warehouse)
    customer = await _customer(db, tenant_ctx)

    sale = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        method="cash",
        amount="30.00",
    )

    result = await PosService.refund(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sale["order_id"],
        amount="30.00",
        method="cash",
        restock=True,
    )
    assert result["restocked"] is False

    balances = await InventoryService.list_balances(db, tenant_ctx.tenant_id)
    mine = [b for b in balances if b.variant_id == variant.id]
    assert mine and mine[0].on_hand == 2  # still the 4 - 2 sold; nothing came back


async def test_refund_of_a_foreign_session_is_refused(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    warehouse, variant = await _sellable_variant(db, tenant_ctx, price="5.00", stock=5)
    first = await _open_session(db, tenant_ctx, warehouse)
    customer = await _customer(db, tenant_ctx)
    sale = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        first.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        method="cash",
        amount="5.00",
    )
    await PosService.close_session(db, tenant_ctx.tenant_id, first.id, counted_cash="5.00")

    # A SECOND open session on a different register must not refund the first's
    # sale — that would move money between two drawers.
    register2 = await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="REG2",
        code=f"REG-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )
    second = await PosService.open_session(db, tenant_ctx.tenant_id, register2.id)

    with pytest.raises(ConflictError):
        await PosService.refund(
            db,
            tenant_ctx.tenant_id,
            second.id,
            order_id=sale["order_id"],
            amount="5.00",
            method="cash",
        )
