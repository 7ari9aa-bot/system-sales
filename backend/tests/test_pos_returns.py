"""§189 phase 2 — returns as a first-class POS document.

Two test classes, per AGENT_BRIEF §7: DB-free guards (routes, wire, the pure
return-pricing math) run everywhere; DB-backed tests (the full return flow,
caps, per-method allocation, close arithmetic) run on CI and are reported
UNVERIFIED when only local runs were possible.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.main import create_app

RETURNS_PATH = "/api/v1/pos/sessions/{session_id}/returns"


# --------------------------------------------------------- DB-free guards --


def test_returns_route_is_mounted() -> None:
    paths = set(create_app().openapi()["paths"])
    assert RETURNS_PATH in paths


def test_return_wire_accepts_lines_and_restock() -> None:
    from app.modules.pos.router import ReturnRequest

    body = ReturnRequest(
        order_id=uuid.uuid4(),
        lines=[{"variant_id": str(uuid.uuid4()), "quantity": 2}],
        restock=True,
    )
    assert body.lines[0].quantity == 2
    assert body.restock is True


def test_return_wire_refuses_zero_quantity() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from app.modules.pos.router import ReturnRequest

    with pytest.raises(PydanticValidationError):
        ReturnRequest(
            order_id=uuid.uuid4(),
            lines=[{"variant_id": str(uuid.uuid4()), "quantity": 0}],
        )


def test_return_line_totals_price_at_the_original_sale() -> None:
    from app.modules.pos.service import PosService

    settle = PosService._return_line_totals
    # No discount: the line refunds its original gross.
    assert settle(Decimal("50.00"), Decimal("0"), [(Decimal("25.00"), 2)]) == [
        Decimal("50.00")
    ]
    # Discounted basket: the line takes its proportional share of the discount.
    # gross 60 of subtotal 100 with a 10 discount → 60 − 6 = 54.
    assert settle(Decimal("100.00"), Decimal("10.00"), [(Decimal("60.00"), 1)]) == [
        Decimal("54.00")
    ]
    # A fully-discounted order has no share to hand back.
    assert settle(Decimal("0"), Decimal("10.00"), [(Decimal("25.00"), 1)]) == [
        Decimal("25.00")
    ]
    # Per-line rounding is HALF_UP to the money quantum.
    assert settle(Decimal("3.00"), Decimal("1.00"), [(Decimal("1.00"), 1)]) == [
        Decimal("0.67")
    ]


def test_return_refunds_what_was_paid_for_a_line_discounted_item() -> None:
    """A 50%-off line paid 50 on a 100 price: returning it refunds 50, never 75.

    The old rule treated the line discount as part of one basket-wide discount and shared it out
    by gross, so the discounted item came back at 100 - 25 = 75 (and the plain item at less).
    """
    from app.modules.pos.service import PosService

    settle = PosService._return_line_totals
    d = Decimal
    # A 100 at 50% off (pays 50) + B 100 at no discount (pays 100). Gross 200, discount 50.
    kw = {"sold_net_subtotal": d("150.00")}
    a = settle(d("200.00"), d("50.00"), [(d("100.00"), 1, d("50"))], **kw)
    b = settle(d("200.00"), d("50.00"), [(d("100.00"), 1, d("0"))], **kw)
    assert a == [d("50.00")] and b == [d("100.00")]
    both_lines = [(d("100.00"), 1, d("50")), (d("100.00"), 1, d("0"))]
    assert sum(settle(d("200.00"), d("50.00"), both_lines, **kw)) == d("150.00")


def test_return_shares_only_the_invoice_discount_over_the_net_lines() -> None:
    """Line 50% off + a fixed 30 off the invoice: the 30 is shared over the NET (150), not gross."""
    from app.modules.pos.service import PosService

    d = Decimal
    # Gross 200, line discount 50, invoice discount 30 -> discount_total 80, paid 120.
    lines = [(d("100.00"), 1, d("50")), (d("100.00"), 1, d("0"))]
    got = PosService._return_line_totals(
        d("200.00"), d("80.00"), lines, sold_net_subtotal=d("150.00")
    )
    assert got == [d("40.00"), d("80.00")]  # 50 - 30*50/150, 100 - 30*100/150
    assert sum(got) == d("120.00")  # the customer's actual payment, to the cent


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
        db, tenant_ctx.tenant_id, title="تيشيرت", slug=f"t-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(
        db, tenant_ctx.tenant_id, product.id, status="active"
    )
    variant = await CatalogService.add_variant(
        db, tenant_ctx.tenant_id, product.id, title="مقاس ل", price=price
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
    return variant


async def _customer(db, tenant_ctx):
    from app.modules.customers.service import CustomerService

    return await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="زبون المرتجع", source="pos"
    )


async def test_line_return_refunds_through_the_original_tenders(db, tenant_ctx):
    from sqlalchemy import select

    from app.modules.pos.models import PosCashMovement, PosReceipt
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        tenders=[
            {"method": "cash", "amount": "30.00"},
            {"method": "card", "amount": "20.00"},
        ],
    )

    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    # 25 gross, no discount → the oldest captured tender (cash) eats it all.
    assert Decimal(result["refunded_total"]) == Decimal("25.00")
    assert result["by_method"] == [{"method": "cash", "amount": "25.00"}]
    assert result["receipt_number"].startswith("POS-RET-")

    return_receipt = (
        (
            await db.execute(
                select(PosReceipt).where(PosReceipt.id == result["receipt_id"])
            )
        )
        .scalars()
        .one()
    )
    assert return_receipt.kind == "return"

    # The drawer arithmetic nets the refund: float 0 + 30 − 25 = 5.
    detail = await PosService.get_session(db, tenant_ctx.tenant_id, pos_session.id)
    assert detail["expected_now"] == Decimal("5.00")
    cash_rows = (
        (
            await db.execute(
                select(PosCashMovement).where(PosCashMovement.session_id == pos_session.id)
            )
        )
        .scalars()
        .all()
    )
    reasons = {r.reason for r in cash_rows}
    assert reasons == {"cash_sale", "cash_refund"}


async def test_discounted_return_takes_its_proportional_share(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        discount_total="10.00",
        discount_override=True,  # about the proportional return share, not the ceiling policy
    )
    assert Decimal(sold["grand_total"]) == Decimal("40.00")

    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    # Line gross 25 carries half of the 10 discount → 25 − 5 = 20.
    assert Decimal(result["refunded_total"]) == Decimal("20.00")


async def test_returning_a_line_discounted_item_refunds_what_was_paid(db, tenant_ctx):
    """Real sale: two items at 100, one at 50% off. Paid 150; each comes back at what it cost."""
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    cheap = await _sellable_variant(db, tenant_ctx, price="100.00")
    full = await _sellable_variant(db, tenant_ctx, price="100.00")
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[
            {"variant_id": str(cheap.id), "quantity": 1, "discount_pct": "50"},
            {"variant_id": str(full.id), "quantity": 1},
        ],
        discount_override=True,
    )
    assert Decimal(sold["grand_total"]) == Decimal("150.00")

    def give_back(variant):
        return PosService.return_sale(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )

    assert Decimal((await give_back(cheap))["refunded_total"]) == Decimal("50.00")  # not 75
    assert Decimal((await give_back(full))["refunded_total"]) == Decimal("100.00")


async def test_return_is_capped_at_what_was_sold(db, tenant_ctx):
    from app.modules.errors import ConflictError
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
    )
    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    with pytest.raises(ConflictError):
        await PosService.return_sale(
            db,
            tenant_ctx.tenant_id,
            pos_session.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 2}],
        )


async def test_restock_moves_only_the_returned_quantities(db, tenant_ctx):
    from app.modules.inventory.service import InventoryService
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx, stock=5)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 3}],
    )

    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        restock=True,
    )
    balances = await InventoryService.list_balances(db, tenant_ctx.tenant_id)
    mine = next(b for b in balances if b.variant_id == variant.id)
    # 5 bought − 3 sold + 1 returned = 3.
    assert mine.on_hand == 3

    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 2}],
        restock=True,
    )
    balances = await InventoryService.list_balances(db, tenant_ctx.tenant_id)
    mine = next(b for b in balances if b.variant_id == variant.id)
    assert mine.on_hand == 5


async def test_card_only_return_leaves_the_drawer_alone(db, tenant_ctx):
    from app.modules.pos.service import PosService

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, opening_float="10.00"
    )
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 2}],
        method="card",
    )
    result = await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
    )
    assert result["by_method"] == [{"method": "card", "amount": "25.00"}]

    preview = await PosService.close_preview(db, tenant_ctx.tenant_id, pos_session.id)
    by_method = {r["method"]: Decimal(r["expected"]) for r in preview["by_method"]}
    assert by_method["card"] == Decimal("25.00")  # 50 − 25
    assert by_method["cash"] == Decimal("10.00")  # float untouched

    closed = await PosService.close_session(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        counted_cash="10.00",
        counted_by_method={"cash": "10.00", "card": "25.00"},
    )
    rows = await PosService.list_reconciliation(db, tenant_ctx.tenant_id, closed.id)
    card = next(r for r in rows if r.method == "card")
    assert Decimal(str(card.variance)) == Decimal("0.00")
