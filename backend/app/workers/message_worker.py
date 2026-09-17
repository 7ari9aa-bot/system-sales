"""Message worker: consumes message events from the outbox relay.

Routing by payload["event_type"]:
- message.received → conversation pipeline (AI hook lands in Stage 6)
- message.outbound → deliver via the channel adapter, update status

Retry/DLQ semantics come from StreamWorker (base).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.core.events.bus import Event
from app.modules.conversations.gateway.base import OutboundMessage, ProviderCredentials
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.models import Conversation, Message
from app.modules.customers.models import CustomerIdentity
from app.modules.platform.models import Integration
from app.workers.base import StreamWorker

logger = logging.getLogger(__name__)


class MessageWorker(StreamWorker):
    stream = "message.events"
    group = "message-workers"
    name = "message-worker"

    async def handle(self, event: Event) -> None:
        event_type = event.payload.get("event_type")
        tenant_raw = event.meta.get("tenant_id")
        if not tenant_raw:
            logger.warning("message.event_without_tenant id=%s", event.id)
            return
        tenant_id = uuid.UUID(tenant_raw)

        if event_type == "message.received":
            await self._on_received(event, tenant_id)
        elif event_type == "message.outbound":
            await self._deliver(event, tenant_id)
        else:
            logger.debug("message.event_ignored type=%s", event_type)

    async def _on_received(self, event: Event, tenant_id: uuid.UUID) -> None:
        conversation_id = event.payload.get("conversation_id")
        logger.info("message.received conversation=%s", conversation_id)
        # AI auto-reply hook (Stage 6) — lazy import, never breaks ingest.
        if not conversation_id:
            return
        try:
            from app.modules.ai.hooks import maybe_auto_reply

            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    await maybe_auto_reply(
                        session, tenant_id, uuid.UUID(conversation_id)
                    )
        except ImportError:
            logger.debug("ai.hooks not installed — skipping auto-reply")
        except Exception:  # noqa: BLE001 — AI failures must not kill the hot path
            logger.exception("ai.auto_reply_failed conversation=%s", conversation_id)

    async def _deliver(self, event: Event, tenant_id: uuid.UUID) -> None:
        message_id = event.payload.get("message_id")
        if not message_id:
            logger.warning("outbound.event_missing_message_id id=%s", event.id)
            return
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                await self._deliver_one(session, tenant_id, uuid.UUID(message_id))

    async def _deliver_one(self, session, tenant_id: uuid.UUID, message_id: uuid.UUID) -> None:
        message = (
            await session.execute(
                select(Message).where(Message.tenant_id == tenant_id, Message.id == message_id)
            )
        ).scalar_one_or_none()
        if message is None or message.status == "sent":
            return
        conversation = (
            await session.execute(
                select(Conversation).where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.id == message.conversation_id,
                )
            )
        ).scalar_one()
        identity = (
            await session.execute(
                select(CustomerIdentity).where(
                    CustomerIdentity.tenant_id == tenant_id,
                    CustomerIdentity.customer_id == conversation.customer_id,
                    CustomerIdentity.channel == conversation.channel,
                )
            )
        ).scalar_one_or_none()
        if identity is None:
            message.status = "failed"
            message.error = "no channel identity for customer"
            return
        integration = (
            await session.execute(
                select(Integration).where(
                    Integration.tenant_id == tenant_id,
                    Integration.provider == conversation.channel,
                    Integration.kind == "channel",
                )
            )
        ).scalar_one_or_none()

        adapter = get_adapter(conversation.channel)
        if adapter is None:
            message.status = "failed"
            message.error = f"channel not configured: {conversation.channel}"
            return

        outbound = OutboundMessage(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            message_id=message.id,
            customer_ref=identity.external_id,
            body=message.body,
            media_url=message.media_url,
        )
        credentials = ProviderCredentials(
            config=(integration.credentials if integration else {}) or {}
        )
        try:
            provider_id = await adapter.send(credentials, outbound)
            message.status = "sent"
            if conversation.channel != "webchat" and message.channel_message_id is None:
                message.channel_message_id = provider_id
        except Exception as exc:  # noqa: BLE001 — surfaced into message.error
            message.status = "failed"
            message.error = str(exc)[:500]
            raise
