"""AI → human handover (spec §37/§150) — the one shape every withhold path owes.

A run that cannot answer the customer must not leave the conversation in AI
limbo. Every path that withholds a reply — a guardrail verdict, a closed
messaging window, a spent budget, a run limit, an approval a human refused, a
missing agent, a plan without AI — owes the same three writes:

1. the ``ai_handovers`` row a human works from,
2. the conversation status that stops the NEXT inbound from re-triggering the
   agent on a conversation nobody is answering,
3. the outbox event the dashboard and the SLA clocks hear about.

One implementation, so a fourth path cannot forget one of the three.

The write is IDEMPOTENT: one conversation never holds two open handovers. A
redelivered event, a second message before a human claims the first, or two
withhold paths firing in one turn all converge on the same row. The database
enforces the same rule (partial unique index ``uq_handovers_open_conversation``),
so the guarantee does not rest on this check alone — a concurrent pair is
refused by Postgres, not by a race in the application.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Statuses that mean "a human still owes this conversation an answer".
OPEN_HANDOVER_STATUSES = ("pending", "claimed")


async def request_human_takeover(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    conversation_id: uuid.UUID,
    reason: str,
    note: str | None = None,
    run_id: uuid.UUID | None = None,
) -> bool:
    """Record the handover. True only when this call created it.

    False means there was nothing to add: the conversation is already closed, or
    an open handover already exists for it (idempotent — the caller should not
    treat that as a failure, and no second outbox event or bell is emitted).
    """
    from app.core.events.writer import add_outbox_event
    from app.modules.ai.models import AIHandover
    from app.modules.conversations.service import ConversationService

    conversation = await ConversationService.get(session, tenant_id, conversation_id)
    if conversation.status == "closed":
        # A human already ended this conversation. Moving it to `waiting_human`
        # would put a finished thread back in the inbox and, on channels that
        # notify on status, ping a customer whose question was answered days
        # ago. The run still ends; nobody is asked to pick it up.
        #
        # This is the common case for an approval, not an exotic one: the TTL is
        # an hour and conversations are closed by hand all day.
        return False

    open_handover = (
        await session.execute(
            select(AIHandover.id)
            .where(
                AIHandover.tenant_id == tenant_id,
                AIHandover.conversation_id == conversation_id,
                AIHandover.status.in_(OPEN_HANDOVER_STATUSES),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_handover is not None:
        # Someone is already on it. A second row would double the queue entry,
        # emit a second `ai.handover.created`, and ring a second bell for one
        # problem. The partial unique index refuses the row at COMMIT anyway;
        # bailing here keeps the whole transaction from failing instead.
        return False

    session.add(
        AIHandover(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            run_id=run_id,
            reason=reason,
            status="pending",
            note=note,
        )
    )
    await ConversationService.set_status(session, tenant_id, conversation_id, "waiting_human")
    await add_outbox_event(
        session,
        aggregate_type="ai",
        aggregate_id=conversation_id,
        event_type="ai.handover.created",
        tenant_id=tenant_id,
        payload={
            "event_type": "ai.handover.created",
            "conversation_id": str(conversation_id),
            "run_id": str(run_id) if run_id else None,
            "reason": reason,
            "note": note,
        },
    )

    # The outbox event reaches the dashboard's SSE stream, but a stream only
    # helps whoever is already watching the page. The persistent notification
    # is what makes the handover visible later — the same transaction, so the
    # row, the status and the bell badge commit (or roll back) together.
    #
    # Owner lookup via SQL rather than `identity.models`: `identity` already
    # imports `ai`, and a model import here would close a NEW cycle that
    # tests/test_module_boundaries.py fails on — the same shape gateway.py's
    # budget alerts use.
    from app.modules.notifications.service import NotificationService

    owner_ids = (
        (
            await session.execute(
                text(
                    "SELECT tu.user_id FROM tenant_users tu "
                    "JOIN roles r ON r.id = tu.role_id "
                    "WHERE tu.tenant_id = :tenant_id AND r.code = 'owner'"
                ),
                {"tenant_id": str(tenant_id)},
            )
        )
        .scalars()
        .all()
    )
    for owner_id in owner_ids:
        await NotificationService.create(
            session,
            tenant_id,
            owner_id,
            kind="ai_handover",
            title="Human handover needed",
            body=(
                f"The AI handed conversation {conversation_id} to the team "
                f"(reason: {reason}). It is waiting for a human reply."
            ),
            payload={
                "conversation_id": str(conversation_id),
                "run_id": str(run_id) if run_id else None,
                "reason": reason,
                "note": note,
            },
            # One bell per conversation+reason: the withhold paths can fire
            # back-to-back on the same stuck conversation, and five identical
            # notifications hide the one that matters.
            dedup_key=f"ai_handover:{conversation_id}:{reason}",
        )
    return True
