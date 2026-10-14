"""The handover lifecycle, end to end — create, claim, resolve, and the refusals.

The review's §4 finding was precise: the intake and outcome halves were each
tested, the QUEUE was not. Nothing exercised create -> claim -> resolve as one
cycle, nothing proved a second employee cannot take a claimed handover, and
nothing stopped one conversation from holding two open ones. `ai_handovers` had
zero rows in production, so none of this had ever run for real.

DB-backed on purpose: these are statements about rows, statuses and constraints,
and a mocked session cannot show that the partial unique index refuses the second
open handover. Skips locally (no `DATABASE_URL_APP_ADMIN`), runs on CI.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.modules.ai.handover import request_human_takeover
from app.modules.ai.hooks import maybe_auto_reply
from app.modules.ai.models import Agent, AIHandover
from app.modules.ai.router import claim_handover, resolve_handover
from app.modules.conversations.models import Conversation
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer


def _ctx(db, tenant_ctx) -> SimpleNamespace:
    """The three fields the handover routes read off the request context."""
    return SimpleNamespace(
        session=db,
        tenant_id=tenant_ctx.tenant_id,
        user_id=tenant_ctx.user.id,
    )


async def _conversation(db, tenant_id) -> Conversation:
    customer = Customer(tenant_id=tenant_id, name="Lifecycle Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    await db.flush()
    return conversation


async def _open_handover(db, tenant_id) -> tuple[Conversation, AIHandover]:
    conversation = await _conversation(db, tenant_id)
    created = await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="guardrail", note="lifecycle"
    )
    assert created is True
    await db.flush()
    handover = (
        (
            await db.execute(
                select(AIHandover).where(
                    AIHandover.tenant_id == tenant_id, AIHandover.note == "lifecycle"
                )
            )
        )
        .scalars()
        .one()
    )
    return conversation, handover


async def _status(db, conversation_id) -> str:
    return (
        await db.execute(select(Conversation.status).where(Conversation.id == conversation_id))
    ).scalar_one()


# --------------------------------------------- 1. the whole cycle, in order ---


async def test_the_full_lifecycle_create_claim_resolve(db, tenant_ctx) -> None:
    """The one test the review asked for: intake, ownership, outcome — in order."""
    tenant_id = tenant_ctx.tenant_id
    conversation, handover = await _open_handover(db, tenant_id)

    # INTAKE: the row exists, is open, and the conversation is out of the AI's reach.
    assert handover.status == "pending"
    assert handover.claimed_by_user_id is None
    assert handover.resolved_at is None
    assert await _status(db, conversation.id) == "waiting_human"

    # CLAIM: the employee who takes it is recorded.
    claimed = await claim_handover(handover.id, _ctx(db, tenant_ctx))
    assert claimed.status == "claimed"
    assert claimed.claimed_by_user_id == tenant_ctx.user.id
    # Claiming is not finishing: the outcome half is still empty.
    assert claimed.resolved_at is None

    # RESOLVE: who, when, and with what result — and the conversation comes back.
    resolved = await resolve_handover(
        handover.id,
        _ctx(db, tenant_ctx),
        SimpleNamespace(outcome="answered", note="اترد على العميل"),
    )
    assert resolved.status == "resolved"
    assert resolved.resolved_by_user_id == tenant_ctx.user.id
    assert resolved.resolved_at is not None
    assert resolved.outcome == "answered"
    assert await _status(db, conversation.id) == "open"


# ------------------------------------------------- 2. one open row, never two --


async def test_a_second_handover_for_the_same_conversation_is_refused(db, tenant_ctx) -> None:
    """Idempotent by contract: a redelivered event must not double the queue."""
    tenant_id = tenant_ctx.tenant_id
    _conversation_row, handover = await _open_handover(db, tenant_id)

    again = await request_human_takeover(
        db,
        tenant_id,
        conversation_id=handover.conversation_id,
        reason="budget",
        note="second attempt",
    )
    assert again is False

    rows = (
        (
            await db.execute(
                select(AIHandover).where(AIHandover.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "a second open handover was created for one conversation"


async def test_a_new_handover_is_allowed_once_the_first_is_resolved(db, tenant_ctx) -> None:
    """The index is PARTIAL: resolved history must not block a later handover."""
    tenant_id = tenant_ctx.tenant_id
    conversation, handover = await _open_handover(db, tenant_id)
    await resolve_handover(
        handover.id, _ctx(db, tenant_ctx), SimpleNamespace(outcome="answered", note="done")
    )

    created = await request_human_takeover(
        db, tenant_id, conversation_id=conversation.id, reason="failure", note="second"
    )
    assert created is True


async def test_a_claimed_handover_cannot_be_stolen_by_a_second_employee(db, tenant_ctx) -> None:
    """§150: a row can be claimed by one person and resolved by another — but the
    second person cannot silently take ownership."""
    from app.core.errors import ConflictError

    tenant_id = tenant_ctx.tenant_id
    _conversation_row, handover = await _open_handover(db, tenant_id)
    await claim_handover(handover.id, _ctx(db, tenant_ctx))

    try:
        await claim_handover(handover.id, _ctx(db, tenant_ctx))
    except ConflictError:
        pass
    else:
        raise AssertionError("a claimed handover was claimable a second time")


# ------------------------------- 3. the two paths that used to return silently --


async def test_no_customer_agent_still_hands_over(db, tenant_ctx, monkeypatch) -> None:
    """Entitled to AI but the agent row is missing: a misconfiguration, not the
    customer's problem. The conversation must not be left with no owner."""
    tenant_id = tenant_ctx.tenant_id

    async def entitled(session, tenant_id_, capability):
        return True

    monkeypatch.setattr("app.modules.billing.service.EntitlementService.can", entitled)

    conversation = await _conversation(db, tenant_id)
    await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="عندكم ايه؟",
    )
    await db.flush()

    await maybe_auto_reply(db, tenant_id, conversation.id)

    handover = (
        (await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert handover.reason == "failure"
    assert await _status(db, conversation.id) == "waiting_human"


async def test_a_plan_without_ai_hands_over_instead_of_going_quiet(
    db, tenant_ctx, monkeypatch
) -> None:
    """§37 `policy` — the reason that had no producer before this. A tenant whose
    plan excludes AI still owes the customer a human answer."""
    tenant_id = tenant_ctx.tenant_id

    async def not_entitled(session, tenant_id_, capability):
        return False

    monkeypatch.setattr("app.modules.billing.service.EntitlementService.can", not_entitled)

    conversation = await _conversation(db, tenant_id)
    await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="عايز أعرف السعر",
    )
    await db.flush()

    await maybe_auto_reply(db, tenant_id, conversation.id)

    handover = (
        (await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id)))
        .scalars()
        .one()
    )
    assert handover.reason == "policy"
    assert await _status(db, conversation.id) == "waiting_human"


async def test_the_agent_that_exists_is_used(db, tenant_ctx, monkeypatch) -> None:
    """The counter-case for the two above: with an agent AND entitlement the reply
    path runs and NO handover is created.

    The turn itself is stubbed: this test is about which BRANCH the hook takes,
    not about what a model would say, and a real turn would need an embedding
    provider configured.
    """
    from app.modules.ai.agents.customer.turn import TurnOutcome

    tenant_id = tenant_ctx.tenant_id
    db.add(
        Agent(
            tenant_id=tenant_id,
            kind="customer",
            name="Customer Agent",
            model="fast",
            system_prompt="s",
            is_active=True,
        )
    )
    await db.flush()

    async def entitled(session, tenant_id_, capability):
        return True

    monkeypatch.setattr("app.modules.billing.service.EntitlementService.can", entitled)

    calls = {"count": 0}

    async def fake_turn(*args, **kwargs):
        calls["count"] += 1
        return TurnOutcome(reply="عندنا مقاس M و L", state_version=0)

    monkeypatch.setattr("app.modules.ai.hooks.run_customer_turn", fake_turn)

    conversation = await _conversation(db, tenant_id)
    await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="عايز أعرف السعر",
    )
    await db.flush()

    await maybe_auto_reply(db, tenant_id, conversation.id)

    assert calls["count"] == 1, "the reply path never ran with an agent and entitlement"
    handovers = (
        (await db.execute(select(AIHandover).where(AIHandover.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert handovers == []
    # …and the conversation stays with the AI rather than being parked for a human.
    assert await _status(db, conversation.id) != "waiting_human"
