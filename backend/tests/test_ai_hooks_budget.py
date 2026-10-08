"""A spent AI budget must reach a human, not the dead-letter queue.

Two ceilings used to fail in two different silent ways: the fairness gate
raised ``ValidationError``, which the worker classifies as PERMANENT and
dead-letters on the spot, and the cost cap raised a bare
``RateLimitExceededError``, which burned five retries against a ceiling that
cannot rise and then dead-lettered too. Either way the customer got silence and
no human was told a conversation was waiting. Both now raise
``AIBudgetExhaustedError`` and the auto-reply hook converts it into the same
handover the guardrail and messaging-window paths already used.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.errors import RateLimitExceededError, ValidationError
from app.modules.ai.gateway import AIBudgetExhaustedError, _on_budget_exceeded
from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.models import Agent, AIHandover
from app.modules.ai.runtime import AgentRunner
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.platform.models import OutboxEvent


def test_block_mode_raises_the_budget_error() -> None:
    with pytest.raises(AIBudgetExhaustedError):
        _on_budget_exceeded("block", "monthly AI budget exceeded", details={})


def test_the_budget_error_is_a_rate_limit_and_not_a_validation_error() -> None:
    """The classification IS the fix.

    ``workers/base.py`` puts ``ValidationError`` in its permanent-failure set
    and ``RateLimitExceededError`` outside it, so which base class a spent
    budget raises decides whether the customer's message is dead-lettered
    immediately or after five pointless retries. Neither is a handover.
    """
    assert issubclass(AIBudgetExhaustedError, RateLimitExceededError)
    assert not issubclass(AIBudgetExhaustedError, ValidationError)


async def test_a_spent_budget_parks_the_conversation_on_a_human(
    db, tenant_ctx, monkeypatch
) -> None:
    tenant_id = tenant_ctx.tenant_id
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
    customer = Customer(tenant_id=tenant_id, name="Budget Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="عايز أعرف السعر",
    )
    await db.flush()

    async def exhausted(self, session, tenant_id_, **kwargs):
        raise AIBudgetExhaustedError("monthly AI budget exceeded")

    monkeypatch.setattr(AgentRunner, "run", exhausted)

    await maybe_auto_reply(db, tenant_id, conversation.id)

    handover = (
        (await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert handover.reason == "budget"
    assert handover.status == "pending"
    assert "monthly AI budget exceeded" in (handover.note or "")

    refreshed = await ConversationService.get(db, tenant_id, conversation.id)
    assert refreshed.status == "waiting_human"

    # Exactly one event, and it is the handover: nothing was sent to the
    # customer, so there is no `message.outbound` pretending otherwise.
    events = (
        (await db.execute(select(OutboxEvent).where(OutboxEvent.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert [event.payload["event_type"] for event in events] == ["ai.handover.created"]
