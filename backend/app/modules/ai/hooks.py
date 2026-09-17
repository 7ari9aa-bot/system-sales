"""AI integration hooks for the message worker.

``maybe_auto_reply`` is called after a conversation ingest; it must NEVER
break the ingest path, so the whole body is wrapped in a catch-all that only
logs. The AI answer is posted through ConversationService (application
service, never raw SQL) and the outbound event is staged via the outbox
writer inside the same transaction.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.knowledge import search_knowledge
from app.modules.ai.models import Agent
from app.modules.ai.runtime import AgentRunner

logger = logging.getLogger(__name__)

KNOWLEDGE_SNIPPETS = 3
HISTORY_MESSAGES = 10


async def maybe_auto_reply(
    session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    """Best-effort AI reply to the last inbound message of a conversation.

    No active agent, no inbound message, or any error -> silently return
    (logged); ingest must never fail because of the AI layer.
    """
    try:
        # Lazy imports: conversations owns messages; AI is an optional layer.
        from app.core.events.writer import add_outbox_event
        from app.modules.conversations.service import ConversationService

        agent = (
            await session.execute(
                select(Agent)
                .where(Agent.tenant_id == tenant_id, Agent.is_active.is_(True))
                .order_by(Agent.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if agent is None:
            return

        history = await ConversationService.list_messages(
            session, tenant_id, conversation_id, limit=HISTORY_MESSAGES
        )
        last_inbound = next(
            (m for m in reversed(history) if m.direction == "inbound" and m.body), None
        )
        if last_inbound is None or not last_inbound.body:
            return
        user_body = last_inbound.body

        conversation = await ConversationService.get(session, tenant_id, conversation_id)
        customer_id: uuid.UUID | None = conversation.customer_id

        # Knowledge context is a bonus, never a hard dependency.
        system_prompt = agent.system_prompt or ""
        try:
            hits = await search_knowledge(session, tenant_id, user_body, limit=KNOWLEDGE_SNIPPETS)
            snippets = "\n".join(f"- {item.title}: {item.content}" for item, _distance in hits)
            if snippets:
                system_prompt = f"{system_prompt}\n\nKnowledge base context:\n{snippets}".strip()
        except Exception:  # noqa: BLE001 — context is optional
            logger.info("auto-reply knowledge search failed", exc_info=True)

        result = await AgentRunner().run(
            session,
            tenant_id,
            agent_id=agent.id,
            conversation_id=conversation_id,
            user_message=user_body,
            customer_id=customer_id,
            system_prompt=system_prompt or None,
        )
        if not result.content:
            return

        message = await ConversationService.add_message(
            session,
            tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            sender_type="ai",
            body=result.content,
        )
        await add_outbox_event(
            session,
            aggregate_type="message",
            aggregate_id=message.id,
            event_type="message.outbound",
            tenant_id=tenant_id,
            payload={
                "message_id": str(message.id),
                "conversation_id": str(conversation_id),
            },
        )
    except Exception:  # noqa: BLE001 — auto-reply must never break ingest
        logger.exception("auto-reply failed for conversation %s", conversation_id)
