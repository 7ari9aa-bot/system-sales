"""M4 — checkout has to look at the product, not only at the variant.

`CatalogService.get_variant` already hides an inactive variant, so the hole was
the one level up: a product sitting in `draft` (a merchant's note pad) or
`archived` (a deliberate withdrawal) kept selling through every active variant
it had. The order took money for goods nobody was offering, and the AI ordering
tool — which reaches checkout through the same service — did exactly the same.

The rule lives in ONE place, `OrderService.create_order`, because that is the
call both the HTTP path and anything else makes. The AI tool half of this
file died with the customer agent's sales surface — the catalog-browsing
tools now read the SAME sellable vocabulary (tests/test_ai_tools.py), so a
line checkout refuses is never even searchable in chat.
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
