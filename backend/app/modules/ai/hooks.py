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

from app.core.storage import get_storage
from app.modules.ai.agents.customer.turn import TurnInput, run_customer_turn
from app.modules.ai.gateway import AIBudgetExhaustedError
from app.modules.conversations.policy import OutboundBlockedError

logger = logging.getLogger(__name__)

KNOWLEDGE_SNIPPETS = 3
HISTORY_MESSAGES = 10


async def maybe_auto_reply(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    inbound_message_id: uuid.UUID | None = None,
) -> None:
    """AI reply to a conversation's inbound message.

    `inbound_message_id` is the message the delivered event actually carried, and
    it is what gets answered. Without it the reply targets the newest inbound
    message — see `_do_auto_reply` for why that is only a fallback.

    Runs under the caller's conversation lease (the message worker already
    holds it — advisory xact locks are reentrant within one transaction).

    Failure policy: exceptions propagate to the worker runtime, which rolls
    the ProcessedEvent marker back and retries with backoff. Swallowing here
    used to ack the event with NO reply and NO retry — a silent customer-
    facing loss. ConversationBusy propagates as retryable by contract.
    """
    from app.core.lease import conversation_lease

    async with conversation_lease(session, conversation_id):
        await _do_auto_reply(
            session, tenant_id, conversation_id, inbound_message_id=inbound_message_id
        )


async def _do_auto_reply(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    inbound_message_id: uuid.UUID | None = None,
) -> None:
    """Inner auto-reply logic (called under the conversation lease)."""
    # Lazy imports: conversations owns messages; AI is an optional layer.
    from app.core.events.writer import add_outbox_event
    from app.modules.ai.core.resolver import resolve_agent_by_kind_optional
    from app.modules.ai.handover import request_human_takeover
    from app.modules.conversations.service import ConversationService

    async def handover(reason: str, note: str, run_id: uuid.UUID | None) -> None:
        await request_human_takeover(
            session,
            tenant_id,
            conversation_id=conversation_id,
            reason=reason,
            note=note,
            run_id=run_id,
        )

    agent = await resolve_agent_by_kind_optional(session, tenant_id, "customer")
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

    # Answer the message the event carried — not "whatever is newest by the time
    # the worker gets here". With A and B queued and A's delivery delayed, the old
    # behaviour answered B twice (once per event) and never answered A: the
    # customer who wrote first got silence, and the other got a duplicate.
    last_inbound = None
    if inbound_message_id is not None:
        named = await ConversationService.find_message(session, tenant_id, inbound_message_id)
        # Scoped here, not in the service: an id from another conversation or an
        # outbound row is not this turn. That includes the resume event's legacy
        # shape, whose aggregate_id was an APPROVAL id — it resolves to nothing
        # and falls through, instead of answering a message that does not exist.
        if named is not None and named.conversation_id == conversation_id:
            if named.direction == "inbound":
                last_inbound = named
            else:
                logger.info(
                    "auto-reply skipped conversation=%s message=%s is outbound",
                    conversation_id,
                    inbound_message_id,
                )
                return

    if last_inbound is None:
        # No usable id: an approval resume (re-evaluate the current context), or
        # an event staged before the id was carried.
        history = await ConversationService.list_messages(
            session, tenant_id, conversation_id, limit=HISTORY_MESSAGES
        )
        last_inbound = next(
            (
                m
                for m in reversed(history)
                if m.direction == "inbound"
                and (m.body or m.media_url or m.content_type in ("image", "voice", "file"))
            ),
            None,
        )
    if last_inbound is None:
        return

    # §8: intake belongs to the turn coordinator, not to six inline ways of
    # asking "did the customer send a photo?". Fetch the attachments once and
    # hand the coordinator the raw shape (§155 kinds + (mime, key) pairs).
    from app.modules.conversations.models import Attachment

    att_rows = (
        (
            await session.execute(
                select(Attachment).where(
                    Attachment.tenant_id == tenant_id,
                    Attachment.message_id == last_inbound.id,
                )
            )
        )
        .scalars()
        .all()
    )
    attachments: list[tuple[str, str | None]] = []
    # §9: the agent accepts no tenant credentials — the URL mapping is minted
    # HERE, outside the turn, from the durable storage keys.
    image_urls: dict[str, str] = {}
    transcript: str | None = None
    has_image = (last_inbound.content_type == "image") or bool(
        last_inbound.media_type and "image" in last_inbound.media_type
    )
    has_voice = (last_inbound.content_type == "voice") or bool(
        last_inbound.media_type and "audio" in last_inbound.media_type
    )
    for att in att_rows:
        mime = att.mime_type or ""
        if att.storage_key:
            attachments.append((mime, att.storage_key))
            if mime.startswith("image/"):
                has_image = True
                image_urls[att.storage_key] = get_storage().public_url(att.storage_key)
            elif mime.startswith("audio/"):
                has_voice = True
        if att.transcription_status == "completed" and att.transcript_text:
            transcript = att.transcript_text.strip() or None

    body = last_inbound.body.strip() if last_inbound.body and last_inbound.body.strip() else None
    # A placeholder survives only where the coordinator has no vocabulary: an
    # image whose bytes were never captured durably has no key to mint a URL
    # from, so build_turn would see nothing at all — say so in words instead.
    # Voice stays unplaceholdered: the coordinator surfaces an untranscribed
    # note as state ("we could not hear them yet"), never hides it.
    if body is None and has_image and not image_urls:
        body = "[Customer sent an image]"
    elif (
        body is None
        and not has_image
        and not has_voice
        and not attachments
        and last_inbound.media_url
    ):
        body = f"[Customer sent an attachment: {last_inbound.content_type}]"
    if body is None and not has_image and not has_voice and not attachments:
        return

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
    #
    # §132: knowledge snippets are injected as a SEPARATE context block, not
    # appended to the system prompt — trusted instructions stay away from
    # untrusted retrieved content. The system prompt itself is no longer passed
    # from here: the runtime resolves it from the agent row.
    knowledge_context: str | None = None
    retrieval_query = body or transcript or ""
    if retrieval_query:
        try:
            from app.modules.ai.knowledge import retrieve_relevant

            snippets = await retrieve_relevant(
                session,
                tenant_id,
                query=retrieval_query,
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

    # The no-resend ledger must be read BEFORE the turn: the coordinator
    # records the run's proposed media into sent_media, so reading the row
    # AFTER would filter out exactly what this turn proposed to deliver.
    from app.modules.ai.agents.customer.state import load_state

    pre_turn_state = await load_state(session, tenant_id, conversation_id)
    pre_turn_sent: set[str] = set(pre_turn_state.sent_media or []) if pre_turn_state else set()

    try:
        outcome = await run_customer_turn(
            session,
            TurnInput(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                agent_id=agent.id,
                inbound_message_id=last_inbound.id,
                customer_id=customer_id,
                body=body,
                content_type=last_inbound.content_type,
                attachments=attachments,
                transcript=transcript,
                image_urls=image_urls,
                knowledge_context=knowledge_context,  # §132: separate from system prompt
            ),
        )
    except AIBudgetExhaustedError as exc:
        # A spent ceiling is not a retryable failure, and letting it reach the
        # worker made it one: the message dead-lettered and the customer got
        # silence with nobody told. Hand it to a human instead — the note says
        # WHICH ceiling (monthly / daily / fairness) so the merchant can act.
        await handover("budget", f"budget:{exc.message}", None)
        logger.warning(
            "ai.budget_exhausted_handover conversation=%s reason=%s",
            conversation_id,
            exc.message,
        )
        return

    # §158: the memory for this run is persisted ONCE, inside AgentRunner
    # (same provenance rules, plus an explicit guardrail==allow check). The
    # duplicate write that used to live here produced two rows and two
    # embeddings per run.

    # §41/§12: the guardrail is evaluated inside the runner, and grounding
    # inside the coordinator — both withhold the reply. Nothing sendable
    # remains either way, so the hook only reacts: a guardrail verdict is a
    # guardrail handover, anything else (a grounding failure) hands the run to
    # a human rather than regenerating — v1 never spends a second model call
    # on a reply the deterministic check may bounce again.
    if outcome.blocked_reason == "empty_turn":
        return
    if outcome.blocked_reason is not None:
        if outcome.blocked_reason.startswith("guardrail:"):
            await handover("guardrail", outcome.blocked_reason, outcome.run_id)
        else:
            await handover("failure", outcome.blocked_reason, outcome.run_id)
        logger.warning(
            "ai.turn_blocked conversation=%s reason=%s",
            conversation_id,
            outcome.blocked_reason,
        )
        return

    if not outcome.reply:
        return

    try:
        message = await ConversationService.add_message(
            session,
            tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            sender_type="ai",
            body=outcome.reply,
        )
    except OutboundBlockedError as exc:
        # §30: outside the customer-service window a free-form AI reply is not
        # allowed on this channel. Hand over to a human (who can send an
        # approved template) instead of letting the event fail — the customer
        # still needs an answer, and a failed event would be retried forever.
        await handover("messaging_window_closed", f"policy:{exc.message}", outcome.run_id)
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

    if outcome.handover_reason is not None:
        # §37/P1-11: the customer asked for a person and the ack went out —
        # now the conversation actually moves. This is the writer that gives
        # the `customer_request` reason a producer: before it, a customer
        # saying "اتكلم مع حد" was answered by the model and nothing else
        # ever learned they had asked.
        await handover(outcome.handover_reason, "customer asked for a human", outcome.run_id)
        logger.info(
            "ai.customer_request_handover conversation=%s run=%s",
            conversation_id,
            outcome.run_id,
        )
        return

    if not outcome.media:
        return

    async def send_media() -> None:
        """§13: deliver the collected product photos after the text reply.

        One outbound message per image, ONE outbox event per message. The
        no-resend rule filters against the PRE-TURN sent_media snapshot: the
        coordinator already recorded the run's proposed media on the state
        row, so a fresh read here would hide exactly this turn's photos. The
        state row itself needs no second patch — the coordinator owns it.
        """
        sent = set(pre_turn_sent)
        for item in outcome.media:
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
            sent.add(item["image_id"])

    await send_media()
