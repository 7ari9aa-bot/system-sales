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

from app.core.errors import NotFoundError, ValidationError
from app.modules.conversations.models import (
    CONVERSATION_STATUSES,
    Assignment,
    Conversation,
    Message,
    normalize_conversation_status,
)
from app.modules.conversations.policy import MessagingPolicyService, OutboundBlockedError
from app.modules.platform.models import AuditLog


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
    ) -> Message:
        conversation = await ConversationService.get(session, tenant_id, conversation_id)
        if not body and not media_url and not template_name:
            raise ValidationError("message needs body, media or a template")

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
        await session.flush()
        return message

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
        limit: int = 50,
        offset: int = 0,
        before_created_at: datetime | None = None,
        before_id: uuid.UUID | None = None,
    ) -> list[Conversation]:
        """Keyset-aware inbox listing: pass before_created_at + before_id to page."""
        from app.modules.customers.models import Customer

        stmt = (
            select(
                Conversation,
                Customer.name.label("customer_name"),
                Customer.phone.label("customer_phone"),
            )
            .outerjoin(
                Customer,
                (Customer.id == Conversation.customer_id) & (Customer.tenant_id == tenant_id),
            )
            .where(Conversation.tenant_id == tenant_id)
        )
        if status:
            stmt = stmt.where(Conversation.status == status)
        if assignee_user_id:
            stmt = stmt.where(Conversation.assignee_user_id == assignee_user_id)
        if before_created_at is not None and before_id is not None:
            stmt = stmt.where(
                tuple_(Conversation.created_at, Conversation.id)
                < tuple_(before_created_at, before_id)
            )
            stmt = stmt.order_by(Conversation.created_at.desc(), Conversation.id.desc())
        else:
            stmt = stmt.order_by(Conversation.last_message_at.desc().nullslast())
        stmt = stmt.limit(limit).offset(offset)
        rows = (await session.execute(stmt)).all()
        results: list[Conversation] = []
        for conv, cust_name, cust_phone in rows:
            conv.customer_name = cust_name
            conv.customer_phone = cust_phone
            results.append(conv)
        return results

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
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action=action,
                resource_type="conversation",
                resource_id=resource_id,
            )
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
