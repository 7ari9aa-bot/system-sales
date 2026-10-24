"""The money-only refund and the exchange obey the same safety rules as /returns.

Two gaps an audit found: a refund could restock the whole basket, and the drawer movement followed
the ``method`` the caller sent rather than the cash legs actually refunded.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.modules.inventory.service import InventoryService
from app.modules.pos.models import PosCashMovement
from app.modules.pos.profiles import PosProfileService
from app.modules.pos.service import PosService
from tests._pos_sell import sell as pos_sell
from tests.test_pos_returns import _customer, _register, _sellable_variant, _warehouse

pytestmark = pytest.mark.asyncio


async def _mixed_till(db, tenant_ctx):
    """A till that accepts cash AND card, so one sale can be paid half and half."""
    register = await _register(db, tenant_ctx)
    wh = await _warehouse(db, tenant_ctx)
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="mixed",
        code=f"M{uuid.uuid4().hex[:6]}",
        warehouse_id=wh.id,
        allowed_payment_methods=["cash", "card"],
    )
    return await PosService.open_session(
        db, tenant_ctx.tenant_id, register.id, profile_id=profile.id
    )


async def _sale(db, tenant_ctx, shift, *, price="100.00", qty=1, tenders=None):
    variant = await _sellable_variant(db, tenant_ctx, price=price, stock=50)
    customer = await _customer(db, tenant_ctx)
    total = str(Decimal(price) * qty)
    sold = await pos_sell(
        db,
        tenant_ctx.tenant_id,
        shift.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
        tenders=tenders or [{"method": "cash", "amount": total}],
    )
    return variant, sold["order_id"]


async def _on_hand(db, tenant_ctx, variant) -> int:
    rows = await InventoryService.list_balances(db, tenant_ctx.tenant_id)
    return sum(b.on_hand for b in rows if b.variant_id == variant.id)


async def _cash_refund_total(db, shift) -> Decimal:
    return Decimal(
        str(
            (
                await db.execute(
                    sa.select(sa.func.coalesce(sa.func.sum(PosCashMovement.amount), 0)).where(
                        PosCashMovement.session_id == shift.id,
                        PosCashMovement.reason == "cash_refund",
                    )
                )
            ).scalar_one()
        )
    )
