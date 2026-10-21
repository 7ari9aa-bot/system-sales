"""Who moved the stock: every ledger row can name the person behind it.

A shortage that cannot be traced to a person cannot be fixed. These pin down:
  * the actor given to a movement is the one stored on the ledger row
  * a call that names nobody still works and stores NULL (old callers, workers, imports)
  * the stocktake approval and a purchase receipt carry the acting user
  * a sale records the cashier on its `sale` row
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.inventory.models import InventoryMovement
from app.modules.inventory.service import InventoryService
from app.modules.inventory.services import StocktakeService
from app.modules.purchasing.service import PurchaseService
from tests.test_inventory_stock_view import _variant
from tests.test_purchasing import _po, _supplier
from tests.test_purchasing import _variant as _po_variant

pytestmark = pytest.mark.asyncio


async def _rows(db, tenant_ctx, variant, reason):
    return (
        (
            await db.execute(
                select(InventoryMovement)
                .where(
                    InventoryMovement.tenant_id == tenant_ctx.tenant_id,
                    InventoryMovement.variant_id == variant.id,
                    InventoryMovement.reason == reason,
                )
                .order_by(InventoryMovement.ledger_seq)
            )
        )
        .scalars()
        .all()
    )


async def test_a_movement_stores_the_actor_it_was_given(db, tenant_ctx):
    _, variant, wh = await _variant(db, tenant_ctx, stock=0)
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, wh.id,
        direction="in", quantity=5, reason="purchase",
        actor_user_id=tenant_ctx.user.id,
    )  # fmt: skip
    (row,) = await _rows(db, tenant_ctx, variant, "purchase")
    assert row.actor_user_id == tenant_ctx.user.id


async def test_a_movement_with_no_actor_stores_null(db, tenant_ctx):
    _, variant, wh = await _variant(db, tenant_ctx, stock=0)
    await InventoryService.move(
        db, tenant_ctx.tenant_id, variant.id, wh.id,
        direction="in", quantity=5, reason="purchase",
    )  # fmt: skip
    (row,) = await _rows(db, tenant_ctx, variant, "purchase")
    assert row.actor_user_id is None


async def test_stocktake_approval_records_who_approved(db, tenant_ctx):
    _, variant, wh = await _variant(db, tenant_ctx, stock=10)
    st = await StocktakeService.open(db, tenant_ctx.tenant_id, wh.id)
    await StocktakeService.record_counts(
        db, tenant_ctx.tenant_id, st.id, [{"variant_id": str(variant.id), "counted_qty": 7}]
    )
    await StocktakeService.approve(db, tenant_ctx.tenant_id, st.id, user_id=tenant_ctx.user.id)
    (row,) = await _rows(db, tenant_ctx, variant, "adjustment")
    assert (row.direction, row.quantity) == ("out", 3)
    assert row.actor_user_id == tenant_ctx.user.id


async def test_purchase_receipt_records_who_received(db, tenant_ctx):
    supplier = await _supplier(db, tenant_ctx)
    variant = await _po_variant(db, tenant_ctx)
    order = await _po(db, tenant_ctx, supplier, variant, qty=4, receive=False)
    await PurchaseService.receive(db, tenant_ctx.tenant_id, order.id, tenant_ctx.user.id)
    (row,) = await _rows(db, tenant_ctx, variant, "purchase")
    assert row.actor_user_id == tenant_ctx.user.id


async def test_purchase_created_and_received_at_once_records_the_creator(db, tenant_ctx):
    supplier = await _supplier(db, tenant_ctx)
    variant = await _po_variant(db, tenant_ctx)
    await _po(db, tenant_ctx, supplier, variant, qty=2, created_by=tenant_ctx.user.id)
    (row,) = await _rows(db, tenant_ctx, variant, "purchase")
    assert row.actor_user_id == tenant_ctx.user.id


async def test_sale_and_return_record_the_cashier(db, tenant_ctx):
    from app.modules.pos.service import PosService
    from tests.test_pos_exchange import _customer, _register, _sellable_variant

    register = await _register(db, tenant_ctx)
    pos_session = await PosService.open_session(db, tenant_ctx.tenant_id, register.id)
    variant = await _sellable_variant(db, tenant_ctx)
    customer = await _customer(db, tenant_ctx)
    cashier = tenant_ctx.user.id
    sold = await PosService.sell(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        tenders=[{"method": "cash", "amount": "25.00"}],
        actor_user_id=cashier,
    )
    (sale_row,) = await _rows(db, tenant_ctx, variant, "sale")
    assert sale_row.actor_user_id == cashier

    await PosService.return_sale(
        db,
        tenant_ctx.tenant_id,
        pos_session.id,
        order_id=sold["order_id"],
        lines=[{"variant_id": str(variant.id), "quantity": 1}],
        restock=True,
        actor_user_id=cashier,
    )
    (return_row,) = await _rows(db, tenant_ctx, variant, "return")
    assert return_row.actor_user_id == cashier
