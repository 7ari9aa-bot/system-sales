"""Turn identity — a delivered event answers the message it carried (§126/§127).

`hooks._do_auto_reply` used to search the conversation for its newest inbound
message and answer THAT. The event's own message was never passed down, so a
delayed delivery answered whichever note arrived last:

    A arrives → B arrives → A's event is delivered late
    A's event  → answers B
    B's event  → answers B again

The customer who wrote A got silence and the customer who wrote B got a
duplicate — and an idempotent worker cannot fix that, because both events
legitimately asked for work. The rule these tests pin is that the message named
by the event is the message answered.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.events.schemas import EventEnvelope
from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.models import Agent
from app.modules.ai.runtime import AgentRunner, AgentRunResult
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.workers.message_worker import _event_message_id


def _envelope(**fields: Any) -> EventEnvelope:
    base: dict[str, Any] = {
        "type": "message.received",
        "tenant_id": uuid.uuid4(),
        "aggregate_type": "message",
        "aggregate_id": uuid.uuid4(),
        "payload": {"conversation_id": str(uuid.uuid4())},
    }
    base.update(fields)
    return EventEnvelope(**base)


def test_a_stamped_event_answers_the_message_it_carries() -> None:
    message_id = uuid.uuid4()
    envelope = _envelope(payload={"message_id": str(message_id)})
    assert _event_message_id(envelope) == message_id


def test_an_explicit_null_names_no_message() -> None:
    """The approval resume sets `message_id: null` and its aggregate is an
    APPROVAL id. Reading the aggregate here would have the worker go looking for
    a message that is actually a governance row."""
    envelope = _envelope(
        aggregate_id=uuid.uuid4(),
        payload={"message_id": None},
    )
    assert _event_message_id(envelope) is None


def test_a_legacy_event_falls_back_to_its_aggregate() -> None:
    """Events staged before the key existed carried the message id as
    `aggregate_id`, and that reading is the only one available to them."""
    message_id = uuid.uuid4()
    envelope = _envelope(aggregate_id=message_id, payload={})
    assert _event_message_id(envelope) == message_id


def test_an_unparseable_id_is_no_message_rather_than_a_crash() -> None:
    """One malformed payload must not dead-letter a customer's message."""
    envelope = _envelope(payload={"message_id": "not-a-uuid"})
    assert _event_message_id(envelope) is None


class _RecordingRunner:
    """Captures what the hook hands the runner, and answers plainly."""

    def __init__(self) -> None:
        self.user_messages: list[str] = []

    async def run(self, session, tenant_id, **kwargs) -> AgentRunResult:
        self.user_messages.append(kwargs["user_message"])
        return AgentRunResult(content="تمام", run_id=uuid.uuid4())


async def _conversation_with_two_inbounds(db, tenant_id):
    db.add(Agent(tenant_id=tenant_id, name="Sales Agent", model="fast", system_prompt="s"))
    customer = Customer(tenant_id=tenant_id, name="Identity Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    first = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="عايز الهودي",
    )
    second = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="والبنطي؟",
    )
    await db.flush()
    return conversation, first, second


async def test_the_named_message_is_answered_even_when_a_newer_one_exists(
    db, tenant_ctx, monkeypatch
):
    tenant_id = tenant_ctx.tenant_id
    conversation, first, second = await _conversation_with_two_inbounds(db, tenant_id)
    runner = _RecordingRunner()
    monkeypatch.setattr(AgentRunner, "run", runner.run)

    await maybe_auto_reply(db, tenant_id, conversation.id, inbound_message_id=first.id)

    assert runner.user_messages == ["عايز الهودي"], (
        f"answered {runner.user_messages!r}: the delayed event for the first "
        "message answered the second one instead"
    )


async def test_without_a_named_message_the_newest_inbound_is_answered(
    db, tenant_ctx, monkeypatch
):
    """The resume path: no message is named, so the conversation's current
    context is re-evaluated rather than a stale one."""
    tenant_id = tenant_ctx.tenant_id
    conversation, _first, _second = await _conversation_with_two_inbounds(db, tenant_id)
    runner = _RecordingRunner()
    monkeypatch.setattr(AgentRunner, "run", runner.run)

    await maybe_auto_reply(db, tenant_id, conversation.id)

    assert runner.user_messages == ["والبنطي؟"]


async def test_an_outbound_message_never_becomes_the_turn(
    db, tenant_ctx, monkeypatch
):
    """A message id from the wrong side of the thread is not a customer turn."""
    tenant_id = tenant_ctx.tenant_id
    conversation, _first, _second = await _conversation_with_two_inbounds(db, tenant_id)
    outbound = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="ai",
        body="رد قديم",
    )
    await db.flush()
    runner = _RecordingRunner()
    monkeypatch.setattr(AgentRunner, "run", runner.run)

    await maybe_auto_reply(db, tenant_id, conversation.id, inbound_message_id=outbound.id)

    assert runner.user_messages == [], "the agent was driven by its own reply"


async def test_a_message_id_from_another_conversation_is_ignored(
    db, tenant_ctx, monkeypatch
):
    tenant_id = tenant_ctx.tenant_id
    conversation, first, _second = await _conversation_with_two_inbounds(db, tenant_id)
    other_customer = Customer(tenant_id=tenant_id, name="Other Customer")
    db.add(other_customer)
    await db.flush()
    other = await ConversationService.get_or_create(
        db, tenant_id, customer_id=other_customer.id, channel="webchat"
    )
    alien = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=other.id,
        direction="inbound",
        sender_type="customer",
        body="رسالة محادثة تانية",
    )
    await db.flush()
    runner = _RecordingRunner()
    monkeypatch.setattr(AgentRunner, "run", runner.run)

    await maybe_auto_reply(db, tenant_id, conversation.id, inbound_message_id=alien.id)

    # Refused as a turn, but the fallback answers this conversation's newest
    # inbound — the point is that the foreign row never becomes the prompt.
    assert runner.user_messages == ["والبنطي؟"]
