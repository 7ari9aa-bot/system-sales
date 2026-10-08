"""Approval lifecycle (spec §135) — a decided approval must END its parked run.

The defect these pin: `AgentRunner.run` always creates a NEW run, and the resume
finds the grant by conversation+action+arguments — never by run id. So a run in
WAITING_APPROVAL is unreachable once its approval is decided, yet nothing ever
moved it. It stayed "in flight" forever, and — worse — a customer who had been
told "we'll reply once it's approved" was never replied to at all when the
answer turned out to be no.

Most of these are database-backed (they need the run, approval and conversation
rows), so they skip without a database — CI runs them.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.modules.ai.approvals import ApprovalService
from app.modules.ai.models import Agent, AgentRun, AIHandover, ApprovalRequest
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.platform.models import OutboxEvent

AI_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "ai"


async def _parked(db, tenant_id, *, ttl_minutes: int = 60):
    """A run suspended on a HIGH-risk approval, exactly as the gate leaves it."""
    agent = Agent(tenant_id=tenant_id, name="Sales Agent", model="fast", system_prompt="s")
    customer = Customer(tenant_id=tenant_id, name="Approval Customer")
    db.add_all([agent, customer])
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    run = AgentRun(
        tenant_id=tenant_id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        status="WAITING_APPROVAL",
        input={"message": "اطلبهولي"},
        started_at=datetime.now(UTC),
        # The runner stamps this when the waiting message goes out, i.e. BEFORE
        # the decision — a parked run already has it.
        finished_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    approval = await ApprovalService.request(
        db,
        tenant_id,
        run_id=run.id,
        conversation_id=conversation.id,
        entity_type="tool",
        entity_id="create_order",
        action="create_order",
        payload={"arguments": {"quantity": 2}},
        ttl_minutes=ttl_minutes,
    )
    await db.flush()
    return run, approval, conversation


async def _handovers(db, tenant_id) -> list[AIHandover]:
    return list(
        (
            await db.execute(
                select(AIHandover).where(AIHandover.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )


async def test_a_rejected_approval_ends_the_parked_run(db, tenant_ctx):
    run, approval, _conversation = await _parked(db, tenant_ctx.tenant_id)

    await ApprovalService.decide(
        db,
        tenant_ctx.tenant_id,
        approval.id,
        decision="REJECTED",
        decided_by_user_id=tenant_ctx.user.id,
        rejection_reason="السعر غلط",
    )

    assert run.status == "cancelled", "the run stays in flight after a human said no"
    assert "rejected" in (run.error or "")
    assert "السعر غلط" in (run.error or "")


async def test_a_rejection_hands_the_customer_to_a_human(db, tenant_ctx):
    """The agent promised a reply. "No" is a reply, and it is a human's to give."""
    run, approval, conversation = await _parked(db, tenant_ctx.tenant_id)

    await ApprovalService.decide(
        db,
        tenant_ctx.tenant_id,
        approval.id,
        decision="REJECTED",
        decided_by_user_id=tenant_ctx.user.id,
    )

    handovers = await _handovers(db, tenant_ctx.tenant_id)
    assert len(handovers) == 1
    assert handovers[0].status == "pending"
    assert handovers[0].reason == "approval"
    assert handovers[0].run_id == run.id
    assert handovers[0].conversation_id == conversation.id

    refreshed = await ConversationService.get(db, tenant_ctx.tenant_id, conversation.id)
    assert refreshed.status == "waiting_human", "the next inbound would re-trigger the agent"

    events = (
        (
            await db.execute(
                select(OutboxEvent).where(OutboxEvent.tenant_id == tenant_ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert [e.payload["event_type"] for e in events] == ["ai.handover.created"]


async def test_an_approved_approval_also_ends_the_parked_run(db, tenant_ctx):
    """Approval does not resume this row either — the resume is a NEW run.

    Left in WAITING_APPROVAL it would look suspended forever, next to the
    resumed run that actually did the work.
    """
    run, approval, _conversation = await _parked(db, tenant_ctx.tenant_id)

    await ApprovalService.decide(
        db,
        tenant_ctx.tenant_id,
        approval.id,
        decision="APPROVED",
        decided_by_user_id=tenant_ctx.user.id,
    )

    assert run.status == "succeeded"
    assert run.error is None
    # The resume answers the customer, so nobody needs to take over.
    assert await _handovers(db, tenant_ctx.tenant_id) == []


async def test_a_cancelled_approval_ends_the_parked_run(db, tenant_ctx):
    run, approval, _conversation = await _parked(db, tenant_ctx.tenant_id)

    await ApprovalService.decide(
        db,
        tenant_ctx.tenant_id,
        approval.id,
        decision="CANCELLED",
        decided_by_user_id=tenant_ctx.user.id,
    )

    assert run.status == "cancelled"
    assert await _handovers(db, tenant_ctx.tenant_id) != []


async def test_a_refusal_does_not_reopen_a_closed_conversation(db, tenant_ctx):
    """Merchants close threads by hand all day and the TTL is an hour, so an
    approval outliving its conversation is the common case, not an exotic one.
    The run still ends; the finished thread must not reappear in the inbox."""
    run, approval, conversation = await _parked(db, tenant_ctx.tenant_id)
    await ConversationService.set_status(db, tenant_ctx.tenant_id, conversation.id, "closed")

    await ApprovalService.decide(
        db,
        tenant_ctx.tenant_id,
        approval.id,
        decision="REJECTED",
        decided_by_user_id=tenant_ctx.user.id,
    )

    assert run.status == "cancelled"
    assert await _handovers(db, tenant_ctx.tenant_id) == []
    refreshed = await ConversationService.get(db, tenant_ctx.tenant_id, conversation.id)
    assert refreshed.status == "closed"


async def test_a_late_decision_is_refused_and_left_for_the_sweep(db, tenant_ctx):
    """The reviewer clicked an hour late.

    The 400 aborts the request transaction, so nothing a refused `decide` writes
    reaches the database — the row is still PENDING afterwards. That is only safe
    because the TTL sweep expires it AND closes the run it parked; a sweep that
    did half of that would leave the customer waiting on a decision already made.
    """
    run, approval, _conversation = await _parked(db, tenant_ctx.tenant_id, ttl_minutes=-1)

    with pytest.raises(ValidationError, match="expired"):
        await ApprovalService.decide(
            db,
            tenant_ctx.tenant_id,
            approval.id,
            decision="APPROVED",
            decided_by_user_id=tenant_ctx.user.id,
        )

    assert run.status == "WAITING_APPROVAL", "a refused decision must not close the run"
    assert await ApprovalService.expire_stale(db, tenant_ctx.tenant_id) == 1
    assert run.status == "cancelled"


async def test_expire_stale_ends_the_runs_it_parked(db, tenant_ctx):
    """The TTL sweep is the COMMON path — nobody decides most approvals."""
    run, _approval, conversation = await _parked(db, tenant_ctx.tenant_id, ttl_minutes=-1)

    assert await ApprovalService.expire_stale(db, tenant_ctx.tenant_id) == 1

    assert run.status == "cancelled"
    assert "expired" in (run.error or "")
    handovers = await _handovers(db, tenant_ctx.tenant_id)
    assert len(handovers) == 1
    assert handovers[0].run_id == run.id
    refreshed = await ConversationService.get(db, tenant_ctx.tenant_id, conversation.id)
    assert refreshed.status == "waiting_human"


async def test_expire_stale_ignores_approvals_still_in_their_ttl(db, tenant_ctx):
    run, _approval, _conversation = await _parked(db, tenant_ctx.tenant_id)

    assert await ApprovalService.expire_stale(db, tenant_ctx.tenant_id) == 0
    assert run.status == "WAITING_APPROVAL"
    assert await _handovers(db, tenant_ctx.tenant_id) == []


async def test_expire_stale_is_bounded_per_call(db, tenant_ctx):
    """Each expiry now writes a handover too, so an unbounded sweep after an
    outage would be one enormous transaction. The next tick takes the rest."""
    for _ in range(3):
        await _parked(db, tenant_ctx.tenant_id, ttl_minutes=-1)

    assert await ApprovalService.expire_stale(db, tenant_ctx.tenant_id, limit=2) == 2
    assert len(await _handovers(db, tenant_ctx.tenant_id)) == 2

    remaining = (
        await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.tenant_id == tenant_ctx.tenant_id,
                ApprovalRequest.status == "PENDING",
            )
        )
    ).scalars().all()
    assert len(remaining) == 1

    assert await ApprovalService.expire_stale(db, tenant_ctx.tenant_id) == 1
    assert await _handovers(db, tenant_ctx.tenant_id) != []


async def test_an_approval_with_no_run_or_conversation_still_expires(db, tenant_ctx):
    """Approvals created outside a conversation (an automation, the API) have
    nothing to park and nobody to hand over — the sweep must not choke on them."""
    approval = await ApprovalService.request(
        db,
        tenant_ctx.tenant_id,
        run_id=None,
        conversation_id=None,
        entity_type="order",
        entity_id="42",
        action="create_order",
        payload={"total": 100},
        ttl_minutes=-1,
    )
    await db.flush()

    assert await ApprovalService.expire_stale(db, tenant_ctx.tenant_id) == 1
    assert approval.status == "EXPIRED"
    assert await _handovers(db, tenant_ctx.tenant_id) == []


def test_the_handover_write_has_one_implementation():
    """Queue row + conversation status + outbox event: three writes every
    withhold path owes. Four copies of them is how one path forgets one."""
    assert (AI_DIR / "handover.py").is_file(), "the shared handover write is gone"
    for name in ("hooks.py", "runtime.py", "approvals.py"):
        source = (AI_DIR / name).read_text(encoding="utf-8")
        assert "AIHandover(" not in source, f"{name} builds a handover by hand again"
