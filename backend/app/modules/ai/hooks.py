"""AI integration hooks for the message worker.

``maybe_auto_reply`` runs after a conversation ingest. It must never break
ingest SILENTLY: the auto-reply itself is allowed to fail loudly so the worker
runtime rolls the event back and retries (a swallowed error used to ack the
event with NO reply and NO retry — a silent customer-facing loss), while the
optional context lookups (knowledge, memories) degrade on purpose. The AI
answer is posted through ConversationService (application service, never raw
SQL) and the outbound event is staged via the outbox writer inside the same
transaction.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import Agent
from app.modules.ai.runtime import AgentRunner
from app.modules.conversations.policy import OutboundBlockedError

logger = logging.getLogger(__name__)

KNOWLEDGE_SNIPPETS = 3
HISTORY_MESSAGES = 10


async def maybe_auto_reply(
    session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    """AI reply to the last inbound message of a conversation.

    Runs under the caller's conversation lease (the message worker already
    holds it — advisory xact locks are reentrant within one transaction).

    Failure policy: exceptions propagate to the worker runtime, which rolls
    the ProcessedEvent marker back and retries with backoff. Swallowing here
    used to ack the event with NO reply and NO retry — a silent customer-
    facing loss. ConversationBusy propagates as retryable by contract.
    """
    from app.core.lease import conversation_lease

    async with conversation_lease(session, conversation_id):
        await _do_auto_reply(session, tenant_id, conversation_id)


async def _do_auto_reply(
    session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    """Inner auto-reply logic (called under the conversation lease)."""
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

    # §165: whether the plan includes AI is an entitlement, and it is checked
    # in ONE service rather than here. A tenant without it is not an error —
    # the conversation simply waits for a human, so we skip (never raise: a
    # raised error would retry and dead-letter the customer's message).
    from app.modules.billing.service import EntitlementService

    if not await EntitlementService.can(session, tenant_id, "CanUseAI"):
        logger.info(
            "auto-reply skipped: plan does not include AI conversation=%s",
            conversation_id,
        )
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
    # A6: never talk over a human. When the conversation is closed, paused or
    # waiting for the team, the next inbound must not re-trigger the agent.
    if conversation.status in ("closed", "paused", "waiting_human"):
        logger.info(
            "auto-reply skipped conversation=%s status=%s",
            conversation_id,
            conversation.status,
        )
        return
    customer_id: uuid.UUID | None = conversation.customer_id

    # Knowledge context is a bonus, never a hard dependency: if retrieval fails
    # the reply still goes out. That part is deliberate.
    #
    # But it must not fail QUIETLY. A misconfigured embedding model means RAG
    # contributes nothing to every reply from then on — answer quality drops and
    # nothing says so. WARNING (not INFO) so it is visible in normal log review,
    # and the message states what was actually lost rather than just "failed".
    system_prompt = agent.system_prompt or ""

    # §132: knowledge snippets are injected as a SEPARATE context block, not
    # appended to the system prompt. This separates trusted instructions from
    # untrusted retrieved content, reducing the prompt-injection surface.
    #
    # Knowledge context is a bonus, never a hard dependency: if retrieval fails
    # the reply still goes out. But it must not fail QUIETLY — a misconfigured
    # embedding model means RAG contributes nothing to every reply from then on.
    knowledge_context: str | None = None
    try:
        from app.modules.ai.knowledge import retrieve_relevant

        snippets = await retrieve_relevant(
            session,
            tenant_id,
            query=user_body,
            customer_id=customer_id,
            limit=KNOWLEDGE_SNIPPETS,
        )
        if snippets:
            knowledge_context = "\n".join(f"- {s}" for s in snippets)
    except Exception:  # noqa: BLE001 — context is optional, the reply is not
        logger.warning(
            "auto-reply continuing WITHOUT knowledge context — knowledge search "
            "failed (check the embedding model config)",
            exc_info=True,
        )

    result = await AgentRunner().run(
        session,
        tenant_id,
        agent_id=agent.id,
        conversation_id=conversation_id,
        user_message=user_body,
        customer_id=customer_id,
        system_prompt=system_prompt or None,
        knowledge_context=knowledge_context,  # §132: separate from system prompt
    )

    # §158: the memory for this run is persisted ONCE, inside AgentRunner
    # (same provenance rules, plus an explicit guardrail==allow check). The
    # duplicate write that used to live here produced two rows and two
    # embeddings per run.

    # §41: the guardrail is evaluated INSIDE AgentRunner, so every caller is
    # covered — this only reacts to the verdict. The runner already withheld
    # the content, so there is nothing sendable here either way.
    if result.guardrail_decision != "allow":
        from app.modules.ai.models import AIHandover

        session.add(
            AIHandover(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                run_id=None,
                reason="guardrail",
                status="pending",
                note=f"guardrail:{result.guardrail_reason}",
            )
        )
        logger.warning(
            "ai.guardrail_blocked conversation=%s reason=%s",
            conversation_id,
            result.guardrail_reason,
        )
        return

    if not result.content:
        return

    try:
        message = await ConversationService.add_message(
            session,
            tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            sender_type="ai",
            body=result.content,
        )
    except OutboundBlockedError as exc:
        # §30: outside the customer-service window a free-form AI reply is not
        # allowed on this channel. Hand over to a human (who can send an
        # approved template) instead of letting the event fail — the customer
        # still needs an answer, and a failed event would be retried forever.
        from app.modules.ai.models import AIHandover

        session.add(
            AIHandover(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                run_id=None,
                reason="messaging_window_closed",
                status="pending",
                note=f"policy:{exc.message}",
            )
        )
        logger.warning(
            "ai.reply_blocked_by_policy conversation=%s reason=%s",
            conversation_id,
            exc.message,
        )
        return
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
        # Messages are append-only and carry no VersionMixin column, so the
        # aggregate version is the constant 1 (created once, never mutated).
        aggregate_version=1,
    )

    if not result.media:
        return

    async def send_media() -> None:
        """§13: deliver the collected product photos after the text reply.

        One outbound message per image, ONE outbox event per message, and the
        state engine's sent_media ledger updated so no image is ever re-sent
        in this conversation. Only runs once the text went out — a photo
        without its sentence reads as spam.
        """
        from app.modules.ai.agents.customer.state import apply_patch, load_state

        state = await load_state(session, tenant_id, conversation_id)
        sent: list[str] = list(state.sent_media or []) if state else []
        newly_sent: list[str] = []
        for item in result.media:
            if item["image_id"] in sent:
                continue  # §13: the no-resend rule
            try:
                media_message = await ConversationService.add_message(
                    session,
                    tenant_id,
                    conversation_id=conversation_id,
                    direction="outbound",
                    sender_type="ai",
                    media_url=item["image_url"],
                    media_type="image",
                    content_type="image",
                )
            except OutboundBlockedError as exc:
                # The text went out; the window closed mid-delivery. Stop
                # sending photos rather than retrying into a closed window.
                logger.warning(
                    "ai.media_send_blocked conversation=%s reason=%s",
                    conversation_id,
                    exc.message,
                )
                break
            await add_outbox_event(
                session,
                aggregate_type="message",
                aggregate_id=media_message.id,
                event_type="message.outbound",
                tenant_id=tenant_id,
                payload={
                    "message_id": str(media_message.id),
                    "conversation_id": str(conversation_id),
                },
                aggregate_version=1,
            )
            sent.append(item["image_id"])
            newly_sent.append(item["image_id"])

        # The state engine owns the row: closed vocabulary, append-dedupe,
        # and a version bump ONLY when something actually grew.
        await apply_patch(
            session,
            tenant_id,
            conversation_id,
            {"shown_items": result.shown_product_ids, "sent_media": newly_sent},
        )

    await send_media()
