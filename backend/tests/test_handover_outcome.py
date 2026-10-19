"""P1-11 — §37/§150: a handover has two halves, and both are now real.

The intake half is now the MODEL's decision: the handover_to_human tool
turns "the agent concluded this needs a person" into the same durable row the
deterministic paths write. The old keyword detector is gone — a keyword that
matched inside a correctly-understood message forced the whole turn down the
wrong path.

The outcome half: closing a handover must record WHO closed it, WHEN and WITH
WHAT RESULT. The resolve route used to flip `status` and leave no trace, so
the queue could count handovers created but never handovers answered.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationError
from app.modules.ai.handover import OPEN_HANDOVER_STATUSES, request_human_takeover
from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.models import Agent, AIHandover
from app.modules.ai.router import resolve_handover
from app.modules.ai.runtime import AgentRunner
from app.modules.conversations.models import Conversation, Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.platform.models import OutboxEvent

# ------------------------------------------------------------- the intake ----


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


async def test_the_model_escalation_tool_creates_the_handover(db, tenant_ctx) -> None:
    """The reason vocabulary now has a MODEL producer: handover_to_human."""
    from app.modules.ai.tools import get_tool

    tenant_id = tenant_ctx.tenant_id
    await _customer_agent(db, tenant_id)
    _customer, conversation, _message = await _inbound(db, tenant_id, "المشكلة معقدة")

    spec = get_tool("handover_to_human")
    result = await spec.handler(
        db,
        tenant_id,
        reason="complex_problem",
        summary="المشكلة خارج سياسات المتجر المسجلة",
        context={"conversation_id": str(conversation.id)},
    )
    assert result["status"] == "handover_recorded"
    await db.flush()

    handover = (
        (await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert handover.reason == "complex_problem"
    assert handover.status == "pending"

    refreshed = await ConversationService.get(db, tenant_id, conversation.id)
    assert refreshed.status == "waiting_human"

    events = (
        (
            await db.execute(
                select(OutboxEvent).where(OutboxEvent.meta["tenant_id"].astext == str(tenant_id))
            )
        )
        .scalars()
        .all()
    )
    assert {e.payload["event_type"] for e in events} == {"ai.handover.created"}


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


def test_the_open_status_vocabulary_is_unchanged() -> None:
    # `AIHandover.status` documents: pending | claimed | resolved.
    assert set(OPEN_HANDOVER_STATUSES) == {"pending", "claimed"}


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


# --------------------------------------- waiting_human re-arm (Oct-19) ----


async def _set_status(db, tenant_id, conversation_id, status):
    await ConversationService.set_status(db, tenant_id, conversation_id, status)
    await db.flush()


async def test_a_dead_handover_does_not_jail_the_conversation_forever(
    db, tenant_ctx, monkeypatch
):
    """THE Oct-19 incident: the Oct-17 failure handover left the telegram
    conversation in waiting_human for days while the customer kept typing
    into silence. The re-arm rule: with NO staff reply after the handover,
    the customer's new message re-opens the conversation and the agent gets
    one more attempt — handing over again if it still cannot answer."""
    tenant_id = tenant_ctx.tenant_id
    await _customer_agent(db, tenant_id)
    customer, conversation, _message = await _inbound(db, tenant_id, "هلا")

    # A handover with NO staff reply follows — the jail shape.
    await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="failure", note="old"
    )
    await _set_status(db, tenant_id, conversation.id, "waiting_human")

    async def answered(self, session, tenant_id_, **kwargs):
        from app.modules.ai.runtime import AgentRunResult

        return AgentRunResult(content="أهلاً بيك!", guardrail_decision="allow")

    monkeypatch.setattr(AgentRunner, "run", answered)

    await maybe_auto_reply(db, tenant_id, conversation.id)

    refreshed = await ConversationService.get(db, tenant_id, conversation.id)
    assert refreshed.status == "open"
    outbound = (
        (
            await db.execute(
                select(Message).where(
                    Message.tenant_id == tenant_id,
                    Message.conversation_id == conversation.id,
                    Message.direction == "outbound",
                )
            )
        )
        .scalars()
        .all()
    )
    assert any(m.body == "أهلاً بيك!" for m in outbound)


async def test_a_staff_reply_keeps_the_human_commitment(db, tenant_ctx, monkeypatch):
    """A6 holds when the human actually took over: a staff outbound after the
    handover keeps waiting_human — the agent must not talk over them."""
    tenant_id = tenant_ctx.tenant_id
    await _customer_agent(db, tenant_id)
    customer, conversation, _message = await _inbound(db, tenant_id, "هلا")

    await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="failure", note="old"
    )
    await _set_status(db, tenant_id, conversation.id, "waiting_human")
    # The staff reply and the second customer message are added in one
    # flush, and Message.created_at is a SERVER default (the DB clock) —
    # every row lands on the same instant. The test WRITES the timeline it
    # needs: handover < staff reply < customer. Production ordering comes
    # from the wire, not from this harness.
    from datetime import UTC, datetime, timedelta

    staff_reply = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="agent",
        body="معاك أحمد من الفريق",
    )
    customer_again = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="لسه فيه؟",
    )
    base = datetime.now(UTC)
    await db.execute(
        text("UPDATE messages SET created_at = :t WHERE id = :id"),
        [
            {"t": base + timedelta(seconds=10), "id": str(staff_reply.id)},
            {"t": base + timedelta(seconds=20), "id": str(customer_again.id)},
        ],
    )
    await db.flush()
    # Message.created_at is a server default: the ORM objects still carry
    # the flush-time value in their identity map, and the hook reads the
    # created_at OFF the ORM — refresh so it re-reads the written clock.
    await db.refresh(staff_reply)
    await db.refresh(customer_again)
    # The ORM objects are expired (the timeline rewrite) — read the written
    # clocks back BEFORE the hook runs, so its comparisons come off the DB.
    await db.refresh(staff_reply)
    await db.refresh(customer_again)

    ai_calls: list = []

    async def counted_run(self, session, tenant_id_, **kwargs):
        ai_calls.append(kwargs.get("user_message"))
        from app.modules.ai.runtime import AgentRunResult

        return AgentRunResult(content="should not happen", guardrail_decision="allow")

    monkeypatch.setattr(AgentRunner, "run", counted_run)

    await maybe_auto_reply(db, tenant_id, conversation.id)

    # A6 held: the agent never ran over the active staff reply...
    assert ai_calls == []
    # ...and the conversation stayed with the human.
    refreshed = await ConversationService.get(db, tenant_id, conversation.id)
    assert refreshed.status == "waiting_human"


async def test_an_resolved_handover_releases_the_conversation(db, tenant_ctx, monkeypatch):
    """A RESOLVED handover is a finished commitment: the human closed it —
    the next customer message goes back to the agent without ceremony."""
    tenant_id = tenant_ctx.tenant_id
    await _customer_agent(db, tenant_id)
    customer, conversation, _message = await _inbound(db, tenant_id, "هلا")

    handover_created = await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="failure", note="old"
    )
    assert handover_created is True
    await _set_status(db, tenant_id, conversation.id, "waiting_human")
    # The human resolved the handover from the queue (no in-thread reply).
    (
        await db.execute(
            text(
                "UPDATE ai_handovers SET status = 'resolved', resolved_at = now() "
                "WHERE conversation_id = :cid AND status = 'pending'"
            ),
            {"cid": str(conversation.id)},
        )
    )
    await db.flush()

    async def answered(self, session, tenant_id_, **kwargs):
        from app.modules.ai.runtime import AgentRunResult

        return AgentRunResult(content="رجعنا ليك", guardrail_decision="allow")

    monkeypatch.setattr(AgentRunner, "run", answered)

    await maybe_auto_reply(db, tenant_id, conversation.id)

    refreshed = await ConversationService.get(db, tenant_id, conversation.id)
    assert refreshed.status == "open"
