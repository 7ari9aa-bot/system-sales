"""M4 — checkout has to look at the product, not only at the variant.

`CatalogService.get_variant` already hides an inactive variant, so the hole was
the one level up: a product sitting in `draft` (a merchant's note pad) or
`archived` (a deliberate withdrawal) kept selling through every active variant
it had. The order took money for goods nobody was offering, and the AI ordering
tool — which reaches checkout through the same service — did exactly the same.

The rule lives in ONE place, `OrderService.create_order`, because that is the
call both the HTTP path and the agent tool make. P1-10 added an EARLY read of
the same vocabulary at the AI quote gate — a line checkout would refuse must
not even be quotable in chat — while the order itself is still created only
through `OrderService`.
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


async def _conversation(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID):
    """A real conversation: AI order quotes are conversation-scoped (§P1-10)."""
    from app.modules.conversations.service import ConversationService

    return await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer_id, channel="whatsapp"
    )


async def test_the_agent_tool_checks_out_through_the_same_service(
    db: AsyncSession, tenant_ctx, monkeypatch
):
    """The AI path may not carry its own, weaker sellability rule (§M4).

    P1-10 makes the delegation two-phase: an unconfirmed call PROPOSES and
    never reaches checkout; only the customer's own confirmed code runs the
    EXECUTION call — and that still goes through OrderService.create_order,
    with the QUOTE's lines, not whatever arguments the model sent this time.
    """
    from types import SimpleNamespace

    from app.modules.ai.agents.customer.confirmation import match_confirmation
    from app.modules.ai.tools import get_tool

    tenant_id = tenant_ctx.tenant_id
    _product_row, variant = await _product(db, tenant_id, status="active")
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}"
    )
    conversation = await _conversation(db, tenant_id, customer.id)

    order_id = uuid.uuid4()
    seen: dict = {}

    async def _fake_create_order(session, tenant_id_arg, customer_id, items, **kwargs):
        seen["items"] = items
        return SimpleNamespace(
            id=order_id,
            number="ORD-TEST-0001",
            status="pending",
            grand_total=Decimal("150.00"),
        )

    monkeypatch.setattr(OrderService, "create_order", staticmethod(_fake_create_order))
    bound = {"customer_id": str(customer.id), "conversation_id": str(conversation.id)}
    proposal = await get_tool("create_order").handler(
        db, tenant_id, items=[{"variant_id": variant.id, "quantity": 2}], context=bound
    )
    # Nothing to check out yet: the proposal only priced a quote.
    assert seen == {}
    assert proposal["status"] == "pending"

    quote = await match_confirmation(
        db,
        tenant_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        text=proposal["confirmation_code"],
    )
    result = await get_tool("create_order").handler(
        db,
        tenant_id,
        # Deliberately DIFFERENT lines — execution must take the quote's items.
        items=[{"variant_id": uuid.uuid4(), "quantity": 7}],
        context={**bound, "confirmed_quote_id": str(quote.id)},
    )

    # The line items went to the service — the tool did not price or validate
    # them on the way past.
    assert seen["items"] == [{"variant_id": variant.id, "quantity": 2}]
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
    """Same gate for the chatbot: what is in draft cannot even be quoted.

    P1-10 moved the refusal EARLIER: the proposal is refused at the quote
    gate, reading checkout's own sellable vocabulary, so no expiring code is
    ever handed out for a line nobody is offering.
    """
    from app.modules.ai.models import AIOrderQuote
    from app.modules.ai.tools import get_tool

    tenant_id = tenant_ctx.tenant_id
    _product_row, variant = await _product(db, tenant_id, status="draft")
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}"
    )
    conversation = await _conversation(db, tenant_id, customer.id)
    handler = get_tool("create_order").handler

    with pytest.raises(ConflictError):
        await handler(
            db,
            tenant_id,
            items=[{"variant_id": variant.id, "quantity": 1}],
            context={"customer_id": str(customer.id), "conversation_id": str(conversation.id)},
        )
    assert (
        await db.execute(select(AIOrderQuote).where(AIOrderQuote.tenant_id == tenant_id))
    ).scalars().all() == []
    await db.flush()
