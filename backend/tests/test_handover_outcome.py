"""P1-11 — §37/§150: a handover has two halves, and both are now real.

The intake half: a customer who asks for a person must PRODUCE a handover row.
Before this, `customer_request` was vocabulary with no writer — the model just
answered the request itself, and nothing in the system knew the customer had
asked to stop talking to it.

The outcome half: closing a handover must record WHO closed it, WHEN and WITH
WHAT RESULT. The resolve route used to flip `status` and leave no trace, so
the queue could count handovers created but never handovers answered.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationError
from app.modules.ai.agents.customer.turn import wants_human_request
from app.modules.ai.handover import request_human_takeover
from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.models import Agent, AIHandover
from app.modules.ai.router import resolve_handover
from app.modules.ai.runtime import AgentRunner
from app.modules.conversations.models import Conversation, Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.platform.models import OutboxEvent

# ------------------------------------------------------------------ the ask ----


@pytest.mark.parametrize(
    "text",
    [
        "عايز أتكلم مع حد من الفريق",
        "أريد التحدث مع موظف",
        "مش عايز روبوت، عايز انسان",
        "لو ممكن كلام مع مسؤول",
        "نفسى أكلم خدمة العملاء",
        "I'd like to talk to a human please",
    ],
)
def test_asking_for_a_person_is_detected(text: str) -> None:
    assert wants_human_request(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "عايز أعرف السعر",
        "الموظف اللي بعتلي Says the price is 200",  # a person mentioned, not asked for
        "هو انت روبوت؟",  # a question ABOUT the bot, not a request for a person
        "عايز اشتري اتنين",
        None,
        "",
    ],
)
def test_everything_else_is_not(text: str | None) -> None:
    assert wants_human_request(text) is False


async def _customer_agent(db: AsyncSession, tenant_id: uuid.UUID) -> None:
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


async def _inbound(db: AsyncSession, tenant_id: uuid.UUID, body: str):
    customer = Customer(tenant_id=tenant_id, name="Asking Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    message = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body=body,
    )
    await db.flush()
    return customer, conversation, message


# ------------------------------------------------- customer_request producer --


async def test_asking_for_a_human_creates_the_handover(db, tenant_ctx, monkeypatch) -> None:
    """The whole point: the reason vocabulary now has a writer."""
    tenant_id = tenant_ctx.tenant_id
    await _customer_agent(db, tenant_id)
    _customer, conversation, _message = await _inbound(db, tenant_id, "عايز أتكلم مع موظف")

    async def no_model_call(self, session, tenant_id_, **kwargs):
        raise AssertionError("a customer who asked for a human must not spend a model call")

    monkeypatch.setattr(AgentRunner, "run", no_model_call)

    await maybe_auto_reply(db, tenant_id, conversation.id)

    handover = (
        (await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert handover.reason == "customer_request"
    assert handover.status == "pending"

    refreshed = await ConversationService.get(db, tenant_id, conversation.id)
    assert refreshed.status == "waiting_human"

    # The customer is not left in silence: an ack went out, and the handover
    # event is what a human's queue reads.
    outbound = (
        (
            await db.execute(
                select(Message).where(
                    Message.tenant_id == tenant_id,
                    Message.direction == "outbound",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(outbound) == 1
    assert "شخص من الفريق" in (outbound[0].body or "")
    events = (
        (
            await db.execute(
                select(OutboxEvent).where(OutboxEvent.meta["tenant_id"].astext == str(tenant_id))
            )
        )
        .scalars()
        .all()
    )
    assert {e.payload["event_type"] for e in events} == {"message.outbound", "ai.handover.created"}


async def test_an_ordinary_question_does_not_hand_over(db, tenant_ctx, monkeypatch) -> None:
    tenant_id = tenant_ctx.tenant_id
    await _customer_agent(db, tenant_id)
    _customer, conversation, _message = await _inbound(db, tenant_id, "عايز أعرف السعر")

    async def answered(self, session, tenant_id_, **kwargs):
        from app.modules.ai.runtime import AgentRunResult

        return AgentRunResult(content="السعر 250", guardrail_decision="allow")

    monkeypatch.setattr(AgentRunner, "run", answered)

    await maybe_auto_reply(db, tenant_id, conversation.id)

    assert (
        await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id))
    ).scalars().all() == []


# ------------------------------------------------------- the outcome fields ----


async def _open_handover(db: AsyncSession, tenant_id: uuid.UUID):
    customer = Customer(tenant_id=tenant_id, name="Outcome Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    created = await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="guardrail", note="policy"
    )
    assert created is True
    await db.flush()
    handover = (
        (
            await db.execute(
                select(AIHandover).where(
                    AIHandover.tenant_id == tenant_id, AIHandover.note == "policy"
                )
            )
        )
        .scalars()
        .one()
    )
    return conversation, handover


def _ctx(db: AsyncSession, tenant_ctx) -> SimpleNamespace:
    """The three fields `resolve_handover` reads off the request context."""
    return SimpleNamespace(
        session=db,
        tenant_id=tenant_ctx.tenant_id,
        user_id=tenant_ctx.user.id,
    )


async def test_resolving_records_who_when_and_with_what_result(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    conversation, handover = await _open_handover(db, tenant_id)

    out = await resolve_handover(
        handover.id,
        _ctx(db, tenant_ctx),
        SimpleNamespace(outcome="answered", note="وضحنا سعر الشحنه للعميل"),
    )

    assert out.status == "resolved"
    assert out.resolved_by_user_id == tenant_ctx.user.id
    assert out.resolved_at is not None
    assert out.outcome == "answered"
    assert out.outcome_note == "وضحنا سعر الشحنه للعميل"

    # The route flips the status with a Core UPDATE; this session's identity
    # map still holds the waiting_human object, so read the column straight
    # from the table. (expire_all would force a synchronous refresh on the
    # next attribute touch — MissingGreenlet in an async session.)
    refreshed_status = (
        await db.execute(select(Conversation.status).where(Conversation.id == conversation.id))
    ).scalar_one()
    assert refreshed_status == "open"

    events = (
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.meta["tenant_id"].astext == str(tenant_id),
                    OutboxEvent.payload["event_type"].as_string() == "ai.handover.resolved",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].payload["outcome"] == "answered"
    assert events[0].payload["resolved_by_user_id"] == str(tenant_ctx.user.id)


async def test_an_outcome_outside_the_vocabulary_is_refused(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    _conversation, handover = await _open_handover(db, tenant_id)

    with pytest.raises(ValidationError):
        await resolve_handover(
            handover.id,
            _ctx(db, tenant_ctx),
            SimpleNamespace(outcome="probably_fine", note=None),
        )

    stored = await db.get(AIHandover, handover.id)
    assert stored.status != "resolved"
    assert stored.resolved_by_user_id is None


async def test_resolving_twice_does_not_overwrite_the_first_record(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    _conversation, handover = await _open_handover(db, tenant_id)
    ctx = _ctx(db, tenant_ctx)
    await resolve_handover(handover.id, ctx, SimpleNamespace(outcome="answered", note=None))

    with pytest.raises(ConflictError):
        await resolve_handover(
            handover.id, ctx, SimpleNamespace(outcome="customer_unreachable", note="second")
        )

    stored = await db.get(AIHandover, handover.id)
    assert stored.outcome == "answered"
    assert stored.resolved_by_user_id == tenant_ctx.user.id


async def test_a_resolve_without_a_body_still_records_who_and_when(db, tenant_ctx) -> None:
    """Backward compatible: an existing caller that posts no body still closes
    the row, and the trace of who/when is the part that must never be lost."""
    _conversation, handover = await _open_handover(db, tenant_ctx.tenant_id)

    out = await resolve_handover(handover.id, _ctx(db, tenant_ctx), None)

    assert out.status == "resolved"
    assert out.resolved_by_user_id == tenant_ctx.user.id
    assert out.outcome is None
