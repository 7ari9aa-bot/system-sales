"""Ingest orchestration — turns a normalized InboundMessage into durable state.

Flow (hot path):
  adapter.parse_inbound → resolve tenant (integrations lookup) → idempotency
  → customer (get_or_create_by_identity) → conversation (get_or_create)
  → messages row (durable write) → outbox event (message.received)

The outbox relay forwards to Redis Streams; MessageWorker picks it up (AI,
routing, auto-replies). This function runs inside one request-level transaction
owned by the webhook router.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.writer import add_outbox_event
from app.modules.conversations.gateway.base import InboundMessage
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService
from app.modules.platform.models import IdempotencyKey, Integration


class IngestError(Exception):
    pass


class IngestService:
    @staticmethod
    async def resolve_tenant(
        session: AsyncSession, adapter_name: str, tenant_key: str | None
    ) -> uuid.UUID | None:
        """Find the tenant whose integration matches this webhook."""
        if tenant_key is None:
            return None
        integration = (
            (
                await session.execute(
                    select(Integration).where(
                        Integration.provider == adapter_name,
                        Integration.kind == "channel",
                        Integration.status == "connected",
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in integration:
            config = row.config or {}
            if tenant_key in (
                config.get("phone_number_id"),
                config.get("bot_id"),
                config.get("public_key"),
                config.get("account_id"),
            ):
                return row.tenant_id
        return None

    @staticmethod
    async def already_processed(session: AsyncSession, scope: str, key: str | None) -> bool:
        if not key:
            return False
        row = (
            await session.execute(
                select(IdempotencyKey).where(
                    IdempotencyKey.scope == scope, IdempotencyKey.key == key
                )
            )
        ).scalar_one_or_none()
        return row is not None

    @staticmethod
    async def mark_processed(
        session: AsyncSession, scope: str, key: str | None, response: dict | None = None
    ) -> None:
        if not key:
            return
        from datetime import UTC, datetime, timedelta

        session.add(
            IdempotencyKey(
                scope=scope,
                key=key,
                response=response or {},
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )

    @classmethod
    async def ingest(
        cls,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        message: InboundMessage,
        idempotency_scope: str,
    ) -> uuid.UUID | None:
        """Persist one inbound message; returns conversation_id or None on dup."""
        if await cls.already_processed(session, idempotency_scope, message.channel_message_id):
            return None

        customer = await CustomerService.get_or_create_by_identity(
            session,
            tenant_id,
            channel=message.channel,
            external_id=message.customer_ref,
            name=message.customer_name,
        )
        conversation = await ConversationService.get_or_create(
            session, tenant_id, customer_id=customer.id, channel=message.channel
        )
        created = await ConversationService.add_message(
            session,
            tenant_id,
            conversation_id=conversation.id,
            direction="inbound",
            sender_type="customer",
            body=message.body,
            media_url=message.media_url,
            media_type=message.media_type,
            channel_message_id=message.channel_message_id,
            payload={"raw": message.raw} if message.raw else None,
        )
        await cls.mark_processed(
            session,
            idempotency_scope,
            message.channel_message_id,
            {"conversation_id": str(conversation.id)},
        )
        await add_outbox_event(
            session,
            aggregate_type="message",
            aggregate_id=created.id,
            event_type="message.received",
            tenant_id=tenant_id,
            payload={
                "conversation_id": str(conversation.id),
                "customer_id": str(customer.id),
                "channel": message.channel,
                "body": message.body,
                "media_url": message.media_url,
                "media_type": message.media_type,
            },
        )
        return conversation.id
