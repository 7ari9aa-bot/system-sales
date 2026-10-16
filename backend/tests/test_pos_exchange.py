"""§189 — the one-transaction exchange (beyond ERPNext and Odoo).

DB-free guards (routes, wire) run everywhere; DB-backed flows (equal-value
swap, customer-owes, shop-owes, caps, drawer arithmetic) run on CI and are
reported UNVERIFIED when only local runs were possible (AGENT_BRIEF §3a).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.main import create_app

EXCHANGES_PATH = "/api/v1/pos/sessions/{session_id}/exchanges"


# --------------------------------------------------------- DB-free guards --


def test_exchanges_route_is_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert EXCHANGES_PATH in paths


def test_exchange_wire_requires_both_halves() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from app.modules.pos.router import ExchangeRequest

    with pytest.raises(PydanticValidationError):
        ExchangeRequest(
            order_id=uuid.uuid4(),
            return_lines=[{"variant_id": str(uuid.uuid4()), "quantity": 1}],
            new_lines=[],
        )
    body = ExchangeRequest(
        order_id=uuid.uuid4(),
        return_lines=[{"variant_id": str(uuid.uuid4()), "quantity": 1}],
        new_lines=[{"variant_id": str(uuid.uuid4()), "quantity": 2}],
        tenders=[{"method": "cash", "amount": "15.00"}],
    )
    assert body.new_lines[0].quantity == 2


# ----------------------------------------------------------- DB-backed -----


async def _warehouse(db, tenant_ctx):
    from app.modules.inventory.service import InventoryService

    return await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)


async def _register(db, tenant_ctx):
    from app.modules.pos.service import PosService

    warehouse = await _warehouse(db, tenant_ctx)
    return await PosService.create_register(
        db,
        tenant_ctx.tenant_id,
        name="كاشير",
        code=f"REG-{uuid.uuid4().hex[:6]}",
        warehouse_id=warehouse.id,
    )


async def _sellable_variant(db, tenant_ctx, price="25.00", stock=10):
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService

    warehouse = await _warehouse(db, tenant_ctx)
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="صنف", slug=f"x-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="وحدة", price=price
    )
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, warehouse.id,
        direction="in", quantity=stock, reason="purchase",
    )
    return variant


async def _customer(db, tenant_ctx):
    from app.modules.customers.service import CustomerService

    return await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="زبون الاستبدال", source="pos"
    )


async def test_equal_value_swap_moves_no_money(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    sold_variant = await _sellable_variant(db, tenant_ctx)
    new_variant = await _sellable_variant(db, tenant_ctx, price="25.00")
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(sold_variant.id), "quantity": 1}],
        tenders=[
            {"method": "cash", "amount": "15.00"},
            {"method": "card", "amount": "10.00"},
        ],
    )

    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(sold_variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(new_variant.id), "quantity": 1}],
        restock=True,
    )
    # 25 credited pays the 25 replacement: pure swap, net zero.
    assert Decimal(result["return_total"]) == Decimal("25.00")
    assert Decimal(result["new_total"]) == Decimal("25.00")
    assert Decimal(result["net"]) == Decimal("0.00")
    assert result["return_receipt_number"].startswith("POS-RET-")
    assert result["new_receipt_number"].startswith("POS-")

    # The drawer never moved for the swap: the credit's refund legs and the
    # funding payments are the double-entry pair (in 15 + 15, out 15).
    detail = await PosService.get_session(db, tenant_ctx.tenant_id, pos_session.id)
    assert detail["inflow"] == Decimal("30.00")
    assert detail["outflow"] == Decimal("15.00")

    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, pos_session.id)
    by_method = {r["method"]: Decimal(r["expected"]) for r in preview["by_method"]}
    # card: captured 10 + funded 10 − refunded 10 = 10; cash: in 30 − out 15 = 15.
    assert by_method["card"] == Decimal("10.00")
    assert by_method["cash"] == Decimal("15.00")
    assert preview["invoice_count"] == 2  # the sale AND its replacement


async def test_exchange_for_a_pricier_item_charges_the_difference(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    sold_variant = await _sellable_variant(db, tenant_ctx)
    new_variant = await _sellable_variant(db, tenant_ctx, price="40.00")
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(sold_variant.id), "quantity": 1}],
        method="cash",
    )
    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(sold_variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(new_variant.id), "quantity": 1}],
        tenders=[{"method": "cash", "amount": "15.00"}],
        tendered_cash="20.00",
    )
    assert Decimal(result["net"]) == Decimal("15.00")
    detail = await PosService.get_session(db, tenant_ctx.tenant_id, pos_session.id)
    # Double-entry: sale cash 25 in + funding 25 in − refund 25 out + tender
    # 15 in − change 5 out → inflow 65, outflow 30, expected 40. The customer
    # physically paid 15 net.
    assert detail["inflow"] == Decimal("65.00")
    assert detail["outflow"] == Decimal("25.00")


async def test_exchange_tenders_must_total_the_difference(db, tenant_ctx):
    from app.modules.errors import ValidationError
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    sold_variant = await _sellable_variant(db, tenant_ctx)
    new_variant = await _sellable_variant(db, tenant_ctx, price="40.00")
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(sold_variant.id), "quantity": 1}],
        method="cash",
    )
    with pytest.raises(ValidationError):
        await PosService.exchange(
            db, tenant_ctx.tenant_id, pos_session.id,
            order_id=sold["order_id"],
            return_lines=[{"variant_id": str(sold_variant.id), "quantity": 1}],
            new_lines=[{"variant_id": str(new_variant.id), "quantity": 1}],
            tenders=[{"method": "cash", "amount": "20.00"}],  # net is 15
        )


async def test_exchange_for_a_cheaper_item_refunds_via_original_tenders(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opening_float="20.00"
    )
    sold_variant = await _sellable_variant(db, tenant_ctx)
    new_variant = await _sellable_variant(db, tenant_ctx, price="10.00")
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(sold_variant.id), "quantity": 2}],
        tenders=[
            {"method": "cash", "amount": "30.00"},
            {"method": "card", "amount": "20.00"},
        ],
    )
    result = await PosService.exchange(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(sold_variant.id), "quantity": 2}],
        new_lines=[{"variant_id": str(new_variant.id), "quantity": 1}],
    )
    # The FULL return value refunds across the original tenders, cash first:
    # 30 cash leaves the drawer, 20 card is refunded — and the 10 replacement
    # is funded from the card credit.
    assert Decimal(result["net"]) == Decimal("-40.00")
    assert result["by_method"] == [
        {"method": "cash", "amount": "30.00"},
        {"method": "card", "amount": "20.00"},
    ]

    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, pos_session.id)
    by_method = {r["method"]: Decimal(r["expected"]) for r in preview["by_method"]}
    # cash: float 20 + 30 in from the sale − 30 out as the refund = 20 (the
    # double-entry legs cancel; the drawer keeps its float); card: 20 captured
    # + 10 funded − 20 refunded = 10.
    assert by_method["cash"] == Decimal("20.00")
    assert by_method["card"] == Decimal("10.00")


async def test_exchange_is_capped_like_a_return(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    sold_variant = await _sellable_variant(db, tenant_ctx)
    new_variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(sold_variant.id), "quantity": 2}],
    )
    await PosService.exchange(
        db, tenant_ctx.tenant_id, pos_session.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(sold_variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(new_variant.id), "quantity": 1}],
    )
    with pytest.raises(ConflictError):
        await PosService.exchange(
            db, tenant_ctx.tenant_id, pos_session.id,
            order_id=sold["order_id"],
            return_lines=[{"variant_id": str(sold_variant.id), "quantity": 2}],
            new_lines=[{"variant_id": str(new_variant.id), "quantity": 2}],
        )


async def test_exchange_event_is_staged(db, tenant_ctx):
    from app.modules.platform.models import OutboxEvent
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    sold_variant = await _sellable_variant(db, tenant_ctx)
    new_variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(sold_variant.id), "quantity": 1}],
    )
    await PosService.exchange(
        db, tenant_ctx.tenant_id, pos_session.id,
        order_id=sold["order_id"],
        return_lines=[{"variant_id": str(sold_variant.id), "quantity": 1}],
        new_lines=[{"variant_id": str(new_variant.id), "quantity": 1}],
    )
    staged = (
        (
            await db.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_type == "pos_session")
            )
        )
        .scalars()
        .all()
    )
    assert any("pos.sale.exchanged" in e.payload for e in staged)
