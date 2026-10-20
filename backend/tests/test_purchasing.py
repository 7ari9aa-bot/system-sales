"""PURCHASING: receiving moves stock and cost once; balances are derived; money never rounds."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.main import create_app
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.service import InventoryService
from app.modules.orders.errors import InsufficientStockError
from app.modules.purchasing.service import (
    CostService,
    PurchaseService,
    SupplierPaymentService,
    SupplierReturnService,
    SupplierService,
    moving_average,
    positive_int,
)

D = Decimal


# ------------------------------------------------------------ pure maths ----


@pytest.mark.parametrize(
    ("on_hand", "avg", "qty", "cost", "expected"),
    [
        (0, "0", 10, "100", "100.0000"),  # nothing on the shelf: the incoming cost IS the cost
        (10, "100", 10, "120", "110.0000"),  # (10*100 + 10*120) / 20
        (10, "100", 5, "130", "110.0000"),  # (1000 + 650) / 15
        (3, "10", 4, "12", "11.1429"),  # (30 + 48) / 7 = 11.142857...
        (1, "0.01", 1, "0.02", "0.0150"),  # tiny costs keep their 4 places
        (-4, "50", 10, "70", "70.0000"),  # oversold: nothing real to average against
        (5, "80", 3, "0", "50.0000"),  # a free (bonus) line lowers the average: (400 + 0) / 8
    ],
)
def test_moving_average(on_hand, avg, qty, cost, expected) -> None:
    assert moving_average(on_hand, D(avg), qty, D(cost)) == D(expected)


def test_moving_average_refuses_a_non_positive_receipt() -> None:
    for qty in (0, -1):
        with pytest.raises(ValidationError):
            moving_average(5, D("10"), qty, D("10"))


@pytest.mark.parametrize("bad", ["0", "-2", "1.5", "abc", "", "1e3", None, 2_000_000])
def test_quantity_must_be_a_positive_whole_number(bad) -> None:
    with pytest.raises(ValidationError):
        positive_int(bad)


@pytest.mark.parametrize(("good", "out"), [(3, 3), ("7", 7), ("4.0", 4), (" 9 ", 9)])
def test_quantity_accepts_whole_numbers(good, out) -> None:
    assert positive_int(good) == out


def test_purchasing_routes_are_mounted_and_guarded_against_double_submit() -> None:
    from app.core.idempotency import IDEMPOTENT_PATHS

    paths = set(create_app().openapi()["paths"])
    wanted = {
        "/api/v1/suppliers",
        "/api/v1/purchase-orders",
        "/api/v1/purchase-orders/{order_id}/receive",
        "/api/v1/supplier-payments",
        "/api/v1/supplier-returns",
    }
    assert wanted <= paths
    for prefix in (
        "/api/v1/purchase-orders",
        "/api/v1/supplier-payments",
        "/api/v1/supplier-returns",
    ):
        assert prefix in IDEMPOTENT_PATHS


# ----------------------------------------------------------- DB-backed -----


async def _supplier(db, tenant_ctx, name=None):
    return await SupplierService.create(
        db, tenant_ctx.tenant_id, name=name or f"مورد {uuid.uuid4().hex[:6]}"
    )


async def _variant(db, tenant_ctx, price="100.00"):
    product = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="تيشيرت", slug=f"p-{uuid.uuid4().hex[:10]}"
    )
    return await CatalogService.add_variant(db, tenant_ctx.tenant_id, product.id, price=price)


async def _shift(db, tenant_ctx, opening="500.00"):
    from app.modules.pos.service import PosService

    wh = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    reg = await PosService.create_register(
        db, tenant_ctx.tenant_id, name="كاشير", code=f"R-{uuid.uuid4().hex[:6]}", warehouse_id=wh.id
    )
    return await PosService.open_session(db, tenant_ctx.tenant_id, reg.id, opening_float=opening)


async def _cash_totals(db, tenant_ctx, shift):
    from app.modules.pos.service import PosService

    return await PosService._cash_totals(db, tenant_ctx.tenant_id, shift.id)


async def _po(db, tenant_ctx, supplier, variant, qty=10, cost="100.00", receive=True, **kw):
    return await PurchaseService.create(
        db,
        tenant_ctx.tenant_id,
        supplier_id=supplier.id,
        lines=[{"variant_id": str(variant.id), "quantity": qty, "unit_cost": cost}],
        receive_now=receive,
        **kw,
    )


async def _on_hand(db, tenant_ctx, variant):
    return await InventoryService.total_on_hand(db, tenant_ctx.tenant_id, variant.id)


async def test_receiving_puts_stock_on_the_shelf_and_sets_the_cost(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, qty=10, cost="100.00")
    assert po.status == "received" and po.received_at is not None and po.total == D("1000.00")
    assert po.number.startswith("PO-")
    assert await _on_hand(db, tenant_ctx, var) == 10
    assert await CostService.get(db, tenant_ctx.tenant_id, var.id) == D("100.0000")
    movement = (
        await db.execute(
            text(
                "select direction, reason, quantity, reference_type, reference_id from "
                "inventory_movements "
                "where variant_id=:v"
            ),
            {"v": var.id},
        )
    ).one()
    assert (movement.direction, movement.reason, movement.quantity, movement.reference_type) == (
        "in",
        "purchase",
        10,
        "purchase_order",
    )
    assert movement.reference_id == po.id


async def test_stock_with_no_recorded_cost_is_not_averaged_in_as_free(db, tenant_ctx) -> None:
    """Stock on the shelf BEFORE any purchase was recorded has an UNKNOWN cost, not a zero one.
    Averaging it as free would make every cost too low from the first delivery on
    (and every profit too high)."""
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    wh = await InventoryService.get_default_warehouse(db, t)
    await InventoryService.move(
        db, t, var.id, wh.id, direction="in", quantity=5, reason="adjustment"
    )  # opening stock
    assert await CostService.get(db, t, var.id) is None
    await _po(db, tenant_ctx, sup, var, qty=10, cost="100.00")
    assert await _on_hand(db, tenant_ctx, var) == 15
    assert await CostService.get(db, t, var.id) == D("100.0000")  # NOT 66.6667
    first = (
        await db.execute(
            text(
                "select old_avg_cost, new_avg_cost, on_hand_before from variant_cost_history "
                "where variant_id=:v"
            ),
            {"v": var.id},
        )
    ).one()
    assert (
        first.old_avg_cost is None and first.on_hand_before == 5
    )  # the history says the old cost was unknown
    await _po(
        db, tenant_ctx, sup, var, qty=15, cost="120.00"
    )  # now the average is real: (15*100 + 15*120) / 30
    assert await CostService.get(db, t, var.id) == D("110.0000")


async def test_a_genuinely_free_delivery_is_a_known_zero_cost_not_an_unknown_one(
    db, tenant_ctx
) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    await _po(db, tenant_ctx, sup, var, qty=4, cost="0")
    assert await CostService.get(db, t, var.id) == D("0.0000")  # known: zero
    await _po(db, tenant_ctx, sup, var, qty=4, cost="10.00")
    assert await CostService.get(db, t, var.id) == D(
        "5.0000"
    )  # (4*0 + 4*10) / 8: the zero WAS known, so it counts


async def test_second_receipt_averages_against_what_is_on_the_shelf(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    await _po(db, tenant_ctx, sup, var, qty=10, cost="100.00")
    await _po(db, tenant_ctx, sup, var, qty=10, cost="120.00")
    assert await _on_hand(db, tenant_ctx, var) == 20
    assert await CostService.get(db, tenant_ctx.tenant_id, var.id) == D("110.0000")
    hist = (
        await db.execute(
            text(
                "select old_avg_cost, new_avg_cost, on_hand_before, received_quantity, unit_cost "
                "from variant_cost_history where variant_id=:v order by on_hand_before"
            ),
            {"v": var.id},
        )
    ).all()
    assert [(h.on_hand_before, h.received_quantity) for h in hist] == [(0, 10), (10, 10)]
    assert hist[1].old_avg_cost == D("100.0000") and hist[1].new_avg_cost == D("110.0000")


async def test_sales_between_receipts_change_the_weight_of_the_old_cost(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    wh = await InventoryService.get_default_warehouse(db, tenant_ctx.tenant_id)
    await _po(db, tenant_ctx, sup, var, qty=10, cost="100.00")
    await InventoryService.move(
        db, tenant_ctx.tenant_id, var.id, wh.id, direction="out", quantity=8, reason="sale"
    )
    await _po(db, tenant_ctx, sup, var, qty=8, cost="130.00")  # 2 left @100 + 8 @130 = 10 units
    assert await CostService.get(db, tenant_ctx.tenant_id, var.id) == D(
        "124.0000"
    )  # (200 + 1040) / 10


async def test_receiving_twice_is_refused_and_changes_nothing(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, qty=5, cost="50.00")
    with pytest.raises(ConflictError, match="already received"):
        await PurchaseService.receive(db, tenant_ctx.tenant_id, po.id)
    assert await _on_hand(db, tenant_ctx, var) == 5
    assert await CostService.get(db, tenant_ctx.tenant_id, var.id) == D("50.0000")


async def test_a_draft_moves_nothing_until_it_is_received(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, receive=False)
    assert po.status == "draft" and po.received_at is None
    assert await _on_hand(db, tenant_ctx, var) == 0
    assert await CostService.get(db, tenant_ctx.tenant_id, var.id) is None
    await PurchaseService.receive(db, tenant_ctx.tenant_id, po.id)
    assert await _on_hand(db, tenant_ctx, var) == 10


async def test_cancel_rules(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    draft = await _po(db, tenant_ctx, sup, var, receive=False)
    await PurchaseService.cancel(db, tenant_ctx.tenant_id, draft.id)
    assert draft.status == "cancelled"
    with pytest.raises(ConflictError, match="already cancelled"):
        await PurchaseService.cancel(db, tenant_ctx.tenant_id, draft.id)
    with pytest.raises(ConflictError, match="cancelled purchase order cannot be received"):
        await PurchaseService.receive(db, tenant_ctx.tenant_id, draft.id)
    received = await _po(db, tenant_ctx, sup, var)
    with pytest.raises(ConflictError, match="supplier return instead"):
        await PurchaseService.cancel(db, tenant_ctx.tenant_id, received.id)
    assert received.status == "received" and await _on_hand(db, tenant_ctx, var) == 10


@pytest.mark.parametrize(
    ("lines", "msg"),
    [
        ([], "at least one line"),
        ([{"variant_id": "nope", "quantity": 1, "unit_cost": "5"}], "variant_id is not valid"),
        ([{"variant_id": None, "quantity": 1, "unit_cost": "5"}], "variant_id is not valid"),
    ],
)
async def test_bad_lines_are_refused(db, tenant_ctx, lines, msg) -> None:
    sup = await _supplier(db, tenant_ctx)
    with pytest.raises(ValidationError, match=msg):
        await PurchaseService.create(db, tenant_ctx.tenant_id, supplier_id=sup.id, lines=lines)


async def test_money_and_quantity_are_checked_per_line(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    for qty, cost, msg in [
        (0, "5", "greater than zero"),
        (1.5, "5", "whole number"),
        (1, "5.005", "2 decimal"),
        (1, "-1", "greater than zero"),
        (1, "abc", "valid number"),
    ]:
        with pytest.raises(ValidationError, match=msg):
            await _po(db, tenant_ctx, sup, var, qty=qty, cost=cost, receive=False)
    await _po(db, tenant_ctx, sup, var, qty=1, cost="0", receive=False)  # a free line is legitimate


async def test_lines_keep_the_order_they_were_entered_in(db, tenant_ctx) -> None:
    """Lines of one document share the transaction's created_at: only `position` can order them."""
    t = tenant_ctx.tenant_id
    sup = await _supplier(db, tenant_ctx)
    variants = [await _variant(db, tenant_ctx) for _ in range(6)]
    order = await PurchaseService.create(
        db,
        t,
        supplier_id=sup.id,
        lines=[
            {"variant_id": str(v.id), "quantity": i + 1, "unit_cost": "10"}
            for i, v in enumerate(variants)
        ],
    )
    for _ in range(5):  # a shuffled read would show up as a different order on some pass
        got = [
            (ln.variant_id, ln.position, ln.quantity)
            for ln in await PurchaseService._lines_in(db, t, order.id)
        ]
        assert got == [(v.id, i + 1, i + 1) for i, v in enumerate(variants)]


async def test_two_lines_cannot_claim_the_same_place_on_a_document(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, receive=False)
    dup = text(
        "insert into purchase_order_lines (id, tenant_id, purchase_order_id, variant_id, "
        "quantity, unit_cost, line_total, position) "
        "values (gen_random_uuid(), :t, :p, :v, 1, 5, 5, :pos)"
    )
    base = {"t": tenant_ctx.tenant_id, "p": po.id, "v": var.id}
    await _must_fail(db, dup, {**base, "pos": 1})  # _po already holds position 1
    await _must_fail(db, dup, {**base, "pos": 0})  # positions start at 1


async def test_the_same_variant_twice_and_unknown_things_are_refused(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    line = {"variant_id": str(var.id), "quantity": 1, "unit_cost": "5"}
    with pytest.raises(ValidationError, match="appears twice"):
        await PurchaseService.create(
            db, tenant_ctx.tenant_id, supplier_id=sup.id, lines=[line, line]
        )
    with pytest.raises(NotFoundError):
        await PurchaseService.create(
            db,
            tenant_ctx.tenant_id,
            supplier_id=sup.id,
            lines=[{"variant_id": str(uuid.uuid4()), "quantity": 1, "unit_cost": "5"}],
        )
    with pytest.raises(NotFoundError):
        await PurchaseService.create(
            db, tenant_ctx.tenant_id, supplier_id=uuid.uuid4(), lines=[line]
        )


async def test_an_inactive_supplier_cannot_receive_new_orders(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    await SupplierService.update(db, tenant_ctx.tenant_id, sup.id, status="inactive")
    with pytest.raises(ConflictError, match="inactive"):
        await _po(db, tenant_ctx, sup, var)


async def test_supplier_names_are_unique_per_shop_ignoring_case(db, tenant_ctx) -> None:
    await _supplier(db, tenant_ctx, "شركة النيل")
    with pytest.raises(ConflictError, match="already exists"):
        await _supplier(db, tenant_ctx, "  شركة النيل ")
    await _supplier(db, tenant_ctx, "Nile Co")
    with pytest.raises(ConflictError):
        await _supplier(db, tenant_ctx, "nile co")


# -------------------------------------------- balance, payments, drawer ----


async def test_balance_is_derived_from_documents_and_credit_buying_works(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    st = await SupplierService.statement(db, t, sup.id)
    assert st["balance"] == D("0.00") and st["orders_count"] == 0 and st["last_order_date"] is None
    po = await _po(
        db, tenant_ctx, sup, var, qty=10, cost="100.00"
    )  # received, NOT paid: bought on credit
    st = await SupplierService.statement(db, t, sup.id)
    assert (st["total_supplied"], st["paid"], st["balance"], st["items_count"]) == (
        D("1000.00"),
        D("0.00"),
        D("1000.00"),
        1,
    )
    await SupplierPaymentService.create(
        db, t, supplier_id=sup.id, purchase_order_id=po.id, amount="400", method="bank_transfer"
    )
    st = await SupplierService.statement(db, t, sup.id)
    assert st["paid"] == D("400.00") and st["balance"] == D("600.00")
    assert (
        PurchaseService.payment_state(po.total, await PurchaseService.paid_for(db, t, po.id))
        == "partial"
    )
    await SupplierPaymentService.create(
        db, t, supplier_id=sup.id, purchase_order_id=po.id, amount="600", method="card"
    )
    assert (
        PurchaseService.payment_state(po.total, await PurchaseService.paid_for(db, t, po.id))
        == "paid"
    )
    assert (await SupplierService.statement(db, t, sup.id))["balance"] == D("0.00")


async def test_a_draft_or_cancelled_order_is_not_a_debt(db, tenant_ctx) -> None:
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    await _po(db, tenant_ctx, sup, var, receive=False)
    cancelled = await _po(db, tenant_ctx, sup, var, receive=False)
    await PurchaseService.cancel(db, tenant_ctx.tenant_id, cancelled.id)
    assert (await SupplierService.statement(db, tenant_ctx.tenant_id, sup.id))["balance"] == D(
        "0.00"
    )


async def test_payments_cannot_exceed_what_is_owed_or_target_the_wrong_order(
    db, tenant_ctx
) -> None:
    t = tenant_ctx.tenant_id
    a, b = await _supplier(db, tenant_ctx), await _supplier(db, tenant_ctx)
    var = await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, a, var, qty=2, cost="50.00")  # owes 100
    with pytest.raises(ConflictError, match="more than what is still owed"):
        await SupplierPaymentService.create(
            db, t, supplier_id=a.id, purchase_order_id=po.id, amount="100.01", method="card"
        )
    with pytest.raises(ValidationError, match="another supplier"):
        await SupplierPaymentService.create(
            db, t, supplier_id=b.id, purchase_order_id=po.id, amount="10", method="card"
        )
    draft = await _po(db, tenant_ctx, a, var, receive=False)
    with pytest.raises(ConflictError, match="only a received"):
        await SupplierPaymentService.create(
            db, t, supplier_id=a.id, purchase_order_id=draft.id, amount="10", method="card"
        )
    with pytest.raises(ValidationError, match="2 decimal"):
        await SupplierPaymentService.create(db, t, supplier_id=a.id, amount="10.005", method="card")
    with pytest.raises(ValidationError, match="method"):
        await SupplierPaymentService.create(db, t, supplier_id=a.id, amount="10", method="crypto")


async def test_a_cash_payment_leaves_the_drawer_by_exactly_its_amount(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    shift = await _shift(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, qty=4, cost="25.50")
    _, out0 = await _cash_totals(db, tenant_ctx, shift)
    pay = await SupplierPaymentService.create(
        db,
        t,
        supplier_id=sup.id,
        purchase_order_id=po.id,
        amount="60.25",
        method="cash",
        session_id=shift.id,
    )
    _, out1 = await _cash_totals(db, tenant_ctx, shift)
    assert out1 - out0 == D("60.25") and pay.session_id == shift.id
    row = (
        await db.execute(
            text(
                "select direction, reason, amount, reference_type, reference_id from "
                "pos_cash_movements "
                "where session_id=:s and reference_id=:p"
            ),
            {"s": shift.id, "p": pay.id},
        )
    ).one()
    assert (row.direction, row.reason, row.amount, row.reference_type) == (
        "out",
        "pay_out",
        D("60.25"),
        "supplier_payment",
    )


async def test_cash_payment_needs_an_open_shift_and_non_cash_must_not_have_one(
    db, tenant_ctx
) -> None:
    t = tenant_ctx.tenant_id
    sup = await _supplier(db, tenant_ctx)
    with pytest.raises(ConflictError, match="open a shift"):
        await SupplierPaymentService.create(db, t, supplier_id=sup.id, amount="5", method="cash")
    shift = await _shift(db, tenant_ctx)
    with pytest.raises(ValidationError, match="only a cash payment"):
        await SupplierPaymentService.create(
            db, t, supplier_id=sup.id, amount="5", method="card", session_id=shift.id
        )
    from app.modules.pos.service import PosService

    await PosService.close_session(db, t, shift.id, counted_cash="500.00")
    with pytest.raises(ConflictError, match="OPEN shift"):
        await SupplierPaymentService.create(
            db, t, supplier_id=sup.id, amount="5", method="cash", session_id=shift.id
        )


# --------------------------------------------------- supplier returns ----


async def test_a_return_takes_goods_off_the_shelf_at_once_and_credits_the_order_price(
    db, tenant_ctx
) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, qty=10, cost="80.00")
    ret = await SupplierReturnService.create(
        db,
        t,
        supplier_id=sup.id,
        purchase_order_id=po.id,
        reason="manufacturing_defect",
        settlement="credit",
        lines=[{"variant_id": str(var.id), "quantity": 3}],
    )
    assert ret.status == "review" and ret.total == D("240.00") and ret.number.startswith("SR-")
    assert await _on_hand(db, tenant_ctx, var) == 7  # the goods left now
    st = await SupplierService.statement(db, t, sup.id)
    assert st["balance"] == D("800.00") and st["credit_returns"] == D(
        "0.00"
    )  # not accepted: no money yet
    await SupplierReturnService.accept(db, t, ret.id)
    st = await SupplierService.statement(db, t, sup.id)
    assert st["credit_returns"] == D("240.00") and st["balance"] == D("560.00")


async def test_the_return_price_is_the_order_price_not_todays_average(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    first = await _po(db, tenant_ctx, sup, var, qty=10, cost="100.00")
    await _po(db, tenant_ctx, sup, var, qty=10, cost="200.00")  # average is now 150
    ret = await SupplierReturnService.create(
        db,
        t,
        supplier_id=sup.id,
        purchase_order_id=first.id,
        reason="surplus",
        settlement="credit",
        lines=[{"variant_id": str(var.id), "quantity": 1}],
    )
    assert ret.total == D("100.00")


async def test_you_cannot_return_more_than_you_bought_or_more_than_you_hold(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    wh = await InventoryService.get_default_warehouse(db, t)
    po = await _po(db, tenant_ctx, sup, var, qty=5, cost="10.00")
    line = lambda q: [{"variant_id": str(var.id), "quantity": q}]  # noqa: E731
    with pytest.raises(ConflictError, match="still returnable"):
        await SupplierReturnService.create(
            db,
            t,
            supplier_id=sup.id,
            purchase_order_id=po.id,
            reason="surplus",
            settlement="credit",
            lines=line(6),
        )
    await SupplierReturnService.create(
        db,
        t,
        supplier_id=sup.id,
        purchase_order_id=po.id,
        reason="surplus",
        settlement="credit",
        lines=line(3),
    )
    with pytest.raises(ConflictError, match="only 2 of the 5"):
        await SupplierReturnService.create(
            db,
            t,
            supplier_id=sup.id,
            purchase_order_id=po.id,
            reason="surplus",
            settlement="credit",
            lines=line(3),
        )
    # sell what is left, then there is nothing physical to send back even though the order allows it
    await InventoryService.move(db, t, var.id, wh.id, direction="out", quantity=2, reason="sale")
    with pytest.raises(InsufficientStockError):
        await SupplierReturnService.create(
            db,
            t,
            supplier_id=sup.id,
            purchase_order_id=po.id,
            reason="surplus",
            settlement="credit",
            lines=line(1),
        )
    assert await _on_hand(db, tenant_ctx, var) == 0


async def test_rejecting_a_return_puts_the_goods_back_and_frees_the_quantity(
    db, tenant_ctx
) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, qty=5, cost="10.00")
    ret = await SupplierReturnService.create(
        db,
        t,
        supplier_id=sup.id,
        purchase_order_id=po.id,
        reason="wrong_size",
        settlement="credit",
        lines=[{"variant_id": str(var.id), "quantity": 5}],
    )
    assert await _on_hand(db, tenant_ctx, var) == 0
    await SupplierReturnService.reject(db, t, ret.id)
    assert ret.status == "rejected" and await _on_hand(db, tenant_ctx, var) == 5
    rows = (
        await db.execute(
            text(
                "select reason, direction, quantity, balance_after from inventory_movements "
                "where reference_id=:r order by balance_after"
            ),
            {"r": ret.id},
        )
    ).all()
    # two rows; the 'out' was never edited. Ordered by balance_after: created_at is the
    # transaction's now().
    assert [(r.reason, r.direction, r.quantity, r.balance_after) for r in rows] == [
        ("supplier_return", "out", 5, 0),
        ("supplier_return_reversal", "in", 5, 5),
    ]
    again = await SupplierReturnService.create(
        db,
        t,
        supplier_id=sup.id,
        purchase_order_id=po.id,
        reason="wrong_size",
        settlement="credit",
        lines=[{"variant_id": str(var.id), "quantity": 5}],
    )
    assert again.status == "review"  # the rejected units are returnable again
    assert (await SupplierService.statement(db, t, sup.id))["credit_returns"] == D("0.00")


async def test_a_return_is_decided_once(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, qty=5, cost="10.00")
    mk = lambda: SupplierReturnService.create(  # noqa: E731
        db,
        t,
        supplier_id=sup.id,
        purchase_order_id=po.id,
        reason="surplus",
        settlement="credit",
        lines=[{"variant_id": str(var.id), "quantity": 1}],
    )
    a, b = await mk(), await mk()
    await SupplierReturnService.accept(db, t, a.id)
    with pytest.raises(ConflictError, match="already accepted"):
        await SupplierReturnService.accept(db, t, a.id)
    with pytest.raises(ConflictError, match="already accepted"):
        await SupplierReturnService.reject(db, t, a.id)
    await SupplierReturnService.reject(db, t, b.id)
    with pytest.raises(ConflictError, match="already rejected"):
        await SupplierReturnService.accept(db, t, b.id)
    assert await _on_hand(db, tenant_ctx, var) == 4  # a left for good; b came back


async def test_a_cash_refund_enters_the_drawer_only_on_acceptance(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    shift = await _shift(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, qty=5, cost="40.00")
    ret = await SupplierReturnService.create(
        db,
        t,
        supplier_id=sup.id,
        purchase_order_id=po.id,
        reason="damaged_on_receipt",
        settlement="cash",
        lines=[{"variant_id": str(var.id), "quantity": 2}],
    )
    in0, _ = await _cash_totals(db, tenant_ctx, shift)
    with pytest.raises(ConflictError, match="open a shift"):
        await SupplierReturnService.accept(db, t, ret.id)
    assert ret.status == "review"  # a refused acceptance leaves it waiting
    await SupplierReturnService.accept(db, t, ret.id, session_id=shift.id)
    in1, _ = await _cash_totals(db, tenant_ctx, shift)
    assert in1 - in0 == D("80.00") and ret.refund_session_id == shift.id
    # a cash refund is NOT account credit: the debt is unchanged
    assert (await SupplierService.statement(db, t, sup.id))["credit_returns"] == D("0.00")


async def test_a_replacement_return_moves_no_money(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    shift = await _shift(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, qty=5, cost="40.00")
    ret = await SupplierReturnService.create(
        db,
        t,
        supplier_id=sup.id,
        purchase_order_id=po.id,
        reason="wrong_color",
        settlement="replace",
        lines=[{"variant_id": str(var.id), "quantity": 1}],
    )
    before = await _cash_totals(db, tenant_ctx, shift)
    await SupplierReturnService.accept(db, t, ret.id)
    assert await _cash_totals(db, tenant_ctx, shift) == before
    assert (await SupplierService.statement(db, t, sup.id))["balance"] == D("200.00")
    with pytest.raises(ValidationError, match="only a cash refund"):
        other = await SupplierReturnService.create(
            db,
            t,
            supplier_id=sup.id,
            purchase_order_id=po.id,
            reason="surplus",
            settlement="credit",
            lines=[{"variant_id": str(var.id), "quantity": 1}],
        )
        await SupplierReturnService.accept(db, t, other.id, session_id=shift.id)


async def test_a_return_without_an_order_needs_an_explicit_price(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    await _po(db, tenant_ctx, sup, var, qty=5, cost="10.00")
    ok = await SupplierReturnService.create(
        db,
        t,
        supplier_id=sup.id,
        reason="surplus",
        settlement="credit",
        lines=[{"variant_id": str(var.id), "quantity": 1, "unit_cost": "12.50"}],
    )
    assert ok.total == D("12.50")
    with pytest.raises(ValidationError, match="unit_cost"):
        await SupplierReturnService.create(
            db,
            t,
            supplier_id=sup.id,
            reason="surplus",
            settlement="credit",
            lines=[{"variant_id": str(var.id), "quantity": 1}],
        )


async def test_return_reason_settlement_and_foreign_orders_are_validated(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    a, b = await _supplier(db, tenant_ctx), await _supplier(db, tenant_ctx)
    var = await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, a, var, qty=3, cost="10.00")
    ln = [{"variant_id": str(var.id), "quantity": 1}]
    with pytest.raises(ValidationError, match="reason"):
        await SupplierReturnService.create(
            db,
            t,
            supplier_id=a.id,
            purchase_order_id=po.id,
            reason="meh",
            settlement="credit",
            lines=ln,
        )
    with pytest.raises(ValidationError, match="settlement"):
        await SupplierReturnService.create(
            db,
            t,
            supplier_id=a.id,
            purchase_order_id=po.id,
            reason="surplus",
            settlement="gift",
            lines=ln,
        )
    with pytest.raises(ValidationError, match="another supplier"):
        await SupplierReturnService.create(
            db,
            t,
            supplier_id=b.id,
            purchase_order_id=po.id,
            reason="surplus",
            settlement="credit",
            lines=ln,
        )
    draft = await _po(db, tenant_ctx, a, var, receive=False)
    with pytest.raises(ConflictError, match="received purchase order"):
        await SupplierReturnService.create(
            db,
            t,
            supplier_id=a.id,
            purchase_order_id=draft.id,
            reason="surplus",
            settlement="credit",
            lines=ln,
        )


# ------------------------------------------------- the database itself ----


async def _must_fail(db, sql, params) -> None:
    savepoint = await db.begin_nested()
    try:
        await db.execute(sql, params)
    except IntegrityError:
        await savepoint.rollback()
        return
    await savepoint.rollback()
    pytest.fail(f"the database accepted a row it must refuse: {params}")


async def test_database_refuses_inconsistent_lines_and_states(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var, receive=False)
    line = text(
        "insert into purchase_order_lines (id, tenant_id, purchase_order_id, variant_id, "
        "quantity, unit_cost, line_total, position) "
        "values (gen_random_uuid(), :t, :p, :v, :q, :c, :l, 9)"
    )
    base = {"t": t, "p": po.id, "v": var.id}
    for q, c, total in [
        (2, 10, 21),
        (0, 10, 0),
        (-1, 10, -10),
        (1, -5, -5),
    ]:  # total != qty*cost / qty<=0 / negative cost
        await _must_fail(db, line, {**base, "q": q, "c": c, "l": total})
    stat = text("update purchase_orders set status=:s, received_at=:r where id=:i")
    await _must_fail(
        db, stat, {"s": "received", "r": None, "i": po.id}
    )  # received needs a timestamp
    await _must_fail(
        db, stat, {"s": "draft", "r": datetime(2026, 1, 1, tzinfo=UTC), "i": po.id}
    )  # a draft cannot have one
    await _must_fail(db, stat, {"s": "shipped", "r": None, "i": po.id})  # unknown state
    pay = text(
        "insert into supplier_payments (id, tenant_id, supplier_id, amount, method, paid_on) "
        "values (gen_random_uuid(), :t, :s, :a, :m, current_date)"
    )
    for amount, method in [
        ("0", "card"),
        ("-3", "card"),
        ("5", "cash"),
        ("5", "barter"),
    ]:  # cash with no shift is refused too
        await _must_fail(db, pay, {"t": t, "s": sup.id, "a": amount, "m": method})


async def test_a_supplier_with_history_cannot_be_deleted_and_the_ledger_cannot_be_rewritten(
    db, tenant_ctx
) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, sup, var)
    await SupplierPaymentService.create(
        db, t, supplier_id=sup.id, purchase_order_id=po.id, amount="10", method="card"
    )
    await _must_fail(db, text("delete from suppliers where id=:i"), {"i": sup.id})  # RESTRICT
    await _must_fail(
        db, text("delete from purchase_orders where id=:i"), {"i": po.id}
    )  # payments + lines point at it


async def test_a_payment_can_be_reversed_only_once(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup = await _supplier(db, tenant_ctx)
    pay = await SupplierPaymentService.create(db, t, supplier_id=sup.id, amount="50", method="card")
    rev = text(
        "insert into supplier_payments (id, tenant_id, supplier_id, amount, method, paid_on, "
        "reverses_payment_id) "
        "values (gen_random_uuid(), :t, :s, 50, 'card', current_date, :p)"
    )
    await db.execute(rev, {"t": t, "s": sup.id, "p": pay.id})
    await _must_fail(db, rev, {"t": t, "s": sup.id, "p": pay.id})
    assert (await SupplierService.statement(db, t, sup.id))["paid"] == D(
        "0.00"
    )  # paid 50, reversed 50


async def test_payment_list_shows_each_payment_and_a_reversal_as_its_own_row(
    db, tenant_ctx
) -> None:
    t = tenant_ctx.tenant_id
    a, b = await _supplier(db, tenant_ctx), await _supplier(db, tenant_ctx)
    var = await _variant(db, tenant_ctx)
    po = await _po(db, tenant_ctx, a, var, qty=2, cost="50.00")
    p1 = await SupplierPaymentService.create(
        db, t, supplier_id=a.id, purchase_order_id=po.id, amount="30", method="card"
    )
    await SupplierPaymentService.create(db, t, supplier_id=a.id, amount="5", method="bank_transfer")
    await SupplierPaymentService.create(db, t, supplier_id=b.id, amount="9", method="card")
    assert len(await SupplierPaymentService.list(db, t)) == 3
    assert {p.amount for p in await SupplierPaymentService.list(db, t, supplier_id=a.id)} == {
        D("30.00"),
        D("5.00"),
    }
    assert [p.id for p in await SupplierPaymentService.list(db, t, purchase_order_id=po.id)] == [
        p1.id
    ]
    assert await SupplierPaymentService.list(db, t, supplier_id=uuid.uuid4()) == []


async def test_cost_history_reads_back_what_receiving_wrote(db, tenant_ctx) -> None:
    t = tenant_ctx.tenant_id
    sup, var = await _supplier(db, tenant_ctx), await _variant(db, tenant_ctx)
    po1 = await _po(db, tenant_ctx, sup, var, qty=10, cost="100.00")
    po2 = await _po(db, tenant_ctx, sup, var, qty=10, cost="120.00")
    rows = await CostService.history(db, t, var.id)
    assert len(rows) == 2
    by_po = {r.purchase_order_id: r for r in rows}
    assert by_po[po1.id].old_avg_cost is None and by_po[po1.id].new_avg_cost == D("100.0000")
    assert by_po[po2.id].old_avg_cost == D("100.0000") and by_po[po2.id].new_avg_cost == D(
        "110.0000"
    )
    assert by_po[po2.id].on_hand_before == 10 and by_po[po2.id].unit_cost == D("120.00")
    assert await CostService.history(db, t, uuid.uuid4()) == []
