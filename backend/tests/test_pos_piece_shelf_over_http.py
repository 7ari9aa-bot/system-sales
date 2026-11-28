"""The shelf decision of each piece must survive the HTTP layer.

The service tests call ``PosService`` directly, so they cannot see a route that drops a field on the
way in. This one drives the real routes: a return line that says ``restock: false`` must keep that
piece off the shelf, and a line that says nothing must follow the shop's default.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.applications.apparel.modules.inventory.models import InventoryMovement
from tests.test_pos_line_discounts import _sellable_variant
from tests.test_pos_return_audit_and_day_holder import _call, _day

pytestmark = pytest.mark.asyncio


async def _returned_to_shelf(db, tenant_ctx, order_id, variant):
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(InventoryMovement.quantity), 0)).where(
                    InventoryMovement.tenant_id == tenant_ctx.tenant_id,
                    InventoryMovement.variant_id == variant.id,
                    InventoryMovement.reason == "return",
                    InventoryMovement.reference_id == order_id,
                )
            )
        ).scalar_one()
    )


async def _two_piece_sale(db, tenant_ctx):
    register_id, day_id, jacket, customer, staff = await _day(db, tenant_ctx)
    shirt = await _sellable_variant(db, tenant_ctx)
    r = await _call(
        staff,
        "POST",
        f"/api/v1/pos/registers/{register_id}/sales",
        {
            "items": [
                {"variant_id": str(jacket.id), "quantity": 1},
                {"variant_id": str(shirt.id), "quantity": 1},
            ],
            "customer_id": str(customer.id),
        },
    )
    assert r.status_code == 201, r.text
    return day_id, jacket, shirt, r.json()["order_id"], staff


async def test_a_return_line_that_says_no_keeps_that_piece_off_the_shelf(db, tenant_ctx) -> None:
    import uuid

    day_id, jacket, shirt, order_id, staff = await _two_piece_sale(db, tenant_ctx)
    r = await _call(
        staff,
        "POST",
        f"/api/v1/pos/sessions/{day_id}/returns",
        {
            "order_id": order_id,
            "lines": [
                {"variant_id": str(jacket.id), "quantity": 1},
                {"variant_id": str(shirt.id), "quantity": 1, "restock": False},
            ],
        },
    )
    assert r.status_code == 201, r.text
    oid = uuid.UUID(order_id)
    assert await _returned_to_shelf(db, tenant_ctx, oid, jacket) == 1  # the shop default: yes
    assert await _returned_to_shelf(db, tenant_ctx, oid, shirt) == 0  # this piece said no
    said = {line["variant_id"]: line["restocked"] for line in r.json()["lines"]}
    assert said == {str(jacket.id): True, str(shirt.id): False}


async def test_an_exchange_line_that_says_no_keeps_that_piece_off_the_shelf(db, tenant_ctx) -> None:
    import uuid

    day_id, jacket, shirt, order_id, staff = await _two_piece_sale(db, tenant_ctx)
    replacement = await _sellable_variant(db, tenant_ctx)
    r = await _call(
        staff,
        "POST",
        f"/api/v1/pos/sessions/{day_id}/exchanges",
        {
            "order_id": order_id,
            "return_lines": [
                {"variant_id": str(jacket.id), "quantity": 1, "restock": True},
                {"variant_id": str(shirt.id), "quantity": 1, "restock": False},
            ],
            "new_lines": [{"variant_id": str(replacement.id), "quantity": 1}],
        },
    )
    assert r.status_code == 201, r.text
    oid = uuid.UUID(order_id)
    assert await _returned_to_shelf(db, tenant_ctx, oid, jacket) == 1
    assert await _returned_to_shelf(db, tenant_ctx, oid, shirt) == 0
