"""M4 — checkout has to look at the product, not only at the variant.

`CatalogService.get_variant` already hides an inactive variant, so the hole was
the one level up: a product sitting in `draft` (a merchant's note pad) or
`archived` (a deliberate withdrawal) kept selling through every active variant
it had. The order took money for goods nobody was offering, and the AI ordering
tool — which reaches checkout through the same service — did exactly the same.

The rule lives in ONE place, `OrderService.create_order`, because that is the
call both the HTTP path and the agent tool make.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.errors import ConflictError
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import Order
from app.modules.orders.service import OrderService

# ------------------------------------------------------------------ helpers ----


async def _product(db: AsyncSession, tenant_id: uuid.UUID, *, status: str):
    """A product in `status`, with one priced variant and 10 units on hand.

    The variant is active in every case: the whole point is that the variant's
    own flag says nothing about the product above it.
    """
    product = await CatalogService.create_product(
        db,
        tenant_id,
        title=f"P-{uuid.uuid4().hex[:6]}",
        slug=f"p-{uuid.uuid4().hex[:6]}",
    )
    if status != "draft":
        await CatalogService.update_product(db, tenant_id, product.id, status=status)
    variant = await CatalogService.add_variant(
        db,
        tenant_id,
        product.id,
        sku=f"S-{uuid.uuid4().hex[:6].upper()}",
        price="25.00",
    )
    await InventoryService.move(
        db,
        tenant_id,
        variant.id,
        (await InventoryService.get_default_warehouse(db, tenant_id)).id,
        direction="in",
        quantity=10,
        reason="purchase",
    )
    return product, variant


async def _checkout(db: AsyncSession, tenant_id: uuid.UUID, variant, *, qty=1):
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}"
    )
    return await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": qty}]
    )


# ------------------------------------------------------------------ the rule ----


def test_only_an_active_product_is_sellable():
    from app.modules.orders.service import sellable_refusal

    assert sellable_refusal("active") is None
    assert sellable_refusal("draft") is not None
    assert sellable_refusal("archived") is not None
    # A variant whose product row is missing cannot be "not said anything yet".
    assert sellable_refusal(None) is not None


async def test_the_agent_tool_checks_out_through_the_same_service(monkeypatch):
    """The AI path may not carry its own, weaker sellability rule (§M4).

    It reaches checkout through OrderService.create_order — the one call where
    the rule lives — so the tool cannot be the seam a draft product slips
    through. The assertion is on the delegation, not on the refusal, which the
    database cases below cover for both paths.
    """
    from types import SimpleNamespace

    from app.modules.ai.tools import get_tool

    order_id = uuid.uuid4()
    seen: dict = {}

    async def _fake_create_order(session, tenant_id, customer_id, items, **kwargs):
        seen["items"] = items
        return SimpleNamespace(
            id=order_id,
            number="ORD-TEST-0001",
            status="pending",
            grand_total=Decimal("150.00"),
        )

    monkeypatch.setattr(OrderService, "create_order", staticmethod(_fake_create_order))
    variant_id = uuid.uuid4()
    result = await get_tool("create_order").handler(
        None,
        uuid.uuid4(),
        items=[{"variant_id": variant_id, "quantity": 2}],
        context={"customer_id": str(uuid.uuid4())},
    )

    # The line items went to the service — the tool did not price or validate
    # them on the way past.
    assert seen["items"] == [{"variant_id": variant_id, "quantity": 2}]
    assert result["order_id"] == str(order_id)
    assert result["number"] == "ORD-TEST-0001"
    # Money leaves as the Decimal it is, as a string — never as a float (§47).
    assert result["grand_total"] == "150.00"


# ----------------------------------------------------------------- at the gate ----


async def test_a_draft_product_is_refused_at_checkout(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    _product_row, variant = await _product(db, tenant_id, status="draft")

    with pytest.raises(ConflictError):
        await _checkout(db, tenant_id, variant)
    # Refused BEFORE anything was held: no order row, no reservation.
    assert (
        await db.execute(select(Order).where(Order.tenant_id == tenant_id))
    ).scalars().all() == []
    await db.flush()


async def test_an_archived_parent_takes_its_active_variant_down(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    _product_row, variant = await _product(db, tenant_id, status="archived")
    assert variant.is_active is True  # the variant itself still looks sellable

    with pytest.raises(ConflictError):
        await _checkout(db, tenant_id, variant)
    await db.flush()


async def test_an_active_product_still_checks_out(db: AsyncSession, tenant_ctx):
    """The refusal must not have turned checkout into a refusal of everything."""
    tenant_id = tenant_ctx.tenant_id
    _product_row, variant = await _product(db, tenant_id, status="active")

    order = await _checkout(db, tenant_id, variant, qty=3)
    await db.flush()

    assert order.status == "pending"
    assert order.grand_total == Decimal("75.00")


async def test_the_agent_tool_refuses_a_draft_product_too(db: AsyncSession, tenant_ctx):
    """Same gate for the chatbot: the customer cannot order what is in draft."""
    from app.modules.ai.tools import get_tool

    tenant_id = tenant_ctx.tenant_id
    _product_row, variant = await _product(db, tenant_id, status="draft")
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}"
    )
    handler = get_tool("create_order").handler

    with pytest.raises(ConflictError):
        await handler(
            db,
            tenant_id,
            items=[{"variant_id": variant.id, "quantity": 1}],
            context={"customer_id": str(customer.id)},
        )
    await db.flush()
