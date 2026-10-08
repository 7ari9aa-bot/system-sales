"""AI → human handover (spec §37/§150) — the one shape every withhold path owes.

A run that cannot answer the customer must not leave the conversation in AI
limbo. Every path that withholds a reply — a guardrail verdict, a closed
messaging window, a spent budget, a run limit, an approval a human refused —
owes the same three writes:

1. the ``ai_handovers`` row a human works from,
2. the conversation status that stops the NEXT inbound from re-triggering the
   agent on a conversation nobody is answering,
3. the outbox event the dashboard and the SLA clocks hear about.

One implementation, so a fourth path cannot forget one of the three.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def request_human_takeover(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    conversation_id: uuid.UUID,
    reason: str,
    note: str | None = None,
    run_id: uuid.UUID | None = None,
) -> bool:
    """Record the handover. False when there was nothing to hand over, i.e. the
    conversation is already closed."""
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
    return True
