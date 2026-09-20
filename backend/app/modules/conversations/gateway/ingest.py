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

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.writer import add_outbox_event
from app.modules.conversations.gateway.base import InboundMessage
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService
from app.modules.platform.models import IdempotencyKey


class IngestError(Exception):
    pass


class IngestService:
    @staticmethod
    async def resolve_tenant(
        session: AsyncSession, adapter_name: str, tenant_key: str | None
    ) -> uuid.UUID | None:
        """Find the tenant whose integration matches this webhook.

        This runs BEFORE any tenant context exists, so it cannot read
        `integrations` directly: that table is FORCE-RLS and the tenant GUC is
        not bound yet, so a plain SELECT silently returned zero rows and every
        inbound webhook was acknowledged with nothing ingested.

        `public.resolve_channel_tenant` is SECURITY DEFINER (created in
        migration b2c3d4e5f6a7 and by scripts/provision.py): it performs the
        lookup with owner rights and returns ONLY the tenant id, so the
        provider credentials in `integrations.config` never leave the table.
        """
        if tenant_key is None:
            return None
        row = (
            await session.execute(
                text("SELECT public.resolve_channel_tenant(:provider, :key)"),
                {"provider": adapter_name, "key": tenant_key},
            )
        ).scalar_one_or_none()
        return uuid.UUID(str(row)) if row else None

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
        # S3: the dedupe scope MUST carry the tenant. A channel-wide scope let
        # an attacker pre-register another tenant's client_message_id; the
        # first writer wins, so the victim's real message was then silently
        # dropped as a duplicate.
        scope = f"{idempotency_scope}:{tenant_id}"
        if await cls.already_processed(session, scope, message.channel_message_id):
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
            scope,
            message.channel_message_id,
            {"conversation_id": str(conversation.id)},
        )
        # §46: the customer's message starts the first-response clock. A no-op
        # when the tenant has no SLA policy, so this costs nothing for tenants
        # that do not use SLAs. Idempotent by conversation, so a replayed
        # inbound event cannot restart (and thereby extend) the clock.
        from app.modules.operations.sla import SlaService

        await SlaService.start(
            session,
            tenant_id,
            conversation_id=conversation.id,
            channel=message.channel,
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
