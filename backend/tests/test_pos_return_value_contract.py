"""The refund the cashier is SHOWN must equal the refund the server GIVES.

The screen estimates a return from the receipt it fetched (`unit_price`, `quantity`,
`discount_pct`, the order discount). This pins that the receipt carries what the estimate
needs, using the report's example:
A = 100 at 50% off (paid 50), B = 100 (paid 100). Returning A is worth 50.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.pos.service import PosService
from tests._pos_helpers import in_tx as _in_tx
from tests._pos_helpers import make_tenant as _make_tenant
from tests._pos_helpers import purge_test_tenant as _purge_test_tenant

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def shop(db_url, admin_url):
    engine, factory, tenant_id, user_id = await _make_tenant(db_url, "rv")
    try:
        yield factory, tenant_id
    finally:
        await engine.dispose()
        await _purge_test_tenant(admin_url, tenant_id, user_id)


async def _setup(factory, t):
    from app.modules.catalog.service import CatalogService
    from app.modules.inventory.service import InventoryService

    async def go(s):
        wh = await InventoryService.get_default_warehouse(s, t)
        reg = await PosService.create_register(
            s, t, name="k", code=f"R{uuid.uuid4().hex[:5]}", warehouse_id=wh.id
        )
        shift = await PosService.open_session(s, t, reg.id, opening_float="0.00")
        ids = []
        for title in ("A", "B"):
            p = await CatalogService.create_product(
                s, t, title=title, slug=f"p-{uuid.uuid4().hex[:10]}"
            )
            p = await CatalogService.update_product(s, t, p.id, status="active")
            v = await CatalogService.add_variant(s, t, p.id, title="v", price="100.00")
            await InventoryService.move(
                s, t, v.id, wh.id, direction="in", quantity=5, reason="purchase"
            )
            ids.append(v.id)
        return shift.id, ids

    out = await _in_tx(factory, t, go)
    assert not isinstance(out, Exception), out
    return out


async def test_receipt_carries_line_discount_and_server_refunds_what_was_paid(shop) -> None:
    factory, t = shop
    shift, (a, b) = await _setup(factory, t)

    sold = await _in_tx(
        factory,
        t,
        lambda s: PosService.sell(
            s,
            t,
            shift,
            items=[
                {"variant_id": str(a), "quantity": 1, "discount_pct": "50.00"},
                {"variant_id": str(b), "quantity": 1},
            ],
            tenders=[{"method": "cash", "amount": "150.00"}],
        ),
    )
    assert not isinstance(sold, Exception), sold
    assert sold["grand_total"] == "150.00"

    receipt = await _in_tx(factory, t, lambda s: PosService.get_receipt(s, t, sold["receipt_id"]))
    by_variant = {ln["variant_id"]: ln for ln in receipt["lines"]}
    assert by_variant[a]["discount_pct"] == "50.00", "the receipt must say A was sold at 50% off"
    assert by_variant[b]["discount_pct"] == "0.00"

    # The client estimate (line net, no order-level share) equals what the server gives back.
    returned = await _in_tx(
        factory,
        t,
        lambda s: PosService.return_sale(
            s, t, shift, order_id=sold["order_id"], lines=[{"variant_id": str(a), "quantity": 1}]
        ),
    )
    assert not isinstance(returned, Exception), returned
    assert Decimal(str(returned["refunded_total"])) == Decimal("50.00")


async def test_old_receipts_without_a_line_discount_read_as_zero(shop) -> None:
    factory, t = shop
    shift, (a, _b) = await _setup(factory, t)
    sold = await _in_tx(
        factory,
        t,
        lambda s: PosService.sell(
            s,
            t,
            shift,
            items=[{"variant_id": str(a), "quantity": 2}],
            tenders=[{"method": "cash", "amount": "200.00"}],
        ),
    )
    receipt = await _in_tx(factory, t, lambda s: PosService.get_receipt(s, t, sold["receipt_id"]))
    assert receipt["lines"][0]["discount_pct"] == "0.00"
