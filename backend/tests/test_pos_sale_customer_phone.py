"""An OPTIONAL phone on a till sale books the invoice to the customer who owns that number.

This is what lets a customer find their own invoice from a chat later. The phone never refuses
a sale, and it is never dropped silently: when it cannot be used the response says so.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.modules.catalog.service import CatalogService
from app.modules.customers.service import CustomerService
from app.modules.inventory.service import InventoryService
from app.modules.pos.service import PosService
from tests._pos_sell import sell

pytestmark = pytest.mark.asyncio


async def _till(db, tenant_id):
    warehouse = await InventoryService.get_default_warehouse(db, tenant_id)
    register = await PosService.create_register(
        db, tenant_id, name="كاشير", code=f"REG-{uuid.uuid4().hex[:6]}", warehouse_id=warehouse.id
    )
    till = await PosService.open_session(db, tenant_id, register.id)
    product = await CatalogService.create_product(
        db, tenant_id, title="تيشيرت", slug=f"t-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(db, tenant_id, product.id, title="L", price="25.00")
    await InventoryService.move(
        db, tenant_id, variant.id, warehouse.id, direction="in", quantity=50, reason="purchase"
    )
    return till, [{"variant_id": str(variant.id), "quantity": 1}]


async def _customer_of(db, order_id):
    row = (
        await db.execute(
            text(
                "SELECT c.id, c.name, c.phone FROM orders o "
                "JOIN customers c ON c.id = o.customer_id WHERE o.id = :i"
            ),
            {"i": order_id},
        )
    ).one()
    return row


async def _count(db, tenant_id, phone):
    return (
        await db.execute(
            text("SELECT count(*) FROM customers WHERE tenant_id = :t AND phone = :p"),
            {"t": tenant_id, "p": phone},
        )
    ).scalar_one()


async def test_a_new_phone_creates_the_customer_and_books_the_sale_to_them(db, tenant_ctx) -> None:
    till, items = await _till(db, tenant_ctx.tenant_id)

    sold = await sell(
        db,
        tenant_ctx.tenant_id,
        till.id,
        items=items,
        customer_phone="01012345678",
        customer_name="أحمد",
    )

    customer = await _customer_of(db, sold["order_id"])
    assert (customer.name, customer.phone) == ("أحمد", "+201012345678")
    assert sold["customer_notice"] is None


async def test_the_same_phone_twice_is_one_customer(db, tenant_ctx) -> None:
    """Typed two ways (local / international), it is still one person."""
    till, items = await _till(db, tenant_ctx.tenant_id)

    first = await sell(db, tenant_ctx.tenant_id, till.id, items=items, customer_phone="01012345678")
    second = await sell(
        db, tenant_ctx.tenant_id, till.id, items=items, customer_phone="+20 101 234 5678"
    )

    assert (await _customer_of(db, first["order_id"])).id == (
        await _customer_of(db, second["order_id"])
    ).id
    assert await _count(db, tenant_ctx.tenant_id, "+201012345678") == 1


async def test_an_existing_customer_is_reused_not_renamed(db, tenant_ctx) -> None:
    till, items = await _till(db, tenant_ctx.tenant_id)
    known = await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="منى", phone="01012345678"
    )

    sold = await sell(
        db,
        tenant_ctx.tenant_id,
        till.id,
        items=items,
        customer_phone="01012345678",
        customer_name="اسم تاني",
    )

    customer = await _customer_of(db, sold["order_id"])
    assert (customer.id, customer.name) == (known.id, "منى")


async def test_a_phone_with_no_name_names_the_customer_by_the_number(db, tenant_ctx) -> None:
    till, items = await _till(db, tenant_ctx.tenant_id)

    sold = await sell(db, tenant_ctx.tenant_id, till.id, items=items, customer_phone="01012345678")

    assert (await _customer_of(db, sold["order_id"])).name == "+201012345678"


async def test_an_invalid_phone_still_sells_and_tells_the_cashier(db, tenant_ctx) -> None:
    till, items = await _till(db, tenant_ctx.tenant_id)

    sold = await sell(db, tenant_ctx.tenant_id, till.id, items=items, customer_phone="0101234")

    assert sold["receipt_id"] and sold["customer_notice"] == "phone_not_recorded"
    # booked as an ordinary walk-in, and nothing junk was stored as a customer
    assert (await _customer_of(db, sold["order_id"])).name == "زبون نقدي"
    assert await _count(db, tenant_ctx.tenant_id, "0101234") == 0


async def test_a_blocked_customer_is_not_booked_and_the_cashier_is_told(db, tenant_ctx) -> None:
    till, items = await _till(db, tenant_ctx.tenant_id)
    known = await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="محظور", phone="01012345678"
    )
    await CustomerService.set_blocked(db, tenant_ctx.tenant_id, known.id, blocked=True)

    sold = await sell(db, tenant_ctx.tenant_id, till.id, items=items, customer_phone="01012345678")

    assert sold["customer_notice"] == "phone_not_recorded"
    assert (await _customer_of(db, sold["order_id"])).id != known.id


async def test_no_phone_keeps_the_walk_in_and_no_notice(db, tenant_ctx) -> None:
    till, items = await _till(db, tenant_ctx.tenant_id)

    for blank in (None, "", "   "):
        sold = await sell(db, tenant_ctx.tenant_id, till.id, items=items, customer_phone=blank)
        assert sold["customer_notice"] is None
        assert (await _customer_of(db, sold["order_id"])).name == "زبون نقدي"


async def test_an_explicit_customer_pick_wins_over_a_typed_phone(db, tenant_ctx) -> None:
    till, items = await _till(db, tenant_ctx.tenant_id)
    picked = await CustomerService.create_from_import(db, tenant_ctx.tenant_id, name="المختار")

    sold = await sell(
        db,
        tenant_ctx.tenant_id,
        till.id,
        items=items,
        customer_id=picked.id,
        customer_phone="01012345678",
    )

    assert (await _customer_of(db, sold["order_id"])).id == picked.id
    assert await _count(db, tenant_ctx.tenant_id, "+201012345678") == 0


async def test_the_agent_finds_the_invoice_of_a_phone_typed_at_the_till(db, tenant_ctx) -> None:
    """End to end: till phone -> WhatsApp chat of that number -> the agent opens the invoice."""
    from app.modules.ai.tools import get_tool
    from app.modules.conversations.service import ConversationService

    till, items = await _till(db, tenant_ctx.tenant_id)
    sold = await sell(db, tenant_ctx.tenant_id, till.id, items=items, customer_phone="01012345678")
    number = (
        await db.execute(text("SELECT number FROM orders WHERE id = :i"), {"i": sold["order_id"]})
    ).scalar_one()
    chat = await CustomerService.get_or_create_by_identity(
        db, tenant_ctx.tenant_id, "whatsapp", "201012345678", name="عميل الشات"
    )
    conversation = await ConversationService.get_or_create(
        db, tenant_ctx.tenant_id, customer_id=chat.id, channel="whatsapp"
    )
    await db.flush()

    result = await get_tool("get_my_orders").handler(
        db,
        tenant_ctx.tenant_id,
        number=number,
        context={"customer_id": str(chat.id), "conversation_id": str(conversation.id)},
    )

    assert [row["number"] for row in result["orders"]] == [number]


async def test_a_legacy_customer_stored_with_the_raw_spelling_is_still_matched(
    db, tenant_ctx
) -> None:
    """Old rows hold what a human typed. They must not be cloned into a second customer."""
    till, items = await _till(db, tenant_ctx.tenant_id)
    legacy = await CustomerService.create_from_import(
        db, tenant_ctx.tenant_id, name="قديم", phone="01012345678"
    )
    await db.execute(
        text("UPDATE customers SET phone = '01012345678' WHERE id = :i"), {"i": legacy.id}
    )
    await db.flush()
    stored = (
        await db.execute(text("SELECT phone FROM customers WHERE id = :i"), {"i": legacy.id})
    ).scalar_one()
    assert stored == "01012345678"  # really the legacy raw spelling

    sold = await sell(db, tenant_ctx.tenant_id, till.id, items=items, customer_phone="01012345678")

    assert (await _customer_of(db, sold["order_id"])).id == legacy.id
