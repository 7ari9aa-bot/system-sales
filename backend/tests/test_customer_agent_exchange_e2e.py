"""The exchange conversation through the REAL runtime, with only the model scripted.

A ground-shop customer writes from any chat, gives the number printed on the receipt and
asks for another size. Everything except the model's words is production code: the
provisioned agent and its tool rows, the registry authorization, argument validation, the
two handlers, the ledger and the grounding check.

This does NOT prove how a real model behaves (it says what the script tells it to say). It
proves the wiring: that the invoice tool is offered, that its result reaches the next
step, that the next tool call can use the product id read from the invoice, and that the
reply built on those facts survives the grounding check without a handover.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from app.modules.ai.agents.customer.turn import TurnInput, run_customer_turn
from app.modules.ai.core.provisioning import provision_canonical_agents
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.ai.runtime import AgentRunner
from app.modules.catalog.service import CatalogService
from app.modules.customers.models import Customer
from app.modules.inventory.service import InventoryService
from app.modules.pos.service import PosService
from tests._pos_sell import sell


async def _agent(db, tenant_id) -> Agent:
    await provision_canonical_agents(db, tenant_id)
    await db.flush()
    return (
        await db.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.kind == "customer")
        )
    ).scalar_one()


async def _conversation(db, tenant_id, channel: str) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.conversations.models import Conversation

    customer = Customer(tenant_id=tenant_id, name="عميل الشات")
    db.add(customer)
    await db.flush()
    conversation = Conversation(tenant_id=tenant_id, customer_id=customer.id, channel=channel)
    db.add(conversation)
    await db.flush()
    return customer.id, conversation.id


async def _shop(db, tenant_id):
    """A till sale of one size-M shirt; L is on the shelf, XL is sold out."""
    warehouse = await InventoryService.get_default_warehouse(db, tenant_id)
    register = await PosService.create_register(
        db, tenant_id, name="كاشير", code=f"REG-{uuid.uuid4().hex[:6]}", warehouse_id=warehouse.id
    )
    till = await PosService.open_session(db, tenant_id, register.id)
    product = await CatalogService.create_product(
        db, tenant_id, title="تيشيرت قطن", slug=f"t-{uuid.uuid4().hex[:10]}"
    )
    product = await CatalogService.update_product(db, tenant_id, product.id, status="active")
    variants = {}
    for size, price, stock in (("M", "25.00", 5), ("L", "25.00", 3), ("XL", "30.00", 0)):
        variants[size] = await CatalogService.add_variant(
            db, tenant_id, product.id, title=size, option_values={"size": size}, price=price
        )
        if stock:
            await InventoryService.move(
                db,
                tenant_id,
                variants[size].id,
                warehouse.id,
                direction="in",
                quantity=stock,
                reason="purchase",
            )
    sold = await sell(
        db,
        tenant_id,
        till.id,
        items=[{"variant_id": str(variants["M"].id), "quantity": 1}],
    )
    number = (
        await db.execute(text("SELECT number FROM orders WHERE id = :i"), {"i": sold["order_id"]})
    ).scalar_one()
    return number, product, variants


def _script(monkeypatch, *steps: ChatCompletionResult) -> dict:
    seen: dict = {"calls": []}
    queue = list(steps)

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        seen["calls"].append({"messages": messages, "tools": tools})
        return queue.pop(0)

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return seen


def _calls(call_id: str, name: str, **arguments) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=None,
        tool_calls=[ToolCallRequest(id=call_id, name=name, arguments=arguments)],
        tokens_in=1,
        tokens_out=1,
        raw_model="m",
    )


def _says(text_: str) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=text_, tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
    )


async def _turn(db, tenant_id, agent, customer_id, conversation_id, body):
    return await run_customer_turn(
        db,
        TurnInput(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            agent_id=agent.id,
            customer_id=customer_id,
            inbound_message_id=uuid.uuid4(),
            body=body,
        ),
        runner=AgentRunner(gateway=AIGateway()),
    )


async def _tool_rows(db, conversation_id) -> list[tuple[str, str]]:
    rows = (
        await db.execute(
            text(
                "SELECT t.name, t.status FROM tool_calls t "
                "JOIN agent_runs r ON r.id = t.run_id "
                "WHERE r.conversation_id = :c ORDER BY t.created_at"
            ),
            {"c": conversation_id},
        )
    ).all()
    return [(r[0], r[1]) for r in rows]


async def _open_handovers(db, conversation_id) -> int:
    return (
        await db.execute(
            text("SELECT count(*) FROM ai_handovers WHERE conversation_id = :c"),
            {"c": conversation_id},
        )
    ).scalar_one()


@pytest.mark.parametrize("channel", ["telegram", "messenger", "instagram", "webchat", "whatsapp"])
async def test_the_invoice_number_leads_to_the_other_sizes_without_a_handover(
    db, tenant_ctx, monkeypatch, channel
) -> None:
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent(db, tenant_id)
    number, product, variants = await _shop(db, tenant_id)
    customer_id, conversation_id = await _conversation(db, tenant_id, channel)
    seen = _script(
        monkeypatch,
        _calls("c1", "get_my_orders", number=number),
        _calls("c2", "get_product_details", product_id=str(product.id)),
        _says("المقاس L متاح بنفس السعر 25 جنيه، والـXL خلصان. تحب أي مقاس؟"),
    )

    outcome = await _turn(
        db, tenant_id, agent, customer_id, conversation_id, f"فاتورتي {number} عايز أبدل المقاس"
    )

    # the invoice tool is on offer to the model, on every channel
    offered = {t["function"]["name"] for t in seen["calls"][0]["tools"]}
    assert "get_my_orders" in offered
    # both tools ran for real, in order, and succeeded
    rows = await _tool_rows(db, conversation_id)
    assert [name for name, _ in rows][:2] == ["get_my_orders", "get_product_details"]
    detail = (
        await db.execute(
            text(
                "SELECT t.name, t.status, t.error FROM tool_calls t "
                "JOIN agent_runs r ON r.id = t.run_id WHERE r.conversation_id = :c "
                "ORDER BY t.created_at"
            ),
            {"c": conversation_id},
        )
    ).all()
    assert all(status == "ok" for _, status in rows[:2]), detail
    # the invoice result reached the model on the next step, carrying the product id
    second_step = str(seen["calls"][1]["messages"])
    assert str(product.id) in second_step and "option_values" in second_step
    # the answer went out, was not blocked by the grounding check, and nobody was handed over
    assert outcome.reply and "L" in outcome.reply
    assert outcome.blocked_reason is None
    assert outcome.handover_reason is None
    assert await _open_handovers(db, conversation_id) == 0


async def test_a_wrong_invoice_number_is_answered_not_handed_over(
    db, tenant_ctx, monkeypatch
) -> None:
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent(db, tenant_id)
    await _shop(db, tenant_id)
    customer_id, conversation_id = await _conversation(db, tenant_id, "telegram")
    _script(
        monkeypatch,
        _calls("c1", "get_my_orders", number="NOPE-000"),
        _says("الرقم ده مش لاقيه عندي. ممكن تراجعه على الإيصال وتبعتهولي تاني؟"),
    )

    outcome = await _turn(
        db, tenant_id, agent, customer_id, conversation_id, "فاتورتي NOPE-000 عايز أبدل"
    )

    assert [n for n, _ in await _tool_rows(db, conversation_id)] == ["get_my_orders"]
    assert outcome.reply and outcome.handover_reason is None
    assert await _open_handovers(db, conversation_id) == 0


async def test_the_model_cannot_name_a_customer_or_list_invoices(
    db, tenant_ctx, monkeypatch
) -> None:
    """Arguments are validated by the real registry: an extra field is refused."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent(db, tenant_id)
    number, _product, _variants = await _shop(db, tenant_id)
    customer_id, conversation_id = await _conversation(db, tenant_id, "telegram")
    _script(
        monkeypatch,
        _calls("c1", "get_my_orders", number=number, customer_id=str(uuid.uuid4())),
        _says("مقدرتش أفتح الفاتورة، ممكن تبعتلي الرقم تاني؟"),
    )

    await _turn(db, tenant_id, agent, customer_id, conversation_id, f"فاتورتي {number}")

    rows = await _tool_rows(db, conversation_id)
    assert rows and rows[0][0] == "get_my_orders" and rows[0][1] != "ok"


async def test_a_plain_size_question_is_answered_from_the_catalog_without_a_handover(
    db, tenant_ctx, monkeypatch
) -> None:
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent(db, tenant_id)
    _number, product, _variants = await _shop(db, tenant_id)
    customer_id, conversation_id = await _conversation(db, tenant_id, "messenger")
    _script(
        monkeypatch,
        _calls("c1", "get_product_details", product_id=str(product.id)),
        _says("المقاسات المتاحة M وL بسعر 25 جنيه، والـXL خلصان."),
    )

    outcome = await _turn(
        db, tenant_id, agent, customer_id, conversation_id, "التيشيرت القطن عندكم مقاسات إيه؟"
    )

    assert outcome.reply and outcome.handover_reason is None
    assert await _open_handovers(db, conversation_id) == 0


async def test_a_wish_to_buy_is_not_a_reason_to_hand_over(db, tenant_ctx, monkeypatch) -> None:
    """The old purchase_intent reason is gone: the runtime refuses it, no handover row appears."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent(db, tenant_id)
    customer_id, conversation_id = await _conversation(db, tenant_id, "telegram")
    _script(
        monkeypatch,
        _calls("c1", "handover_to_human", reason="purchase_intent", summary="wants to buy"),
        _says("تحب تعرف طريقة الشراء؟ قولي المنتج اللي عاجبك."),
    )

    await _turn(db, tenant_id, agent, customer_id, conversation_id, "عايز أشتري تيشيرت")

    assert await _open_handovers(db, conversation_id) == 0
    assert [(n, s) for n, s in await _tool_rows(db, conversation_id)] == [
        ("handover_to_human", "error")
    ]


async def test_a_real_unsolved_problem_hands_over_once_with_what_was_tried(
    db, tenant_ctx, monkeypatch
) -> None:
    tenant_id = tenant_ctx.tenant_id
    agent = await _agent(db, tenant_id)
    customer_id, conversation_id = await _conversation(db, tenant_id, "telegram")
    _script(
        monkeypatch,
        _calls(
            "c1",
            "handover_to_human",
            reason="complex_problem",
            summary="الطلب اتأخر 10 أيام، جربت خطوات المتجر المكتوبة ومفيش حل.",
        ),
        _says("هحوّلك لحد من الفريق يكمل معاك."),
    )

    outcome = await _turn(
        db, tenant_id, agent, customer_id, conversation_id, "طلبي متأخر وزهقت من الانتظار"
    )

    assert outcome.reply
    assert await _open_handovers(db, conversation_id) == 1
    note = (
        await db.execute(
            text("SELECT reason, note FROM ai_handovers WHERE conversation_id = :c"),
            {"c": conversation_id},
        )
    ).one()
    assert note[0] == "complex_problem" and "جربت" in (note[1] or "")
