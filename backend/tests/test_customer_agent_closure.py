"""Customer-agent closure pins — the two gaps a reply-only agent still owes.

The crash window: the AI reply commits in its own transaction and the
ProcessedEvent marker in a LATER one, so a worker that dies between them (or a
stale-claim reclaim) re-delivers the event and the customer got the same answer
twice. The reply now threads to the inbound via ``reply_to_message_id`` and the
hook refuses a second turn against an already-answered inbound.

The dead-end handover: ``ai.handover.created`` reached the SSE stream but
nobody persistent — a merchant not watching the inbox page never learned a
conversation was waiting. The takeover now writes the owners' notification in
the same transaction as the handover row itself.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.modules.ai.handover import request_human_takeover
from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.models import Agent, AIHandover
from app.modules.ai.runtime import AgentRunner
from app.modules.conversations.models import Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.notifications.models import Notification


def _runner_result(reply: str, *, grounded_in: dict | None = None) -> SimpleNamespace:
    """The minimal AgentRunResult the hook consumes: an allowed, text-only reply
    with no media and no handover request.

    A reply that states a figure must have a tool result behind it — the turn
    withholds an unsourced number. ``grounded_in`` is that tool result, so a
    test about *delivery* (not about grounding) can still say "السعر ٢٥٠"
    honestly instead of leaning on the unsourced-number gap."""
    return SimpleNamespace(
        content=reply,
        guardrail_decision="allow",
        guardrail_reason=None,
        tool_calls_made=(
            [{"name": "search_catalog", "status": "ok", "result": grounded_in}]
            if grounded_in is not None
            else []
        ),
        shown_product_ids=[],
        media=[],
        tokens_in=10,
        tokens_out=10,
        run_id=uuid.uuid4(),
    )


async def _seed_conversation_with_inbound(db, tenant_id) -> tuple:
    db.add(
        Agent(
            tenant_id=tenant_id,
            kind="customer",
            name="Sales Agent",
            model="fast",
            system_prompt="s",
            is_active=True,
        )
    )
    customer = Customer(tenant_id=tenant_id, name="Closure Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    inbound = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="عايز أعرف السعر",
    )
    await db.flush()
    return conversation, inbound


async def _ai_replies(db, tenant_id) -> list:
    return list(
        (
            await db.execute(
                select(Message).where(
                    Message.tenant_id == tenant_id,
                    Message.sender_type == "ai",
                )
            )
        )
        .scalars()
        .all()
    )


async def test_the_same_inbound_is_never_answered_twice(db, tenant_ctx, monkeypatch):
    tenant_id = tenant_ctx.tenant_id
    conversation, inbound = await _seed_conversation_with_inbound(db, tenant_id)

    async def reply_once(self, session, tenant_id_, **kwargs):
        return _runner_result("السعر ٢٥٠ جنيه", grounded_in={"price": "250.00"})

    monkeypatch.setattr(AgentRunner, "run", reply_once)

    # The delivered event, then its re-delivery: the crash window or a replay
    # puts the SAME inbound message back through the worker.
    await maybe_auto_reply(db, tenant_id, conversation.id, inbound_message_id=inbound.id)
    await maybe_auto_reply(db, tenant_id, conversation.id, inbound_message_id=inbound.id)

    replies = await _ai_replies(db, tenant_id)
    assert len(replies) == 1, "the second delivery re-answered an already-answered inbound"
    assert replies[0].reply_to_message_id == inbound.id, (
        "an AI reply must thread to the inbound it answers — that link IS the guard"
    )


async def test_a_human_reply_does_not_count_as_an_ai_answer(db, tenant_ctx):
    """The guard suppresses AI duplicates, not staff work: a human outbound
    threaded to the inbound must not stop the AI from answering, and the AI
    answering must not stop a human — only sender_type='ai' rows count."""
    tenant_id = tenant_ctx.tenant_id
    customer = Customer(tenant_id=tenant_id, name="Human First")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    inbound = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="hello",
    )
    await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="agent",
        body="human replying",
        reply_to_message_id=inbound.id,
    )
    await db.flush()

    assert await ConversationService.find_ai_reply(db, tenant_id, inbound.id) is None


async def test_a_handover_notifies_the_owners(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = Customer(tenant_id=tenant_id, name="Handover Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )

    created = await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="guardrail", run_id=None
    )
    assert created is True

    notifications = list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.kind == "ai_handover",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(notifications) == 1, "the owner was never told a conversation is waiting"
    assert notifications[0].user_id == tenant_ctx.user.id
    assert notifications[0].payload["conversation_id"] == str(conversation.id)

    # Three withhold paths can fire back-to-back on one stuck conversation.
    # §150's idempotency contract — and the partial unique index
    # `uq_handovers_open_conversation` — allow ONE OPEN row per conversation, so
    # the second and third calls are no-ops: the queue is not tripled, the owner
    # is not rung again for the same problem, and a database that already carries
    # the index refuses a second open row even if a caller tries to bypass the
    # service.
    again_guardrail = await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="guardrail", run_id=None
    )
    again_budget = await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="budget", run_id=None
    )
    assert again_guardrail is False, "a second open handover was created"
    assert again_budget is False, "a second open handover was created"

    handovers = list(
        (await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    notifications = list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.kind == "ai_handover",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(handovers) == 1, "one conversation, one open handover"
    assert len(notifications) == 1, "one problem, one bell"


async def test_a_closed_conversation_notifies_nobody(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = Customer(tenant_id=tenant_id, name="Already Closed")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    await ConversationService.set_status(db, tenant_id, conversation.id, "closed")

    created = await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="budget", run_id=None
    )

    assert created is False
    rows = list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.kind == "ai_handover",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows == [], "a finished thread must not ring the owners' bell"
