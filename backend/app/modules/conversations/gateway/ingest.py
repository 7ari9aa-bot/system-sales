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

from sqlalchemy import case, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.writer import add_outbox_event
from app.modules.conversations.gateway.base import InboundMessage
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService
from app.modules.platform.models import IdempotencyKey, WebhookEvent


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
        # §155: convert provider reply_to_message_id (string) to UUID if
        # it matches a local message. None if it doesn't (foreign reply).
        reply_to_uuid: uuid.UUID | None = None
        if message.reply_to_message_id:
            try:
                reply_to_uuid = uuid.UUID(message.reply_to_message_id)
            except ValueError:
                reply_to_uuid = None  # provider-side id, not a local UUID

        created = await ConversationService.add_message(
            session,
            tenant_id,
            conversation_id=conversation.id,
            direction="inbound",
            sender_type="customer",
            body=message.body,
            media_url=message.media_url,
            media_type=message.media_type,
            content_type=message.content_type,
            reply_to_message_id=reply_to_uuid,
            channel_message_id=message.channel_message_id,
            payload={"raw": message.raw} if message.raw else None,
        )
        await cls.mark_processed(
            session,
            scope,
            message.channel_message_id,
            {"conversation_id": str(conversation.id)},
        )

        # §142: also record in the tenant-scoped inbound_message_dedupe table.
        # This is a SEPARATE dedupe record from the IdempotencyKey (which is
        # scope-based). The InboundMessageDedupe table is (tenant_id,
        # channel_account_id, external_message_id) and lives on its own
        # retention lifecycle — it can be pruned independently of the
        # IdempotencyKey (which expires after 7 days). The dedupe record
        # has no response payload — it is a pure existence check.
        from app.modules.platform.models import InboundMessageDedupe

        existing_dedupe = (
            await session.execute(
                select(InboundMessageDedupe).where(
                    InboundMessageDedupe.tenant_id == tenant_id,
                    InboundMessageDedupe.channel_account_id == message.customer_ref,
                    InboundMessageDedupe.external_message_id == message.channel_message_id,
                )
            )
        ).scalar_one_or_none()
        if existing_dedupe is None:
            session.add(
                InboundMessageDedupe(
                    tenant_id=tenant_id,
                    channel_account_id=message.customer_ref,
                    external_message_id=message.channel_message_id,
                )
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
                # The consumer must know WHICH message this event carries. Without
                # it the AI hook answers "the newest inbound message", so a delayed
                # delivery answers a later message twice and the earlier one never.
                "message_id": str(created.id),
                "customer_id": str(customer.id),
                "channel": message.channel,
                "body": message.body,
                "media_url": message.media_url,
                "media_type": message.media_type,
            },
            # Literal: Message is append-only (AppendOnlyCreatedAtMixin) with
            # no version column — a message row is never mutated, so 1 is its
            # only possible aggregate version (§153).
            aggregate_version=1,
        )
        return conversation.id

    # ------------------------------------------------ §24 ingress lifecycle --

    @staticmethod
    async def process_webhook_event(
        session: AsyncSession,
        *,
        adapter,
        channel: str,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        payload: dict,
    ) -> int:
        """The synchronous processing block for one stored ingress row.

        parse → ingest → delivery receipts → processed marker, all inside a
        SAVEPOINT: a failure anywhere in the block rolls back ALL of its
        writes (including the processed marker) while leaving the caller's
        transaction alive. The webhook router calls this to ACK 200 and
        quarantine the row on failure (§24 — provider retry storms help
        nobody); the WebhookWorker retry re-runs this EXACT block, so a
        retried event is processed by the same code path that failed once.

        Returns the accepted-message count; raises on failure — the caller
        decides the fate of the ingress row via `mark_webhook_event_failed`.
        """
        from app.core.db import bind_tenant

        # RLS: ingest writes tenant-scoped rows — bind the GUC before any insert.
        await bind_tenant(session, tenant_id)
        accepted = 0
        async with session.begin_nested():
            for message in adapter.parse_inbound(payload):
                conversation_id = await IngestService.ingest(
                    session,
                    tenant_id=tenant_id,
                    message=message,
                    idempotency_scope=f"webhook:{channel}",
                )
                if conversation_id is not None:
                    accepted += 1
            await IngestService.apply_status_updates(
                session, tenant_id, adapter.parse_status_updates(payload)
            )
            await session.execute(
                sa_update(WebhookEvent)
                .where(WebhookEvent.id == event_id)
                .values(
                    processing_status="processed",
                    attempts=WebhookEvent.attempts + 1,
                )
            )
        return accepted

    @staticmethod
    async def mark_webhook_event_failed(
        session: AsyncSession, event_id: uuid.UUID, exc: Exception
    ) -> None:
        """§24: quarantine a failed ingress row in the caller's transaction.

        The error text is recorded and attempts incremented. While the retry
        budget holds, the row stays ``failed`` for the WebhookWorker sweep;
        the failure that SPENDS the budget dead-letters it instead (§24:
        Retry 1..N → Dead Letter Queue). A dead row leaves the automatic
        rotation for good — only an explicit human decision replays, ignores
        or resolves it — and it is never deleted: nothing disappears.
        """
        from app.core.config import get_settings

        max_attempts = get_settings().worker_max_attempts
        await session.execute(
            sa_update(WebhookEvent)
            .where(WebhookEvent.id == event_id)
            .values(
                processing_status=case(
                    (WebhookEvent.attempts + 1 >= max_attempts, "dead"),
                    else_="failed",
                ),
                last_error=str(exc)[:500],
                attempts=WebhookEvent.attempts + 1,
            )
        )

    @staticmethod
    async def apply_status_updates(session, tenant_id: uuid.UUID, updates) -> None:
        """Delivery receipts: update our outbound message rows by provider id.

        Monotonic state machine (§130): a receipt may only move a message
        forward. Out-of-order or replayed provider events (e.g. a late `sent`
        after `read`) are dropped instead of regressing the row.
        """
        from app.modules.conversations.models import Message

        # target status → statuses it may legally be advanced from
        _FORWARD_FROM: dict[str, tuple[str, ...]] = {
            "sent": ("queued", "sending", "unknown"),
            "delivered": ("queued", "sending", "unknown", "sent"),
            "read": ("queued", "sending", "unknown", "sent", "delivered"),
            "failed": ("queued", "sending", "unknown"),
        }

        for receipt in updates:
            if not receipt.channel_message_id or not receipt.status:
                continue
            allowed_from = _FORWARD_FROM.get(receipt.status)
            if allowed_from is None:
                continue  # unknown/arbitrary provider status — never written raw
            values: dict = {"status": receipt.status}
            if receipt.error:
                values["error"] = receipt.error
            await session.execute(
                sa_update(Message)
                .where(
                    Message.tenant_id == tenant_id,
                    Message.channel_message_id == receipt.channel_message_id,
                    Message.direction == "outbound",
                    Message.status.in_(allowed_from),
                )
                .values(**values)
            )
