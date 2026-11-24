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

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import case, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.events.writer import add_outbox_event
from app.modules.conversations.gateway.base import InboundMessage
from app.modules.conversations.models import Conversation, Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService
from app.modules.platform.models import IdempotencyKey, Integration, WebhookEvent

logger = logging.getLogger(__name__)


async def _channel_credentials(session, tenant_id, channel) -> dict | None:
    """A connected channel's decrypted settings. The one place this file reaches the platform
    module for them, so the cross-module import is counted once."""
    from app.modules.platform.services.channel_access import channel_credentials_config

    return await channel_credentials_config(session, tenant_id, channel)


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
    async def resolve_account_tenant(session: AsyncSession, waba_id: str) -> uuid.UUID | None:
        """The store that owns a WhatsApp Business Account, or None when it is not exactly one.

        Same reasons as `resolve_tenant`: it runs before any store is bound, so it goes through
        a SECURITY DEFINER function that returns only the store id.
        """
        if not waba_id:
            return None
        row = (
            await session.execute(
                text("SELECT public.resolve_whatsapp_waba_tenant(:waba)"), {"waba": waba_id}
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

    @staticmethod
    async def _resolve_reply_target(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        provider_ref: str | None,
    ) -> uuid.UUID | None:
        """Local message a provider reply points at, or None if we never stored it."""
        if not provider_ref:
            return None
        found = await session.execute(
            select(Message.id).where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation_id,
                Message.channel_message_id == provider_ref,
            )
        )
        return found.scalar_one_or_none()

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
        # A message that names no customer is not a customer turn: storing it would put every
        # such message on one blank identity, so two different people would share one thread.
        # The adapters drop them at parse time; this is the invariant behind that.
        if not str(message.customer_ref or "").strip():
            raise ValidationError(
                f"{message.channel} message without a customer identity cannot be stored"
            )

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
            identity_extra=cls._identity_extra(message),
        )
        conversation = await ConversationService.get_or_create(
            session, tenant_id, customer_id=customer.id, channel=message.channel
        )
        # Who is this customer? Messenger and Instagram name them only by a provider-scoped
        # number, so a new thread would read as a bare id until someone asked for the profile.
        # The read runs beside the message: it never delays the webhook's 200, never fails the
        # ingest, and the profile service decides for itself when a refresh is due.
        cls._enrich_profile_soon(tenant_id, customer.id, message.channel)
        # §155: a provider reply/reaction names its target by the PROVIDER's id
        # (a WhatsApp wamid), never by our UUID. Resolve it to the local message,
        # but only inside THIS conversation: a forged id naming another
        # customer's message must not link to it. The provider id is kept in
        # provider_metadata so a target we never stored (older than our history)
        # can still be shown as an unresolved quote instead of vanishing.
        reply_to_uuid = await cls._resolve_reply_target(
            session, tenant_id, conversation.id, message.reply_to_message_id
        )
        provider_metadata = (
            {"reply_to_provider_id": message.reply_to_message_id}
            if message.reply_to_message_id
            else None
        )
        referral = cls._referral_details(message)
        if referral:
            # Meta extends the messaging window to 7 days for a conversation that began from a
            # Click-to-Messenger / Click-to-Direct ad (add_message turns `from_ad` into the
            # marker), and the ad itself is context the agent needs: which campaign brought this
            # person in. Only the fields Meta sent, checked, so a hostile payload cannot put
            # anything else on the screen.
            provider_metadata = {**(provider_metadata or {}), "referral": referral}
            if str(referral.get("source") or "").upper() == "ADS" or referral.get("ad_id"):
                provider_metadata["from_ad"] = True

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
            provider_metadata=provider_metadata,
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

    @staticmethod
    def _identity_extra(message: InboundMessage) -> dict:
        """What the provider says about this handle, for the identity row (empty when nothing)."""
        extra: dict = {}
        identity_type = getattr(message, "identity_type", "") or ""
        if identity_type and identity_type != "phone":
            # A BSUID is worth recording: it is the only handle a number-less customer has, and
            # support needs to know that this thread is not tied to a phone at all.
            extra["identity_type"] = identity_type
        if getattr(message, "username", None):
            extra["username"] = message.username
        if getattr(message, "parent_ref", None):
            extra["parent_ref"] = message.parent_ref
        return extra

    # ------------------------------------------------- who the customer is --

    @staticmethod
    def _enrich_profile_soon(tenant_id: uuid.UUID, customer_id: uuid.UUID, channel: str) -> None:
        """Learn a Meta customer's name and photo without making the webhook wait for Meta.

        Fire-and-forget by design: the caller is the ingest path, which owes Meta a fast 200.
        A refusal, a timeout or a missing channel config is a missing name, never a lost message.
        """
        if channel not in ("messenger", "instagram"):
            return

        async def _run() -> None:
            from app.core.db import SessionLocal, bind_tenant
            from app.modules.conversations.customer_profile import CustomerProfileService
            from app.modules.platform.services.channel_access import channel_credentials_config

            try:
                async with SessionLocal() as bg:
                    await bind_tenant(bg, tenant_id)
                    config = await channel_credentials_config(bg, tenant_id, channel)
                    if not config or not config.get("api_key"):
                        return
                    enrich = (
                        CustomerProfileService.enrich_messenger_for
                        if channel == "messenger"
                        else CustomerProfileService.enrich_instagram_for
                    )
                    await enrich(bg, tenant_id, customer_id, config)
                    await bg.commit()
            except Exception:  # noqa: BLE001 - a name is a courtesy, a message is the job
                logger.warning(
                    "ingest.profile_enrich_failed tenant=%s channel=%s",
                    tenant_id,
                    channel,
                    exc_info=True,
                )

        try:
            asyncio.create_task(_run())
        except RuntimeError:  # no running loop (a sync test, a CLI replay): skip the courtesy
            logger.warning("ingest.profile_enrich_no_loop tenant=%s channel=%s", tenant_id, channel)

    @staticmethod
    async def _open_conversation(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str, customer_id: uuid.UUID
    ) -> Conversation | None:
        """The one live conversation this customer has on this channel, if any."""
        return (
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

    @staticmethod
    async def apply_echoes(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        channel: str,
        echoes: list[dict],
        *,
        own_app_id: str | None = None,
    ) -> int:
        """Store replies a person sent from OUTSIDE this system (Meta Business Suite).

        Meta echoes every message the Page sends, including our own, so an echo whose
        ``app_id`` is this app is skipped — we already stored that message when we sent
        it. Anything else becomes a real outbound message on the thread, so the merchant
        sees it in FIHRIST and the agent does not answer the customer twice.

        An echo for a customer we have never seen, or with no live conversation, is
        dropped: a courtesy record must never fail the batch that carries real messages.
        """
        stored = 0
        for echo in echoes:
            mid = str(echo.get("mid") or "")
            app_id = str(echo.get("app_id") or "")
            body = echo.get("text")
            customer_ref = str(echo.get("customer_ref") or "")
            if not mid or not body or not customer_ref:
                continue
            if own_app_id and app_id and app_id == str(own_app_id):
                continue
            customer = await CustomerService.find_by_identity(
                session, tenant_id, channel, customer_ref
            )
            if customer is None:
                continue
            already = (
                await session.execute(
                    select(Message.id)
                    .where(
                        Message.tenant_id == tenant_id,
                        Message.channel_message_id == mid,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if already is not None:
                continue
            conversation = await IngestService._open_conversation(
                session, tenant_id, channel, customer.id
            )
            if conversation is None:
                continue
            await ConversationService.add_message(
                session,
                tenant_id,
                conversation_id=conversation.id,
                direction="outbound",
                sender_type="agent",
                body=body,
                channel_message_id=mid,
                payload={"source": "meta_echo", "app_id": app_id or None},
            )
            stored += 1
        return stored

    # ------------------------------------------------- coexistence backfill --

    @staticmethod
    async def _store_imported_message(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        channel: str,
        item: dict,
        *,
        direction: str,
        sender_type: str,
        source: str,
        status: str,
    ) -> int:
        """Write one already-sent message from the app's history or echoes, at its real time.

        Deliberately NOT ``ConversationService.add_message``: that path applies the outbound
        policy (a historical outbound message would be refused outside the 24-hour window, which
        is nonsense — it was sent months ago) and stamps ``last_customer_message_at = now()``,
        which would open a fake service window from the moment of import. Here the timestamps come
        from Meta, the unread counter does not move, and the window only moves FORWARD to a real
        historical inbound time, never to "now".
        """
        mid = item.get("channel_message_id")
        if not mid:
            return 0
        already = (
            await session.execute(
                select(Message.id)
                .where(Message.tenant_id == tenant_id, Message.channel_message_id == mid)
                .limit(1)
            )
        ).scalar_one_or_none()
        if already is not None:
            # A duplicate webhook, or the same message arriving in history and live: the first
            # copy wins and nothing is written twice.
            return 0
        identity_extra = {
            key: item.get(key)
            for key in ("identity_type", "username", "parent_ref")
            if item.get(key) is not None
        }
        customer = await CustomerService.get_or_create_by_identity(
            session,
            tenant_id,
            channel=channel,
            external_id=item["customer_ref"],
            name=None,
            phone=item.get("phone"),
            identity_extra=identity_extra or None,
        )
        conversation = await ConversationService.get_or_create(
            session, tenant_id, customer_id=customer.id, channel=channel
        )
        when = item.get("occurred_at") or datetime.now(UTC)
        # §155 threading, same rule as the live path: the provider names its target by wamid, so
        # resolve it inside THIS conversation only, and keep the provider id in metadata when the
        # parent is not stored yet — an imported reply must not lose its quote just because the
        # message it answers arrived in a later chunk.
        reply_ref = item.get("reply_to_message_id")
        reply_to_uuid = (
            await IngestService._resolve_reply_target(
                session, tenant_id, conversation.id, reply_ref
            )
            if reply_ref
            else None
        )
        provider_metadata = {"imported_from": source}
        if reply_ref:
            provider_metadata["reply_to_provider_id"] = reply_ref
        session.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                channel=channel,
                direction=direction,
                sender_type=sender_type,
                body=item.get("body"),
                media_url=item.get("media_url"),
                media_type=item.get("media_type"),
                content_type=item.get("content_type") or "text",
                channel_message_id=mid,
                status=status,
                reply_to_message_id=reply_to_uuid,
                payload={"raw": item.get("raw") or {}, "imported_from": source},
                provider_metadata=provider_metadata,
                created_at=when,
            )
        )
        if conversation.last_message_at is None or when > conversation.last_message_at:
            conversation.last_message_at = when
        if direction == "inbound" and (
            conversation.last_customer_message_at is None
            or when > conversation.last_customer_message_at
        ):
            # The customer's real last message time, not the import time: the service window is
            # whatever it honestly is.
            conversation.last_customer_message_at = when
        return 1

    @staticmethod
    async def apply_history(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        channel: str,
        batches: list[dict],
        *,
        epoch: str | None = None,
    ) -> int:
        """Import the app's chat history: stored in place, at its own time, and never answered.

        No outbox event is emitted, so the AI never runs on a historical message — a backfill of
        thousands of old messages must not produce thousands of replies.
        """
        from app.modules.conversations import whatsapp_sync

        if epoch is None:
            first_number = batches[0].get("phone_number_id") if batches else None
            epoch = await whatsapp_sync.channel_epoch(
                session, tenant_id, phone_number_id=first_number or None
            )
        stored = 0
        for batch in batches:
            if (
                epoch
                and await whatsapp_sync.attribute_chunk(
                    session,
                    tenant_id,
                    phone_number_id=str(batch.get("phone_number_id") or ""),
                    epoch=epoch,
                    sync_type=whatsapp_sync.WHATSAPP_SYNC_HISTORY,
                    request_id=batch.get("request_id"),
                )
                is None
            ):
                # Not this run's history: not one message from it is stored. Checking before the
                # write is the point — after it, the rows are already in a conversation they do
                # not belong to.
                continue
            batch_stored = 0
            for item in batch.get("messages") or []:
                batch_stored += await IngestService._store_imported_message(
                    session,
                    tenant_id,
                    channel,
                    item,
                    direction=item["direction"],
                    sender_type="customer" if item["direction"] == "inbound" else "agent",
                    source="whatsapp_history",
                    status=item.get("status")
                    or ("received" if item["direction"] == "inbound" else "sent"),
                )
            stored += batch_stored
            if epoch:
                # Progress is folded in AFTER the rows are written, so a crash mid-chunk leaves the
                # run behind reality (retryable) instead of ahead of it (a lie).
                await whatsapp_sync.record_chunk(
                    session,
                    tenant_id,
                    phone_number_id=str(batch.get("phone_number_id") or ""),
                    epoch=epoch,
                    sync_type=whatsapp_sync.WHATSAPP_SYNC_HISTORY,
                    request_id=batch.get("request_id"),
                    phase=batch.get("phase"),
                    chunk_order=batch.get("chunk_order"),
                    progress=batch.get("progress"),
                    messages_stored=batch_stored,
                    chunk_key=batch.get("chunk_key"),
                    not_shared=bool(batch.get("not_shared")),
                    error=batch.get("error"),
                )
        return stored

    @staticmethod
    async def apply_app_state_sync(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        channel: str,
        batches: list[dict],
        *,
        epoch: str | None = None,
    ) -> int:
        """Turn the app's contact list into customers — no conversations, no AI.

        A contact update is not a message: it must not open a conversation, page anyone or start an
        agent run. A removal is recorded as nothing at all on purpose: the customer may have open
        conversations and their history is still theirs.
        """
        from app.modules.conversations import whatsapp_sync

        if epoch is None:
            first_number = batches[0].get("phone_number_id") if batches else None
            epoch = await whatsapp_sync.channel_epoch(
                session, tenant_id, phone_number_id=first_number or None
            )
        stored = 0
        for batch in batches:
            if (
                epoch
                and await whatsapp_sync.attribute_chunk(
                    session,
                    tenant_id,
                    phone_number_id=str(batch.get("phone_number_id") or ""),
                    epoch=epoch,
                    sync_type=whatsapp_sync.WHATSAPP_SYNC_CONTACTS,
                    request_id=batch.get("request_id"),
                )
                is None
            ):
                # A stale contact batch must not create customers, and must not touch the run.
                continue
            if epoch:
                await whatsapp_sync.record_chunk(
                    session,
                    tenant_id,
                    phone_number_id=str(batch.get("phone_number_id") or ""),
                    epoch=epoch,
                    sync_type=whatsapp_sync.WHATSAPP_SYNC_CONTACTS,
                    request_id=batch.get("request_id"),
                    messages_stored=0,
                    chunk_key=batch.get("chunk_key"),
                    contacts_snapshot_received=True,
                )
            for contact in batch.get("contacts") or []:
                identity_ref = str(
                    contact.get("identity_ref") or contact.get("phone") or ""
                ).strip()
                if not identity_ref:
                    continue
                action_at = contact.get("timestamp") or batch.get("timestamp")
                existing_customer = await CustomerService.find_by_identity(
                    session, tenant_id, channel, identity_ref
                )
                existing_identity = (
                    await CustomerService.channel_identity(
                        session, tenant_id, existing_customer.id, channel
                    )
                    if existing_customer is not None
                    else None
                )
                previous_extra = (
                    existing_identity.extra
                    if existing_identity and isinstance(existing_identity.extra, dict)
                    else {}
                )
                previous_at = previous_extra.get("whatsapp_app_contact_updated_at")
                if action_at and previous_at:
                    try:
                        if datetime.fromisoformat(previous_at) > action_at:
                            continue
                    except (TypeError, ValueError):
                        pass
                identity_extra = {
                    "identity_type": contact.get("identity_type") or "phone",
                    "whatsapp_app_contact": contact.get("action") != "remove",
                    "whatsapp_app_contact_action": contact.get("action") or "add",
                    "whatsapp_app_contact_updated_at": action_at.isoformat() if action_at else None,
                    "username": contact.get("username"),
                    "parent_ref": contact.get("parent_ref"),
                }
                if contact.get("action") == "remove":
                    customer = await CustomerService.find_by_identity(
                        session, tenant_id, channel, identity_ref
                    )
                    if customer is None:
                        continue
                    identity = await CustomerService.channel_identity(
                        session, tenant_id, customer.id, channel
                    )
                    if identity is not None:
                        previous = identity.extra if isinstance(identity.extra, dict) else {}
                        previous_at = previous.get("whatsapp_app_contact_updated_at")
                        # Older or duplicate removals cannot overwrite a newer re-add.
                        if action_at and previous_at:
                            try:
                                if datetime.fromisoformat(previous_at) > action_at:
                                    continue
                            except (TypeError, ValueError):
                                pass
                        identity.extra = {**previous, **identity_extra}
                    continue
                customer = await CustomerService.get_or_create_by_identity(
                    session,
                    tenant_id,
                    channel=channel,
                    external_id=identity_ref,
                    name=contact.get("name"),
                    phone=contact.get("phone"),
                    identity_extra=identity_extra,
                )
                if contact.get("name"):
                    customer.name = contact["name"]
                stored += 1
        return stored

    @staticmethod
    async def apply_app_echoes(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str, echoes: list[dict]
    ) -> int:
        """Store what the merchant typed in the WhatsApp Business app on their phone.

        This is the promise coexistence makes: the same thread, from the app and from FIHRIST. An
        echo becomes a real outbound message from a HUMAN, it may start a conversation the merchant
        began from their phone, and it takes the thread away from the AI — otherwise the agent,
        which never saw the reply, answers the customer a second time with a different answer.

        Storing the row and taking the thread are two separate guarantees. The launch blocker was
        coupling them: an echo whose wamid history sync had ALREADY imported found the row, skipped
        the rest of the loop and left the conversation with the agent — the merchant had answered
        from the phone and the AI could still reply over them. So the handover below runs for every
        echo that is genuinely the merchant's, whether or not this call wrote the row.

        The one duplicate that must NOT take the thread is our own send coming back as an echo:
        that is the AI's own message, and silencing the agent after it answers would break the
        channel. ``payload.imported_from`` is the discriminator: imports carry it, sends do not.
        """
        stored = 0
        for echo in echoes:
            mid = echo.get("channel_message_id")
            wrote = await IngestService._store_imported_message(
                session,
                tenant_id,
                channel,
                echo,
                direction="outbound",
                sender_type="agent",
                source="whatsapp_business_app",
                status="sent",
            )
            stored += wrote
            if not wrote and mid:
                existing_payload = (
                    await session.execute(
                        select(Message.payload)
                        .where(
                            Message.tenant_id == tenant_id,
                            Message.channel_message_id == mid,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                imported = isinstance(existing_payload, dict) and bool(
                    existing_payload.get("imported_from")
                )
                if not imported:
                    # Our own send echoed back: nothing to store and nothing to hand over.
                    continue
            customer_ref = str(echo.get("customer_ref") or "")
            if not customer_ref:
                continue
            customer = await CustomerService.find_by_identity(
                session, tenant_id, channel, customer_ref
            )
            if customer is None:
                continue
            conversation = await IngestService._open_conversation(
                session, tenant_id, channel, customer.id
            )
            if conversation is None:
                continue
            from app.modules.ai.handover import request_human_takeover

            # Idempotent by design: an open handover is reused, never duplicated. A failure here is
            # NOT logged and swallowed — the agent would keep the thread and answer over the
            # merchant. Raising fails the webhook event so it is retried, and the retry is safe
            # because the message row is already deduped by wamid.
            await request_human_takeover(
                session,
                tenant_id,
                conversation_id=conversation.id,
                reason="whatsapp_business_app_reply",
                note="replied from the WhatsApp Business app on the phone",
            )
        return stored

    @staticmethod
    async def apply_unsupported_notices(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str, notices: list[dict]
    ) -> int:
        """Record a message Meta could not hand over, without degrading the whole channel.

        On a coexistence number this is usually a first message after the link or one from an
        unsupported companion device: the message exists in the merchant's app and will never
        reach FIHRIST, so it is written as a system note on the conversation (or on a fresh one) and
        nothing else changes.
        """
        recorded = 0
        for notice in notices:
            mid = notice.get("channel_message_id")
            if not mid:
                continue
            already = (
                await session.execute(
                    select(Message.id)
                    .where(
                        Message.tenant_id == tenant_id,
                        Message.channel_message_id == f"unsupported:{mid}",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if already is not None:
                continue
            recipient_ref = str(notice.get("recipient_ref") or "").strip()
            if not recipient_ref:
                logger.warning(
                    (
                        "whatsapp.unsupported_message_without_recipient "
                        "tenant=%s channel=%s message_id=%s"
                    ),
                    tenant_id,
                    channel,
                    mid,
                )
                continue
            customer = await CustomerService.get_or_create_by_identity(
                session,
                tenant_id,
                channel=channel,
                external_id=recipient_ref,
                name=None,
                identity_extra={"identity_type": "phone"},
            )
            conversation = await ConversationService.get_or_create(
                session, tenant_id, customer_id=customer.id, channel=channel
            )
            detail = str(notice.get("details") or notice.get("title") or "").strip()
            session.add(
                Message(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    channel=channel,
                    direction="inbound",
                    sender_type="system",
                    body=(
                        "A WhatsApp message could not be delivered to FIHRIST because it came "
                        "from an unsupported device or message type."
                        + (f" Meta: {detail}" if detail else "")
                    ),
                    content_type="unsupported",
                    channel_message_id=f"unsupported:{mid}",
                    status="received",
                    payload={"notice_code": 131060, "provider_message_id": mid},
                    provider_metadata={"imported_from": "whatsapp_unsupported_notice"},
                )
            )
            conversation.last_message_at = datetime.now(UTC)
            recorded += 1
        return recorded

    @staticmethod
    async def apply_edits(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str, edits: list[dict]
    ) -> int:
        """Rewrite a message Meta says was edited, keeping what it said before.

        The original body is kept once in ``provider_metadata.original_body`` so a second edit
        does not overwrite the history, and ``edited`` is set so the UI can show its marker.
        A mid we do not hold (another tenant's message, or one we never stored) is ignored: an
        edit may never touch a row outside this tenant, and must never create a new message.
        """
        updated = 0
        for edit in edits:
            mid = str(edit.get("mid") or "")
            if not mid:
                continue
            row = (
                await session.execute(
                    select(Message).where(
                        Message.tenant_id == tenant_id,
                        Message.channel_message_id == mid,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                continue
            if row.channel and channel and row.channel != channel:
                continue
            text = edit.get("text")
            if isinstance(text, str) and text and text != row.body:
                metadata = dict(row.provider_metadata or {})
                metadata.setdefault("original_body", row.body)
                metadata["edited_at"] = edit.get("timestamp")
                row.body = text
                row.provider_metadata = metadata
            row.edited = True
            updated += 1
        return updated

    @staticmethod
    async def apply_handover(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str, handover: dict
    ) -> bool:
        """Meta thread control, applied to our own conversation state.

        ``take_thread_control`` means a person owns the thread now: the handover record is
        opened and the conversation moves to ``waiting_human``, which is exactly what stops
        the agent from answering. ``pass_thread_control`` gives it back, so a thread left in
        ``waiting_human`` returns to the AI. ``request_thread_control`` only asks for it and
        changes nothing.
        """
        customer_ref = str(handover.get("customer_ref") or "")
        event = str(handover.get("event") or "")
        if not customer_ref or event not in ("take_thread_control", "pass_thread_control"):
            return False
        customer = await CustomerService.find_by_identity(session, tenant_id, channel, customer_ref)
        if customer is None:
            return False
        conversation = await IngestService._open_conversation(
            session, tenant_id, channel, customer.id
        )
        if conversation is None:
            return False
        if event == "take_thread_control":
            from app.modules.ai.handover import request_human_takeover

            return await request_human_takeover(
                session,
                tenant_id,
                conversation_id=conversation.id,
                reason="meta_thread_control",
                note="control taken outside FIHRIST (Meta inbox or another app)",
            )
        if conversation.status == "waiting_human":
            await ConversationService.set_status(session, tenant_id, conversation.id, "open")
            return True
        return False

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
            messages = adapter.parse_inbound(payload)
            await IngestService.fill_customer_names(
                session, tenant_id=tenant_id, adapter=adapter, channel=channel, messages=messages
            )
            for message in messages:
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
            # Messenger read receipts name a time, not a message: "read everything up to T".
            parse_reads = getattr(adapter, "parse_read_watermarks", None)
            if callable(parse_reads):
                await IngestService.apply_read_watermarks(
                    session, tenant_id, channel, parse_reads(payload)
                )
            # Public comments ride the same signed envelope (field "feed" /
            # "comments"). They are interaction data, not conversation turns:
            # persisted for the analyst, never fanned out to the AI. Adapters
            # without a comment parser (whatsapp, telegram, webchat) simply
            # contribute none.
            parse_comments = getattr(adapter, "parse_comments", None)
            if callable(parse_comments):
                from app.modules.conversations.social_comments import SocialCommentService

                for comment in parse_comments(payload):
                    await SocialCommentService.ingest(
                        session, tenant_id, platform=channel, comment=comment
                    )
                    accepted += 1
            # A story's numbers, delivered after it expires. Parsed by nothing before, so every
            # story metric Meta sent was dropped on the floor.
            parse_story_insights = getattr(adapter, "parse_story_insights", None)
            if callable(parse_story_insights):
                from app.modules.conversations.instagram_insights import StoryInsightsService

                deliveries = parse_story_insights(payload)
                if deliveries:
                    outcome = await StoryInsightsService.apply(
                        session, tenant_id, channel, deliveries
                    )
                    logger.info(
                        "instagram.story_insights_applied",
                        extra={"tenant_id": str(tenant_id), "channel": channel, **outcome},
                    )
            # Replies typed in Meta's own inbox (or another app) come back as `is_echo`.
            # The parsers existed and were never called, so a staff reply from Meta
            # Business Suite never reached FIHRIST and the agent answered the same
            # customer a second time.
            parse_echoes = getattr(adapter, "parse_echoes", None)
            if callable(parse_echoes):
                from app.core.config import settings

                accepted += await IngestService.apply_echoes(
                    session,
                    tenant_id,
                    channel,
                    parse_echoes(payload),
                    own_app_id=settings.meta_app_id or None,
                )
            # The Page's OWN feed: a post edited, shared, hidden, published or reacted to. The
            # comment parser above ignores everything that is not a comment, so these changes used
            # to disappear and the merchant kept seeing the post as it was on publication day.
            parse_feed = getattr(adapter, "parse_feed_events", None)
            if callable(parse_feed):
                from app.modules.conversations.facebook_feed import PageEventProcessor

                changes = parse_feed(payload)
                if changes:
                    outcome = await PageEventProcessor.apply(session, tenant_id, channel, changes)
                    logger.info(
                        "facebook.feed_applied",
                        extra={"tenant_id": str(tenant_id), "channel": channel, **outcome},
                    )
                    # The same events are the notifications screen's food. They are recorded even
                    # when `apply` could not find the object (unknown_post): a post published
                    # before the Page was connected is still news the merchant should see, and
                    # the row is what makes the read mark shared instead of per browser.
                    from app.modules.conversations.page_activity_service import (
                        PageActivityService,
                    )

                    noted = await PageActivityService.record_changes(
                        session, tenant_id, channel, changes
                    )
                    logger.info(
                        "facebook.feed_activity",
                        extra={"tenant_id": str(tenant_id), "channel": channel, **noted},
                    )
            # Coexistence: the WhatsApp Business app's OWN data. These three fields exist only
            # for a number that runs the app and the Cloud API together, and none of them is a
            # live customer turn — so they are handled here, apart from parse_inbound, and none of
            # the history import emits an outbox event. Thousands of imported messages must not
            # become thousands of AI answers.
            parse_history = getattr(adapter, "parse_history_sync", None)
            if callable(parse_history):
                history_batches = parse_history(payload)
                if history_batches:
                    imported = await IngestService.apply_history(
                        session, tenant_id, channel, history_batches
                    )
                    logger.info(
                        "whatsapp.history_imported",
                        extra={
                            "tenant_id": str(tenant_id),
                            "channel": channel,
                            "messages": imported,
                            "chunks": len(history_batches),
                        },
                    )
            parse_state_sync = getattr(adapter, "parse_app_state_sync", None)
            if callable(parse_state_sync):
                state_batches = parse_state_sync(payload)
                if state_batches:
                    contacts = await IngestService.apply_app_state_sync(
                        session, tenant_id, channel, state_batches
                    )
                    logger.info(
                        "whatsapp.contacts_synced",
                        extra={
                            "tenant_id": str(tenant_id),
                            "channel": channel,
                            "contacts": contacts,
                        },
                    )
            # What the merchant typed in the app on the phone. Without this the agent never sees
            # the human reply and answers the same customer a second time.
            parse_app_echoes = getattr(adapter, "parse_app_echoes", None)
            if callable(parse_app_echoes):
                app_echoes = parse_app_echoes(payload)
                if app_echoes:
                    accepted += await IngestService.apply_app_echoes(
                        session, tenant_id, channel, app_echoes
                    )
            # A message Meta could not hand over (131060): explainable, not a broken channel.
            parse_unsupported = getattr(adapter, "parse_unsupported_notices", None)
            if callable(parse_unsupported):
                await IngestService.apply_unsupported_notices(
                    session, tenant_id, channel, parse_unsupported(payload)
                )
            # An edited message: Meta sends the mid and the new text. The old body is kept in
            # provider_metadata so the thread can show that it changed.
            parse_edits = getattr(adapter, "parse_edits", None)
            if callable(parse_edits):
                accepted += await IngestService.apply_edits(
                    session, tenant_id, channel, parse_edits(payload)
                )
            # Thread control (messaging_handovers): a human took the thread, or handed it
            # back. Without this the agent kept replying after a person took over.
            parse_handovers = getattr(adapter, "parse_handovers", None)
            if callable(parse_handovers):
                for handover in parse_handovers(payload):
                    await IngestService.apply_handover(session, tenant_id, channel, handover)
            # A template's review state changed. The event is only a signal: our copy is brought
            # up to date from Meta itself, never written from what the event says, so a forged or
            # stale event cannot approve anything.
            has_template_news = getattr(adapter, "has_template_status_change", None)
            if callable(has_template_news) and has_template_news(payload):
                from app.modules.conversations.templates import TemplateService

                credentials = await _channel_credentials(session, tenant_id, channel)
                if credentials and credentials.get("access_token"):
                    # Its own savepoint: Meta being slow or down must not roll back the messages
                    # ingested above. The periodic sweep catches up whatever this misses.
                    try:
                        async with session.begin_nested():
                            await TemplateService.sync_from_meta(
                                session, tenant_id, credentials=credentials
                            )
                    except Exception as exc:  # noqa: BLE001 - the sweep retries within 15 minutes
                        logger.warning(
                            "webhook.template_resync_failed tenant=%s", tenant_id, exc_info=True
                        )
                        await _record_template_resync(
                            session, tenant_id, channel, error=type(exc).__name__
                        )
                    else:
                        await _record_template_resync(session, tenant_id, channel, error=None)
            # Meta warning, then blocking, the Page's messaging: `messaging_policy_enforcement`.
            # Nothing read this field before, so a Page Meta had already blocked kept looking
            # healthy and the agent kept writing replies that could not be delivered.
            parse_policy = getattr(adapter, "parse_policy_events", None)
            if callable(parse_policy):
                policy_events = parse_policy(payload)
                if policy_events:
                    await _apply_policy_events(session, tenant_id, channel, policy_events)
            # Meta saying the ACCOUNT is limited or banned, or that its sending limit moved. The
            # events are signed, and the only thing done with them is to tighten the channel's
            # status or note a number: nothing here lets an event loosen anything.
            parse_signals = getattr(adapter, "parse_account_signals", None)
            if callable(parse_signals):
                signals = parse_signals(payload)
                if signals:
                    await _apply_account_signals(session, tenant_id, channel, signals)
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
        await IngestService._record_channel_failure(session, event_id, exc)

    @staticmethod
    async def _record_channel_failure(
        session: AsyncSession, event_id: uuid.UUID, exc: Exception
    ) -> None:
        """Count the failure on the channel it belongs to, so the health surface can see it.

        ``consecutive_failures`` used to be written as 0 and nothing else, so no channel could ever
        turn degraded because its deliveries kept failing. Never raises: this runs inside the
        quarantine path, whose own job (keeping the row) must not be lost to bookkeeping.
        """
        try:
            from app.core.log_redaction import redact
            from app.core.meta_diagnostics import record_channel_issue

            row = (
                await session.execute(
                    select(
                        WebhookEvent.provider,
                        WebhookEvent.tenant_id,
                        WebhookEvent.processing_status,
                    ).where(WebhookEvent.id == event_id)
                )
            ).first()
            if row is None or row.tenant_id is None:
                return
            if getattr(row, "processing_status", None) == "dead":
                # M6: the failure that spent the retry budget is a customer message that will
                # never be answered. The operator hears about it now, not from the customer.
                from app.core.ops_alerts import fire_and_forget

                fire_and_forget(
                    "webhook dead-lettered", str(row.provider), detail=type(exc).__name__
                )
            integration = (
                await session.execute(
                    select(Integration).where(
                        Integration.tenant_id == row.tenant_id,
                        Integration.provider == row.provider,
                        Integration.kind == "channel",
                        Integration.status.in_(("active", "connected")),
                    )
                )
            ).scalar_one_or_none()
            if integration is not None:
                health = dict(integration.webhook_health or {})
                health["consecutive_failures"] = int(health.get("consecutive_failures") or 0) + 1
                health["last_error"] = redact(str(exc))[:300]
                health["last_failure_at"] = datetime.now(UTC).isoformat()
                integration.webhook_health = health
            await record_channel_issue(
                "webhook.processing_failed",
                channel=row.provider,
                tenant_id=row.tenant_id,
                details={"event_id": str(event_id), "error": type(exc).__name__},
            )
        except Exception:  # noqa: BLE001 - bookkeeping must not undo the quarantine
            logger.warning("webhook.failure_bookkeeping_failed event=%s", event_id, exc_info=True)

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

    #: How long a looked-up name (or the fact that Meta would not give one) is remembered, so a
    #: chatty customer costs one Graph call, not one per message.
    _PROFILE_TTL_SECONDS = 24 * 60 * 60
    _NO_PROFILE_TTL_SECONDS = 60 * 60

    @classmethod
    async def fill_customer_names(
        cls,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        adapter,
        channel: str,
        messages: list,
    ) -> None:
        """Give a nameless sender their name from the provider, once. Best effort, never raises.

        Only for adapters that can look a person up (``fetch_profile``) and only for a sender the
        webhook did not already name. The lookup is cached, including a refusal for a shorter
        time, so neither a busy customer nor a Page Meta will not answer for turns every message
        into a Graph call. A failure of any kind leaves the message to be ingested as before.
        """
        fetch = getattr(adapter, "fetch_profile", None)
        if not callable(fetch):
            return
        wanted = list(
            dict.fromkeys(
                m.customer_ref
                for m in messages
                if m.customer_ref and not getattr(m, "customer_name", None)
            )
        )
        if not wanted:
            return
        try:
            from app.core.redis import get_redis_or_none

            redis = get_redis_or_none()
            credentials = None
            for ref in wanted:
                key = f"profile:{channel}:{tenant_id}:{ref}"
                cached = None
                if redis is not None:
                    try:
                        cached = await redis.get(key)
                    except Exception:  # noqa: BLE001 - the cache is a courtesy
                        cached = None
                if cached is not None:
                    name = cached.decode() if isinstance(cached, bytes) else str(cached)
                else:
                    if credentials is None:
                        credentials = await _channel_credentials(session, tenant_id, channel) or {}
                    profile = await fetch(credentials, ref) if credentials else None
                    name = (profile or {}).get("name", "")
                    if redis is not None:
                        try:
                            await redis.set(
                                key,
                                name,
                                ex=cls._PROFILE_TTL_SECONDS
                                if name
                                else cls._NO_PROFILE_TTL_SECONDS,
                            )
                        except Exception:  # noqa: BLE001
                            pass
                if name:
                    for message in messages:
                        if message.customer_ref == ref and not message.customer_name:
                            message.customer_name = name
        except Exception:  # noqa: BLE001 - a name is never worth losing a received message
            logger.warning("ingest.customer_name_lookup_failed channel=%s", channel, exc_info=True)

    #: The referral fields worth showing, and the longest each may be. Meta's own keys; anything
    #: else in the object is dropped rather than passed through.
    _REFERRAL_FIELDS = ("source", "type", "ref", "ad_id", "ref_source", "headline", "ctwa_clid")

    @classmethod
    def _referral_details(cls, message) -> dict | None:
        """The Click-to-Messenger / Click-to-Direct referral, as a small checked dict.

        The adapters keep it under ``raw["_messenger"]`` (Messenger) or ``raw["_ig"]`` (Instagram).
        Before this, the only thing kept was a bare ``from_ad`` flag, so the agent could tell the
        conversation started from an ad but not which one — the campaign, the ad id and the
        headline Meta sent were thrown away.
        """
        raw = message.raw if isinstance(message.raw, dict) else {}
        for key in ("_messenger", "_ig"):
            extra = raw.get(key)
            if not isinstance(extra, dict):
                continue
            referral = extra.get("referral")
            if not isinstance(referral, dict):
                continue
            kept = {}
            for name in cls._REFERRAL_FIELDS:
                value = referral.get(name)
                if isinstance(value, str) and value.strip():
                    kept[name] = value.strip()[:255]
            if kept:
                return kept
        return None

    @staticmethod
    def _came_from_ad(message) -> bool:
        """True when this inbound message carries a Click-to-Messenger / Click-to-Direct referral.

        The adapters keep the provider's referral under ``raw["_messenger"]`` (Messenger) or
        ``raw["_ig"]`` (Instagram); an ad shows as ``source == "ADS"`` or as an ``ad_id``.
        """
        raw = message.raw if isinstance(message.raw, dict) else {}
        for key in ("_messenger", "_ig"):
            extra = raw.get(key)
            if not isinstance(extra, dict):
                continue
            referral = extra.get("referral")
            if isinstance(referral, dict) and (
                str(referral.get("source") or "").upper() == "ADS" or referral.get("ad_id")
            ):
                return True
        return False

    @staticmethod
    async def apply_read_watermarks(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str, reads: list[dict]
    ) -> None:
        """Mark a customer's outbound messages ``read`` up to the provider's watermark.

        A Messenger read receipt carries only a time (epoch milliseconds): everything sent before
        it was read. Only OUR outbound rows in THIS customer's conversation on THIS channel that
        are already sent or delivered are advanced, so a receipt can never regress a row, touch
        another customer's thread, or mark a message that never left.
        """
        from app.modules.conversations.models import Message

        for read in reads:
            ref = str(read.get("customer_ref") or "").strip()
            try:
                watermark_ms = int(read.get("watermark"))
            except (TypeError, ValueError):
                continue
            if not ref:
                continue
            cutoff = datetime.fromtimestamp(watermark_ms / 1000.0, tz=UTC)
            # The customer's conversation is found through their channel identity with raw SQL,
            # not the customers models: the conversations module must not grow a new import edge.
            conversation_ids = (
                (
                    await session.execute(
                        text(
                            "SELECT c.id FROM conversations c "
                            "JOIN customer_identities ci ON ci.customer_id = c.customer_id "
                            "AND ci.tenant_id = c.tenant_id "
                            "WHERE c.tenant_id = :tenant AND c.channel = :channel "
                            "AND ci.channel = :channel AND ci.external_id = :ref"
                        ),
                        {"tenant": tenant_id, "channel": channel, "ref": ref},
                    )
                )
                .scalars()
                .all()
            )
            if not conversation_ids:
                continue
            await session.execute(
                sa_update(Message)
                .where(
                    Message.tenant_id == tenant_id,
                    Message.conversation_id.in_(conversation_ids),
                    Message.direction == "outbound",
                    Message.status.in_(("sent", "delivered")),
                    Message.created_at <= cutoff,
                )
                .values(status="read")
            )


async def _apply_account_signals(
    session, tenant_id: uuid.UUID, channel: str, signals: list[dict]
) -> None:
    """Act on Meta's account-health news: a restriction restricts the channel, a limit is noted.

    Until now nothing ever set ``restricted``, so a banned WhatsApp account looked healthy while
    every send failed. A restricting event moves an active channel to ``restricted`` (the
    lifecycle already allows it) and writes the reason into ``webhook_health`` where
    ``check_integrations`` and the channel diagnostics read it. It never moves a channel the owner
    already disconnected or Meta already logged out, and it never moves one BACK to active: only
    reconnecting does that, because a quiet period proves nothing about the restriction ending.

    A limit change is informational and stays out of the failure counters.

    Best-effort by contract, like the template mark: the delivery is already accepted.
    """
    try:
        integration = (
            await session.execute(
                select(Integration)
                .where(
                    Integration.tenant_id == tenant_id,
                    Integration.provider == channel,
                    Integration.kind == "channel",
                )
                .order_by(
                    case((Integration.status.in_(("active", "connected")), 0), else_=1),
                    Integration.id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if integration is None:
            return
        health = dict(integration.webhook_health or {})
        now = datetime.now(UTC).isoformat()
        for signal in signals:
            if signal.get("kind") == "offboarded":
                # The merchant removed our app from the account, or Meta took it off. The channel
                # cannot send, so it must not look connected: `disconnected` stops the sender and
                # tells the owner to link again, and the reason is kept for the screen.
                health["partner_removed"] = {
                    "event": signal.get("event") or "",
                    "reason": signal.get("reason") or "",
                    "initiated_by": signal.get("initiated_by") or "",
                    "waba_id": signal.get("waba_id") or "",
                    "at": now,
                }
                if integration.status in ("active", "connected", "restricted", "reauth_required"):
                    integration.status = "disconnected"
            elif signal.get("kind") == "reconnected":
                # Coming back is not proof the number is usable: it has to be verified again, so
                # the channel waits for a connect instead of resuming sends on a stale token.
                health["partner_reconnected"] = {
                    "event": signal.get("event") or "",
                    "waba_id": signal.get("waba_id") or "",
                    "at": now,
                }
                if integration.status == "disconnected":
                    integration.status = "reauth_required"
            elif signal.get("kind") == "restriction":
                health["account_restriction"] = {
                    "event": signal.get("event") or "",
                    "detail": signal.get("detail") or "",
                    "at": now,
                }
                if integration.status in ("active", "connected"):
                    integration.status = "restricted"
            elif signal.get("kind") == "limit":
                health["messaging_limit"] = {
                    "event": signal.get("event") or "",
                    "limit": signal.get("limit") or "",
                    "at": now,
                }
        integration.webhook_health = health
        await session.flush()
    except Exception:  # noqa: BLE001 - the delivery is accepted; the mark is best-effort
        logger.warning(
            "ingest.account_signal_failed tenant=%s channel=%s", tenant_id, channel, exc_info=True
        )


async def _apply_policy_events(
    session, tenant_id: uuid.UUID, channel: str, events: list[dict]
) -> None:
    """Record Meta's messaging-policy news as operational state and as a notification.

    A BLOCK is not a guess: Meta said the Page may not message, so the channel is moved to
    ``restricted`` (a lifecycle state that already exists) and every surface that reads
    ``check_integrations`` shows it. A WARN is recorded and nothing else: it is a warning, and
    restricting a working channel over one would cost the owner the channel for nothing. Neither
    ever moves a channel BACK to active — only reconnecting does that, because a quiet period
    proves nothing.

    The notification row is written through the same Page activity feed the rest of the Page's
    news uses, with the event's own timestamp in the dedup key, so a delivery Meta retries updates
    the row instead of nagging the owner twice.
    """
    from app.modules.conversations.page_activity_service import PageActivityService

    try:
        integration = (
            await session.execute(
                select(Integration)
                .where(
                    Integration.tenant_id == tenant_id,
                    Integration.provider == channel,
                    Integration.kind == "channel",
                )
                .order_by(
                    case((Integration.status.in_(("active", "connected")), 0), else_=1),
                    Integration.id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        health = dict((integration.webhook_health if integration else None) or {})
        now = datetime.now(UTC)
        for event in events:
            action = str(event.get("action") or "").upper()
            at = _epoch_or_now(event.get("at"), now)
            health["messaging_policy"] = {
                "action": action,
                "reason": event.get("reason") or "",
                "expires_at": event.get("expires_at"),
                "at": at.isoformat(),
            }
            if integration is not None and action == "BLOCK":
                if integration.status in ("active", "connected"):
                    integration.status = "restricted"
            await PageActivityService.record(
                session,
                tenant_id,
                channel=channel,
                kind="policy",
                object_id=str(event.get("page_id") or channel),
                occurred_at=at,
                summary=(
                    f"ميتا أوقفت مراسلة الصفحة: {event.get('reason') or action}"
                    if action == "BLOCK"
                    else f"تحذير من ميتا على مراسلة الصفحة: {event.get('reason') or action}"
                ),
            )
        if integration is not None:
            integration.webhook_health = health
            await session.flush()
    except Exception:  # noqa: BLE001 - the delivery is accepted; the mark is best-effort
        logger.warning(
            "ingest.policy_event_failed tenant=%s channel=%s", tenant_id, channel, exc_info=True
        )


def _epoch_or_now(value: object, fallback: datetime) -> datetime:
    """Meta's epoch seconds, or the current time when the event carries no usable stamp."""
    try:
        seconds = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if seconds <= 0:
        return fallback
    return datetime.fromtimestamp(seconds, tz=UTC)


async def _record_template_resync(
    session, tenant_id: uuid.UUID, channel: str, *, error: str | None
) -> None:
    """Leave a mark on the channel when its template copy could not be refreshed.

    A failed resync used to be a log line and nothing else: the store's templates stayed at
    whatever Meta last said and the only trace was a warning nobody reads, so an owner staring at
    a template stuck on "pending" had nothing to look at. The mark rides `webhook_health`, which
    `check_integrations` already reports, and only a resync that SUCCEEDS clears it — the next
    unrelated delivery arriving is not evidence that templates are fresh.

    Best-effort by contract: the messages above are the job, and a mark that cannot be written
    must not turn a delivered message into a retried one.
    """
    try:
        integration = (
            await session.execute(
                select(Integration)
                .where(
                    Integration.tenant_id == tenant_id,
                    Integration.provider == channel,
                    Integration.kind == "channel",
                )
                .order_by(
                    case((Integration.status.in_(("active", "connected")), 0), else_=1),
                    Integration.id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if integration is None:
            return
        health = dict(integration.webhook_health or {})
        if error is None:
            if "template_resync_error" not in health:
                return
            health.pop("template_resync_error", None)
            health.pop("template_resync_failed_at", None)
            health["template_resync_ok_at"] = datetime.now(UTC).isoformat()
        else:
            health["template_resync_error"] = error[:120]
            health["template_resync_failed_at"] = datetime.now(UTC).isoformat()
        integration.webhook_health = health
        await session.flush()
    except Exception:  # noqa: BLE001 - a mark is a courtesy, the ingested messages are the job
        logger.warning(
            "ingest.template_resync_mark_failed tenant=%s channel=%s",
            tenant_id,
            channel,
            exc_info=True,
        )

    # ------------------------------------------------ §24 ingress lifecycle --
