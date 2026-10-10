"""P1-10 — the customer, not the model, authorizes an order.

The contract these tests pin:

* ``create_order`` without a bound confirmed quote only PROPOSES. It prices
  the lines from the catalog, mints a 6-digit code with an expiry, and leaves
  NO order row behind.
* The code becomes a confirmed quote only when the CUSTOMER's own message
  carries it, matched server-side. The model has no argument that can
  confirm, and no sentence it writes counts as a confirmation.
* Execution runs the QUOTE's items. The arguments of the executing call are
  ignored on purpose: what the customer typed a code for is what ships.
* One live quote per conversation, so a repeated proposal replays the same
  code instead of orphaning the one the customer is about to type.
* A quote past its expiry dies in both directions: unconfirmable while
  pending, unexecutable while confirmed — and it stops holding the
  conversation hostage, so a fresh quote can be minted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, DomainError
from app.modules.ai.agents.customer.confirmation import (
    QUOTE_TTL_MINUTES,
    live_quote,
    match_confirmation,
)
from app.modules.ai.agents.customer.turn import TurnInput, run_customer_turn
from app.modules.ai.models import AIOrderQuote
from app.modules.ai.runtime import AgentRunResult
from app.modules.ai.tools import get_tool
from app.modules.catalog.service import CatalogService
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import Order, OrderItem

HANDLER = get_tool("create_order").handler


# ------------------------------------------------------------------ helpers ----


async def _participant(db: AsyncSession, tenant_id: uuid.UUID):
    """A customer and their conversation — quotes are bound to both."""
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}", name="Nour"
    )
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="whatsapp"
    )
    return customer, conversation


async def _variant(db: AsyncSession, tenant_id: uuid.UUID, *, price: str = "25.50"):
    """An active, sellable product with one priced variant and 10 units."""
    product = await CatalogService.create_product(
        db,
        tenant_id,
        title=f"P-{uuid.uuid4().hex[:6]}",
        slug=f"p-{uuid.uuid4().hex[:6]}",
    )
    await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, sku=f"S-{uuid.uuid4().hex[:6].upper()}", price=price
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
    return variant


def _context(customer, conversation, **extra) -> dict:
    return {
        "customer_id": str(customer.id),
        "conversation_id": str(conversation.id),
        **extra,
    }


async def _propose(db: AsyncSession, tenant_id: uuid.UUID, customer, conversation, variant, qty=2):
    return await HANDLER(
        db,
        tenant_id,
        items=[{"variant_id": variant.id, "quantity": qty}],
        context=_context(customer, conversation),
    )


async def _quotes(db: AsyncSession, tenant_id: uuid.UUID) -> list[AIOrderQuote]:
    return list(
        (
            await db.execute(
                select(AIOrderQuote).where(AIOrderQuote.tenant_id == tenant_id).order_by(
                    AIOrderQuote.created_at
                )
            )
        )
        .scalars()
        .all()
    )


async def _orders(db: AsyncSession, tenant_id: uuid.UUID) -> list[Order]:
    return list(
        (await db.execute(select(Order).where(Order.tenant_id == tenant_id))).scalars().all()
    )


# ---------------------------------------------------------------- proposal ----


async def test_a_proposal_mints_a_quote_and_creates_no_order(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id, price="25.50")

    result = await _propose(db, tenant_id, customer, conversation, variant, qty=2)

    assert result["status"] == "pending"
    assert result["confirmation_code"].isdigit() and len(result["confirmation_code"]) == 6
    # Priced from the catalog, not from anything the model said.
    assert Decimal(result["grand_total"]) == Decimal("51.00")
    assert result["items"][0]["variant_id"] == str(variant.id)
    assert result["items"][0]["unit_price"] == "25.50"
    assert result["items"][0]["line_total"] == "51.00"
    assert "لم ينفذ" in result["instruction"]
    # The order does not exist yet — the quote is the only row written.
    assert await _orders(db, tenant_id) == []
    assert [q.status for q in await _quotes(db, tenant_id)] == ["pending"]


async def test_a_second_proposal_replays_the_same_code(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)

    first = await _propose(db, tenant_id, customer, conversation, variant)
    second = await _propose(db, tenant_id, customer, conversation, variant, qty=5)

    # One live quote per conversation: a second code would orphan the first.
    assert second["quote_id"] == first["quote_id"]
    assert second["confirmation_code"] == first["confirmation_code"]
    assert len(await _quotes(db, tenant_id)) == 1


async def test_a_draft_line_is_refused_before_any_code_exists(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    product = await CatalogService.create_product(
        db, tenant_id, title="Draft", slug=f"d-{uuid.uuid4().hex[:6]}"
    )
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, sku=f"D-{uuid.uuid4().hex[:6].upper()}", price="10.00"
    )

    with pytest.raises(ConflictError):
        await _propose(db, tenant_id, customer, conversation, variant)
    assert await _quotes(db, tenant_id) == []


# ------------------------------------------------------------- confirming ----


async def test_the_customers_message_confirms_the_quote(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)
    proposal = await _propose(db, tenant_id, customer, conversation, variant)

    quote = await match_confirmation(
        db,
        tenant_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        text=f"ايوه {proposal['confirmation_code']} أكّد الطلب",
    )

    assert quote is not None and quote.status == "confirmed"
    assert quote.confirmed_at is not None
    # Confirmation starts the EXECUTION window — merchant approval can be slow.
    assert quote.expires_at > datetime.now(UTC) + timedelta(
        minutes=QUOTE_TTL_MINUTES - 1
    )


async def test_text_without_the_code_never_confirms(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)
    await _propose(db, tenant_id, customer, conversation, variant)

    matched = await match_confirmation(
        db,
        tenant_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        text="اكيد كده تمام 123456",
    )
    assert matched is None
    assert (await _quotes(db, tenant_id))[0].status == "pending"


async def test_a_message_from_another_customer_cannot_confirm(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    other = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}"
    )
    proposal = await _propose(db, tenant_id, customer, conversation, await _variant(db, tenant_id))

    matched = await match_confirmation(
        db,
        tenant_id,
        conversation_id=conversation.id,
        customer_id=other.id,
        text=proposal["confirmation_code"],
    )
    assert matched is None


# ------------------------------------------------------------- executing ----


async def test_execution_creates_the_order_from_the_quotes_items(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id, price="25.50")
    other_variant = await _variant(db, tenant_id, price="99.00")
    proposal = await _propose(db, tenant_id, customer, conversation, variant, qty=2)
    quote = await match_confirmation(
        db,
        tenant_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        text=proposal["confirmation_code"],
    )

    # The model's arguments here name a DIFFERENT, dearer line on purpose.
    result = await HANDLER(
        db,
        tenant_id,
        items=[{"variant_id": other_variant.id, "quantity": 9}],
        context=_context(customer, conversation, confirmed_quote_id=str(quote.id)),
    )

    order = await db.get(Order, uuid.UUID(result["order_id"]))
    assert order is not None and order.customer_id == customer.id
    lines = (
        await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    ).scalars().all()
    assert [(str(item.variant_id), item.quantity) for item in lines] == [(str(variant.id), 2)]
    assert Decimal(result["grand_total"]) == Decimal("51.00")
    assert result["quote_id"] == str(quote.id)

    await db.refresh(quote)
    assert quote.status == "consumed" and quote.consumed_at is not None


async def test_execution_refuses_a_quote_that_was_never_confirmed(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)
    await _propose(db, tenant_id, customer, conversation, variant)
    pending = (await _quotes(db, tenant_id))[0]

    with pytest.raises(DomainError):
        await HANDLER(
            db,
            tenant_id,
            items=[{"variant_id": variant.id, "quantity": 2}],
            context=_context(customer, conversation, confirmed_quote_id=str(pending.id)),
        )
    assert await _orders(db, tenant_id) == []


async def test_execution_refuses_a_foreign_or_made_up_quote_id(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)
    proposal = await _propose(db, tenant_id, customer, conversation, variant)
    quote = await match_confirmation(
        db,
        tenant_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        text=proposal["confirmation_code"],
    )
    other_customer, other_conversation = await _participant(db, tenant_id)

    with pytest.raises(DomainError):
        await HANDLER(
            db,
            tenant_id,
            items=[{"variant_id": variant.id, "quantity": 1}],
            # The right quote, the wrong conversation: server-bound scope wins.
            context=_context(other_customer, other_conversation, confirmed_quote_id=str(quote.id)),
        )
    with pytest.raises(DomainError):
        await HANDLER(
            db,
            tenant_id,
            items=[{"variant_id": variant.id, "quantity": 1}],
            context=_context(customer, conversation, confirmed_quote_id=str(uuid.uuid4())),
        )
    assert await _orders(db, tenant_id) == []


async def test_an_expired_confirmed_quote_cannot_execute(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)
    proposal = await _propose(db, tenant_id, customer, conversation, variant)
    quote = await match_confirmation(
        db,
        tenant_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        text=proposal["confirmation_code"],
    )
    quote.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()

    with pytest.raises(DomainError):
        await HANDLER(
            db,
            tenant_id,
            items=[{"variant_id": variant.id, "quantity": 2}],
            context=_context(customer, conversation, confirmed_quote_id=str(quote.id)),
        )
    assert await _orders(db, tenant_id) == []


async def test_a_stale_quote_frees_the_conversation_for_a_fresh_one(db, tenant_ctx) -> None:
    """Expiry clears BOTH phases, or one dead quote blocks the conversation."""
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)
    proposal = await _propose(db, tenant_id, customer, conversation, variant)
    quote = await match_confirmation(
        db,
        tenant_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        text=proposal["confirmation_code"],
    )
    quote.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()

    assert await live_quote(
        db, tenant_id, conversation_id=conversation.id, customer_id=customer.id
    ) is None
    fresh = await _propose(db, tenant_id, customer, conversation, variant, qty=3)
    assert fresh["quote_id"] != str(quote.id)
    assert fresh["status"] == "pending"
    assert [q.status for q in await _quotes(db, tenant_id)] == ["expired", "pending"]


async def test_a_consumed_quote_leads_to_a_new_proposal(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)
    proposal = await _propose(db, tenant_id, customer, conversation, variant)
    quote = await match_confirmation(
        db,
        tenant_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        text=proposal["confirmation_code"],
    )
    await HANDLER(
        db,
        tenant_id,
        items=[{"variant_id": variant.id, "quantity": 2}],
        context=_context(customer, conversation, confirmed_quote_id=str(quote.id)),
    )

    again = await _propose(db, tenant_id, customer, conversation, variant, qty=1)
    assert again["quote_id"] != str(quote.id)
    assert again["status"] == "pending"


# ---------------------------------------------------------------- the turn ----


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(self, session, tenant_id, **kwargs) -> AgentRunResult:
        self.calls.append(kwargs)
        return AgentRunResult(content="تمام", guardrail_decision="allow", guardrail_reason=None)


async def _run_turn(db, tenant_ctx, customer, conversation, body: str) -> _FakeRunner:
    runner = _FakeRunner()
    await run_customer_turn(
        db,
        TurnInput(
            tenant_id=tenant_ctx.tenant_id,
            conversation_id=conversation.id,
            agent_id=uuid.uuid4(),
            customer_id=customer.id,
            body=body,
        ),
        runner=runner,
    )
    return runner


async def test_the_turn_binds_a_confirmed_quote_for_the_runner(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)
    proposal = await _propose(db, tenant_id, customer, conversation, variant)

    runner = await _run_turn(db, tenant_ctx, customer, conversation, proposal["confirmation_code"])

    quote = (await _quotes(db, tenant_id))[0]
    assert runner.calls[0]["confirmed_quote_id"] == quote.id
    assert "العميل أكّد الطلب" in runner.calls[0]["knowledge_context"]


async def test_the_turn_announces_a_pending_quote_without_binding_it(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    customer, conversation = await _participant(db, tenant_id)
    variant = await _variant(db, tenant_id)
    await _propose(db, tenant_id, customer, conversation, variant)

    runner = await _run_turn(db, tenant_ctx, customer, conversation, "ممكن خصم شوية؟")

    assert runner.calls[0]["confirmed_quote_id"] is None
    context = runner.calls[0]["knowledge_context"]
    assert "مستني تأكيد العميل" in context
    assert (await _quotes(db, tenant_id))[0].code in context


async def test_a_turn_without_a_customer_skips_confirmation(db, tenant_ctx) -> None:
    runner = _FakeRunner()
    await run_customer_turn(
        db,
        TurnInput(
            tenant_id=tenant_ctx.tenant_id,
            conversation_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            body="عايز أشتري",
        ),
        runner=runner,
    )
    assert runner.calls[0]["confirmed_quote_id"] is None
    assert "مستني تأكيد" not in (runner.calls[0]["knowledge_context"] or "")
