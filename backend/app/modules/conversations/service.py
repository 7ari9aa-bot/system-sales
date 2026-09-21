"""CONVERSATIONS service — the conversation/message core.

Durable ingest rule: the message row is written FIRST; the outbox/stream entry
is a trigger. Duplicate channel_message_id → return the existing row (idempotent
ingest at the service level as well as the DB unique constraint).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.consent import MARKETING_PURPOSE, evaluate_outbound_consent
from app.core.errors import NotFoundError, ValidationError
from app.core.guardrails import AI_SENDER_TYPES, default_guardrail
from app.modules.conversations.media import MediaService, MediaStorage
from app.modules.conversations.models import (
    CONVERSATION_STATUSES,
    Assignment,
    Conversation,
    Message,
    normalize_conversation_status,
)
from app.modules.conversations.policy import MessagingPolicyService, OutboundBlockedError


class ConversationService:
    @staticmethod
    async def get_or_create(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        customer_id: uuid.UUID,
        channel: str,
    ) -> Conversation:
        conversation = (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.customer_id == customer_id,
                    Conversation.channel == channel,
                    Conversation.status != "closed",
                )
                .order_by(Conversation.last_message_at.desc().nullslast())
                .limit(1)
            )
        ).scalar_one_or_none()
        if conversation is None:
            conversation = Conversation(
                tenant_id=tenant_id, customer_id=customer_id, channel=channel
            )
            session.add(conversation)
            await session.flush()
        return conversation

    @staticmethod
    async def get(
        session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = (
            await session.execute(
                select(Conversation).where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.id == conversation_id,
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise NotFoundError("conversation not found")
        return conversation

    @staticmethod
    async def add_message(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        conversation_id: uuid.UUID,
        direction: str,
        sender_type: str,
        body: str | None = None,
        media_url: str | None = None,
        media_type: str | None = None,
        channel_message_id: str | None = None,
        sender_user_id: uuid.UUID | None = None,
        payload: dict | None = None,
        content_type: str = "text",
        reply_to_message_id: uuid.UUID | None = None,
        provider_metadata: dict | None = None,
        template_name: str | None = None,
        template_vars: dict | None = None,
        media_storage: MediaStorage | None = None,
    ) -> Message:
        conversation = await ConversationService.get(session, tenant_id, conversation_id)
        if not body and not media_url and not template_name:
            raise ValidationError("message needs body, media or a template")

        # §173: AI-authored content is checked HERE, at the boundary that
        # actually inserts an outbound message — not only inside AgentRunner.
        #
        # The runner evaluates the FULL chain (it has the run's tool results for
        # the factual constraint). This boundary applies the content-only checks
        # (validity, PII leakage, injection echo), which is what can be judged
        # without a run. Without this, any future producer that is not the runner
        # — a send tool, an AI campaign, a journey step — would bypass the
        # guardrail entirely simply by inserting a message directly.
        if direction == "outbound" and sender_type in AI_SENDER_TYPES and body:
            verdict = default_guardrail().evaluate(body, {})
            if verdict.decision != "allow":
                raise OutboundBlockedError(
                    f"AI output blocked by guardrail: {verdict.reason}",
                    details={
                        "conversation_id": str(conversation_id),
                        "guardrail_decision": verdict.decision,
                        "guardrail_reason": verdict.reason,
                        "guardrail_checks": verdict.checks,
                    },
                )

        # §30-31: EVERY outbound producer (human composer, AI auto-reply,
        # automation, journeys, campaigns) funnels through here, so this is the
        # only place the channel policy has to be enforced. Outside the
        # customer-service window an approved template is mandatory — without
        # this the provider silently rejects the send and the agent believes
        # the customer was answered.
        decision = None
        if direction == "outbound":
            decision = await MessagingPolicyService.evaluate_for_conversation(
                session, tenant_id, conversation, template_name=template_name
            )
            if not decision.allowed:
                raise OutboundBlockedError(
                    decision.reason,
                    details={
                        "conversation_id": str(conversation_id),
                        "channel": conversation.channel,
                        "requires_template": decision.requires_template,
                        "window_expires_at": (
                            decision.window_expires_at.isoformat()
                            if decision.window_expires_at
                            else None
                        ),
                    },
                )

        # §32: consent is per (customer, channel, purpose) and append-only, but
        # this generic path is TRANSACTIONAL by construction — it has no purpose
        # argument, so it cannot express marketing and there is nothing for a
        # caller to forget. Promotional sends go through
        # `add_promotional_message`, the single door that always runs the gate.
        # (A model that cannot tell a promotion from a shipping notice cannot be
        # made safe by a *default*; it is made safe by having one door.)

        if channel_message_id is not None:
            existing = (
                await session.execute(
                    select(Message).where(
                        Message.tenant_id == tenant_id,
                        Message.channel_message_id == channel_message_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing  # idempotent ingest

        message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction=direction,
            sender_type=sender_type,
            sender_user_id=sender_user_id,
            body=body,
            media_url=media_url,
            media_type=media_type,
            channel_message_id=channel_message_id,
            payload=payload or {},
            # §155 canonical columns.
            content_type=content_type,
            reply_to_message_id=reply_to_message_id,
            provider_metadata=provider_metadata or {},
            template_name=template_name,
            template_vars=template_vars or {},
            status="received" if direction == "inbound" else "queued",
        )
        session.add(message)
        now = datetime.now(UTC)
        conversation.last_message_at = now
        if direction == "inbound":
            # §30: the window anchor. Only INBOUND moves it — last_message_at
            # also moves on outbound and would keep the window open forever.
            conversation.last_customer_message_at = now
            conversation.unread_count += 1
        elif decision is not None:
            # Record the standing so the UI and the policy engine agree.
            conversation.messaging_policy_state = (
                "template_only" if decision.requires_template else "open"
            )
        # §46: an agent or AI reply satisfies the first-response SLA. A no-op
        # when no SLA is running, and only for real replies — a system message
        # must not stop the clock.
        if direction == "outbound" and sender_type in ("agent", "ai"):
            from app.modules.operations.sla import SlaService

            await SlaService.mark_met(session, tenant_id, conversation_id=conversation_id)
        await session.flush()
        # §33-34: capture inbound media to durable storage NOW, while the
        # provider URL is still valid (they expire within hours). Placed after
        # the flush so message.id exists, and after the channel_message_id
        # dedupe above so a re-delivered webhook never re-fetches.
        #
        # Synchronous on purpose: this is the single choke point every inbound
        # message passes through, so a producer cannot forget to capture media.
        # Outbound media is ours already and is skipped.
        if direction == "inbound" and media_url:
            await MediaService.ingest_inbound_media(
                session,
                tenant_id,
                message=message,
                media_url=media_url,
                declared_media_type=media_type,
                storage=media_storage,
            )
        return message

    @staticmethod
    async def add_promotional_message(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        conversation_id: uuid.UUID,
        sender_type: str = "system",
        body: str | None = None,
        media_url: str | None = None,
        media_type: str | None = None,
        sender_user_id: uuid.UUID | None = None,
        payload: dict | None = None,
        content_type: str = "text",
        template_name: str | None = None,
        template_vars: dict | None = None,
    ) -> Message:
        """Send a PROMOTIONAL message — the one §32 consent-checked door.

        `purpose` is deliberately NOT a parameter: the purpose of this method is
        marketing, so there is no flag for a caller to omit and no way to reach
        the send without the consent gate. A campaign, journey or broadcast that
        wants to reach customers uses this method; a transactional reply uses
        `add_message`.

        The gate runs BEFORE anything is written, so an opted-out customer is
        never left with a queued or half-sent message.
        """
        conversation = await ConversationService.get(session, tenant_id, conversation_id)
        consent = await evaluate_outbound_consent(
            session,
            tenant_id,
            customer_id=conversation.customer_id,
            channel=conversation.channel,
            purpose=MARKETING_PURPOSE,
        )
        if not consent.allowed:
            raise OutboundBlockedError(
                consent.reason,
                details={
                    "conversation_id": str(conversation_id),
                    "customer_id": str(conversation.customer_id),
                    "channel": consent.channel,
                    "purpose": consent.purpose,
                },
            )
        # §30-31 channel policy, §173 guardrail and the durable insert all still
        # apply — this door only adds the §32 check in front of them.
        return await ConversationService.add_message(
            session,
            tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            sender_type=sender_type,
            body=body,
            media_url=media_url,
            media_type=media_type,
            sender_user_id=sender_user_id,
            payload=payload,
            content_type=content_type,
            template_name=template_name,
            template_vars=template_vars,
        )

    @staticmethod
    async def set_status(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        status: str,
    ) -> Conversation:
        """Move a conversation through the §156 lifecycle states.

        open | waiting_customer | waiting_human | waiting_ai | paused | closed
        Legacy "pending" is accepted and normalized to "open"; anything else
        outside the lifecycle is rejected.
        """
        normalized = normalize_conversation_status(status)
        if normalized not in CONVERSATION_STATUSES:
            raise ValidationError(
                f"status must be one of {sorted(CONVERSATION_STATUSES)}, got {status!r}"
            )
        conversation = await ConversationService.get(session, tenant_id, conversation_id)
        conversation.status = normalized
        await session.flush()
        return conversation

    @staticmethod
    async def assign(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        assigned_to_user_id: uuid.UUID | None,
        assigned_by_user_id: uuid.UUID,
    ) -> Assignment:
        conversation = await ConversationService.get(session, tenant_id, conversation_id)
        conversation.assignee_user_id = assigned_to_user_id
        assignment = Assignment(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            assigned_to_user_id=assigned_to_user_id,
            assigned_by_user_id=assigned_by_user_id,
        )
        session.add(assignment)
        await session.flush()
        return assignment

    @staticmethod
    async def close(
        session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await ConversationService.get(session, tenant_id, conversation_id)
        conversation.status = "closed"
        conversation.unread_count = 0
        return conversation

    @staticmethod
    async def list_inbox(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        assignee_user_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
        before_created_at: datetime | None = None,
        before_id: uuid.UUID | None = None,
    ) -> list[Conversation]:
        """Keyset-aware inbox listing: pass before_created_at + before_id to page.

        §8: customer name/phone fetched via CustomerService (no cross-module
        model import).
        """
        from app.modules.customers.service import CustomerService
        from app.modules.platform.service import AuditService

        stmt = select(Conversation).where(Conversation.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(Conversation.status == status)
        if assignee_user_id:
            stmt = stmt.where(Conversation.assignee_user_id == assignee_user_id)
        if customer_id is not None:
            stmt = stmt.where(Conversation.customer_id == customer_id)
        if before_created_at is not None and before_id is not None:
            stmt = stmt.where(
                tuple_(Conversation.created_at, Conversation.id)
                < tuple_(before_created_at, before_id)
            )
            stmt = stmt.order_by(Conversation.created_at.desc(), Conversation.id.desc())
        else:
            stmt = stmt.order_by(Conversation.last_message_at.desc().nullslast())
        stmt = stmt.limit(limit).offset(offset)
        conversations = list((await session.execute(stmt)).scalars().all())
        if not conversations:
            return []

        # Batch-fetch customer names via the public contract (§8).
        customer_ids = [c.customer_id for c in conversations if c.customer_id]
        name_phone_map = await CustomerService.get_name_phone_map(
            session, tenant_id, customer_ids
        )
        for conv in conversations:
            entry = name_phone_map.get(conv.customer_id) if conv.customer_id else None
            conv.customer_name = entry[0] if entry else None
            conv.customer_phone = entry[1] if entry else None
            results.append(conv)
        return results

    # ------------------------------------------------------------------
    # §137 — InboxQuery: a dedicated read model for the inbox list.
    # ------------------------------------------------------------------
    # The raw list_inbox returns Conversation rows. The inbox UI needs MORE:
    # the last message preview, the unread count per conversation, and the
    # SLA status. Computing these per-row in the UI is N+1; computing them
    # in a single SQL query is the §137 read model.
    #
    # This is a READ-ONLY query — it never writes. It is the CQRS read side.

    @staticmethod
    async def inbox_query(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        assignee_user_id: uuid.UUID | None = None,
        limit: int = 50,
        before_created_at: datetime | None = None,
        before_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """§137: inbox list with preview + unread count + SLA in one query."""
        from sqlalchemy import func, text

        # Single SQL query that joins conversations → customers → last message
        # → unread count → SLA status. Using raw SQL because the subqueries
        # for "last message" and "unread count" are cleaner in SQL than ORM.
        params: dict[str, object] = {"tenant_id": str(tenant_id)}
        where_clauses = ["c.tenant_id = :tenant_id"]
        if status:
            params["status"] = status
            where_clauses.append("c.status = :status")
        if assignee_user_id:
            params["assignee_user_id"] = str(assignee_user_id)
            where_clauses.append("c.assignee_user_id = :assignee_user_id")
        if before_created_at and before_id:
            params["before_created_at"] = before_created_at
            params["before_id"] = before_id
            where_clauses.append(
                "(c.created_at, c.id) < (:before_created_at, :before_id)"
            )

        order_by = (
            "c.created_at DESC, c.id DESC"
            if before_created_at
            else "c.last_message_at DESC NULLS LAST"
        )

        sql = text(f"""
            SELECT
                c.id,
                c.status,
                c.channel,
                c.customer_id,
                cust.name AS customer_name,
                cust.phone AS customer_phone,
                c.assignee_user_id,
                c.created_at,
                c.last_message_at,
                c.last_message_preview,
                c.unread_count,
                c.sla_status,
                c.sla_deadline_at
              FROM conversations c
              LEFT JOIN customers cust
                ON cust.id = c.customer_id
               AND cust.tenant_id = c.tenant_id
             WHERE {' AND '.join(where_clauses)}
             ORDER BY {order_by}
             LIMIT :limit
        """)
        params["limit"] = min(limit, 200)

        rows = (await session.execute(sql, params)).all()
        return [
            {
                "id": str(row.id),
                "status": row.status,
                "channel": row.channel,
                "customer_id": str(row.customer_id) if row.customer_id else None,
                "customer_name": row.customer_name,
                "customer_phone": row.customer_phone,
                "assignee_user_id": str(row.assignee_user_id) if row.assignee_user_id else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
                "last_message_preview": row.last_message_preview,
                "unread_count": int(row.unread_count or 0),
                "sla_status": row.sla_status,
                "sla_deadline_at": row.sla_deadline_at.isoformat() if row.sla_deadline_at else None,
            }
            for row in rows
        ]

    @staticmethod
    async def list_messages(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        limit: int = 100,
        before_created_at=None,
        before_id: uuid.UUID | None = None,
    ) -> list[Message]:
        """Newest-first keyset fetch, returned oldest-first for display.

        Pass before_created_at (with before_id for stable ties) to page
        backwards through the history.
        """
        await ConversationService.get(session, tenant_id, conversation_id)
        stmt = select(Message).where(
            Message.tenant_id == tenant_id, Message.conversation_id == conversation_id
        )
        if before_created_at is not None and before_id is not None:
            stmt = stmt.where(
                tuple_(Message.created_at, Message.id)
                < tuple_(before_created_at, before_id)
            )
        elif before_created_at is not None:
            stmt = stmt.where(Message.created_at < before_created_at)
        stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
        return list((await session.execute(stmt)).scalars().all())[::-1]

    @staticmethod
    async def mark_read(
        session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation:
        conversation = await ConversationService.get(session, tenant_id, conversation_id)
        conversation.unread_count = 0
        await session.execute(
            select(Message).where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation_id,
                Message.direction == "inbound",
                Message.status == "received",
            )
        )
        return conversation

    @staticmethod
    async def audit(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        action: str,
        resource_id: str,
    ) -> None:
        from app.modules.platform.service import AuditService

        await AuditService.write(
            session,
            tenant_id,
            actor_user_id,
            action=action,
            resource_type="conversation",
            resource_id=resource_id,
        )

    @staticmethod
    async def reconcile_unknown_messages(
        session: AsyncSession,
        tenant_id: uuid.UUID | None = None,
        *,
        stuck_threshold_minutes: int = 15,
    ) -> list[dict]:
        """Reconcile messages stuck in 'unknown' or 'sending'.

        - If message was sending or unknown for longer than stuck_threshold_minutes,
          and no provider receipt arrived, transition to 'failed' with definitive error.
        - Emits an in-app notification / audit trail so agents know an
          outbound message failed delivery.
        """
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(minutes=stuck_threshold_minutes)
        stmt = select(Message).where(
            Message.status.in_(["unknown", "sending"]),
            Message.created_at <= cutoff,
        )
        if tenant_id is not None:
            stmt = stmt.where(Message.tenant_id == tenant_id)

        stuck_messages = list((await session.execute(stmt)).scalars().all())
        results = []
        for msg in stuck_messages:
            old_status = msg.status
            msg.status = "failed"
            msg.error = (
                f"Reconciled from '{old_status}' after "
                f"{stuck_threshold_minutes}m: provider unacknowledged"
            )
            results.append({
                "message_id": str(msg.id),
                "tenant_id": str(msg.tenant_id),
                "conversation_id": str(msg.conversation_id),
                "old_status": old_status,
                "new_status": "failed",
            })
        if results:
            await session.flush()
        return results
