"""Message worker: consumes message events from the outbox relay.

Routing by payload["event_type"]:
- message.received → conversation pipeline (AI hook, serialized by lease)
- message.outbound → deliver via the channel adapter

Outbound state machine (spec §129/§130) — three phases so every state is
DURABLE before the next one starts:

    Phase 1 (TX)  claim:   QUEUED → SENDING, committed BEFORE the provider
                           call so a crash mid-request leaves an observable
                           in-flight state (never a silent re-queue).
    Phase 2 (no TX) send:  the provider call; no DB transaction is held
                           across the network hop.
    Phase 3 (TX)  outcome: the §127 ProcessedEvent inbox row commits in the
                           SAME transaction as the terminal status, making
                           at-least-once delivery exactly-once for the effect.

    QUEUED → SENDING → SENT → DELIVERED → READ
                    ├→ UNKNOWN   (no provider result: timeout/connection lost
                    │             — NEVER blindly retried; the retry dead-
                    │             letters for reconciliation, §130)
                    └→ FAILED    (definitive rejection — DLQ)

Reconciliation guards (§130): a message already in UNKNOWN or stuck in
SENDING is never resent — the event dead-letters with reason so the DLQ
inspect command (the manual reconciliation tool) and delivery webhooks
decide the outcome.

All received-path processing runs under the conversation lease (§126) so two
processors can never mutate one conversation concurrently.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, bind_tenant
from app.core.errors import RateLimitExceededError, ValidationError
from app.core.events.bus import Event
from app.core.events.schemas import EventEnvelope, deserialize_event
from app.core.lease import ConversationBusy, conversation_lease
from app.modules.ai.gateway import (
    AIBudgetFallbackRequested,
    reserve_budget,
    settle_reservation,
)
from app.modules.ai.usage import PLATFORM_BUCKET, record_usage
from app.modules.conversations.gateway.base import (
    ChannelAdapter,
    OutboundMessage,
    ProviderCredentials,
)
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.models import Attachment, Conversation, Message
from app.modules.conversations.policy import MessagingPolicyService
from app.modules.conversations.voice import STTProvider, VoiceService, stt_cost_estimate
from app.modules.customers.models import CustomerIdentity
from app.modules.platform.models import DeliveryAttempt, Integration, ProcessedEvent
from app.workers.base import (
    PermanentError,
    RetryableError,
    StreamWorker,
    defer_unless_tenant_allows,
)

logger = logging.getLogger(__name__)

_UNKNOWN_REASON = "unknown delivery state — requires reconciliation"
_STUCK_SENDING_REASON = "stuck in sending — requires reconciliation"


async def transcribe_inbound_voice(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    message_id: uuid.UUID,
    stt_provider: STTProvider | None = None,
    language: str | None = None,
) -> str | None:
    """§35: transcribe the pending audio attachment on an inbound message.

    Lives in the worker layer, not in `conversations`: it is the one place that
    has to see both the attachment table and the AI budget gate, and
    `conversations -> ai` closes a module import cycle (§36 rule set below is
    otherwise unchanged).

    - Nothing pending (text message, image, already transcribed) returns without
      touching the provider — the idempotency is the status column.
    - Budget is RESERVED before the call, never checked-and-hoped: transcription
      costs money, and a preflight lets concurrent voice notes overshoot the cap.
    - A block is not an error. The customer's note is already stored and stays
      delivered; raising here would retry and dead-letter a healthy ingest.
    """
    attachment = (
        await session.execute(
            select(Attachment).where(
                Attachment.tenant_id == tenant_id,
                Attachment.message_id == message_id,
                Attachment.transcription_status == "pending",
            )
        )
    ).scalar_one_or_none()
    if attachment is None:
        return None

    cost = stt_cost_estimate(attachment)
    try:
        reservation_id = await reserve_budget(session, tenant_id, estimated_cost=cost)
    except (RateLimitExceededError, AIBudgetFallbackRequested) as exc:
        attachment.transcription_status = "failed"
        await session.flush()
        logger.warning(
            "voice.stt_budget_blocked tenant=%s attachment=%s reason=%s",
            tenant_id,
            attachment.id,
            exc,
        )
        return None

    try:
        result = await VoiceService.transcribe(
            session,
            tenant_id,
            attachment_id=attachment.id,
            stt_provider=stt_provider,
            language=language,
        )
    finally:
        await settle_reservation(session, reservation_id)

    if result.text:
        # §42: booked whether or not the provider answered, so the cap sees the
        # money a failed call may still have consumed.
        # §47: the estimate is a Decimal and `ai_usage.cost` is Numeric(18,8);
        # `float(cost)` rounded the sub-cent places the column exists to hold.
        # PLATFORM_BUCKET, not an omitted agent_id: this spend happens BEFORE
        # `maybe_auto_reply` picks an agent (and even when the tenant has none, or
        # no AI entitlement), so attributing it to an agent would be a fiction —
        # while leaving it NULL gives the rollup a bucket its unique key cannot
        # arbitrate, which fragments it into one row per voice note.
        await record_usage(session, tenant_id, agent_id=PLATFORM_BUCKET, cost=cost)
        return result.text
    return None


@dataclass(slots=True)
class _SendPlan:
    """Everything phase 2 needs, snapshotted while phase 1 still holds the TX."""

    adapter: ChannelAdapter
    credentials: ProviderCredentials
    outbound: OutboundMessage
    set_channel_message_id: bool  # webchat messages have no provider id


class MessageWorker(StreamWorker):
    stream = "message.events"
    group = "message-workers"
    name = "message-worker"
    # §127: message_worker has its own finer-grained ProcessedEvent check
    # (per delivery phase), so skip the generic check in StreamWorker._process.
    _skip_generic_idempotency = True

    async def handle(self, event: Event) -> None:
        # Read the event through the §19 envelope's read half (finding 2): the
        # type and tenant claim come from the envelope, never hand-parsed from
        # payload/meta. A non-envelope entry fails CLOSED — dropped rather than
        # processed without a tenant.
        try:
            envelope = deserialize_event(event)
        except (ValidationError, KeyError, TypeError, ValueError):
            logger.warning("message.event_without_envelope id=%s", event.id)
            return

        if envelope.type == "message.received":
            await self._on_received(envelope)
        elif envelope.type == "message.outbound":
            await self._deliver(envelope)
        else:
            logger.debug("message.event_ignored type=%s", envelope.type)

    def _dedupe_id(self, envelope: EventEnvelope) -> str:
        """Stable consumer-inbox key: the outbox row id survives crash-reclaim
        re-publishes; the per-XADD bus uuid would make replays look new."""
        return str(envelope.meta.get("outbox_id") or envelope.id)

    async def _on_received(self, envelope: EventEnvelope) -> None:
        conversation_id = envelope.payload.get("conversation_id")
        logger.info("message.received conversation=%s", conversation_id)
        if not conversation_id:
            return
        tenant_id = envelope.tenant_id
        try:
            from app.modules.ai.hooks import maybe_auto_reply

            # Phase 1: Deduplication preflight check (§127)
            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    prior = (
                        await session.execute(
                            select(ProcessedEvent.id).where(
                                ProcessedEvent.consumer_name == self.name,
                                ProcessedEvent.event_id == uuid.UUID(self._dedupe_id(envelope)),
                            )
                        )
                    ).scalar_one_or_none()
                    if prior is not None:
                        logger.info("received.event_already_processed id=%s", envelope.id)
                        return

            # Phase 2: Transcribe inbound voice note before answering (§35, §126)
            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    async with conversation_lease(session, uuid.UUID(conversation_id)):
                        await transcribe_inbound_voice(
                            session, tenant_id, message_id=envelope.aggregate_id
                        )

            # Phase 3: AI Auto-reply (runs under conversation_lease internally)
            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    await maybe_auto_reply(session, tenant_id, uuid.UUID(conversation_id))

            # Phase 4: Commit consumer-inbox ProcessedEvent (§127)
            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    try:
                        async with session.begin_nested():
                            session.add(
                                ProcessedEvent(
                                    consumer_name=self.name,
                                    event_id=uuid.UUID(self._dedupe_id(envelope)),
                                    status="done",
                                )
                            )
                            await session.flush()
                    except IntegrityError:
                        logger.info("received.event_already_processed id=%s", envelope.id)
                        return
        except ImportError:
            logger.debug("ai.hooks not installed — skipping auto-reply")
        # NOTE: no broad swallow here. An AI/provider failure must roll the
        # ProcessedEvent marker back and propagate so the worker runtime
        # retries with backoff (and finally dead-letters). Swallowing acked
        # the event while losing the reply forever.
        except ConversationBusy:
            # Retryable by contract (lease.py): re-raise so the event is
            # requeued instead of being marked processed with no reply.
            raise

    # ------------------------------------------------------- outbound ----

    async def _deliver(self, envelope: EventEnvelope) -> None:
        message_id_raw = envelope.payload.get("message_id")
        if not message_id_raw:
            logger.warning("outbound.event_missing_message_id id=%s", envelope.id)
            return
        message_id = uuid.UUID(str(message_id_raw))
        tenant_id = envelope.tenant_id

        # Phase 1 — claim (§129): QUEUED -> SENDING committed before the
        # provider call, so a crash mid-request leaves an observable
        # in-flight state and a retry dead-letters instead of resending.
        plan = None
        permanent_reason: str | None = None
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                # §48 — checked BEFORE claiming, so a suspended tenant's message
                # stays QUEUED rather than being sent, and is deferred rather
                # than dead-lettered: it resumes if the tenant is reactivated.
                await defer_unless_tenant_allows(session, tenant_id, "allows_channels")
                try:
                    plan = await self._deliver_one(session, tenant_id, message_id)
                except PermanentError as exc:
                    # The failed/sending status write must SURVIVE: flush it
                    # as part of this commit, dead-letter after the commit.
                    # (Raising inside the tx used to roll the write back,
                    # leaving the message queued forever.)
                    await session.flush()
                    permanent_reason = str(exc)
        if permanent_reason is not None:
            raise PermanentError(permanent_reason)
        if plan is None:
            return

        # Phase 2 — the provider call (no transaction held across the hop).
        status, provider_id, error = await self._send(plan)

        # Phase 3 — outcome (§127): the ProcessedEvent consumer-inbox row
        # commits in the SAME transaction as the terminal status, so a
        # replayed event can never apply the effect twice; a replay whose
        # twin already finished dies on the unique constraint inside the
        # savepoint and returns silently.
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                try:
                    async with session.begin_nested():
                        session.add(
                            ProcessedEvent(
                                consumer_name=self.name,
                                event_id=uuid.UUID(self._dedupe_id(envelope)),
                                status="done",
                            )
                        )
                        await session.flush()
                except IntegrityError:
                    logger.info("outbound.event_already_processed id=%s", envelope.id)
                    return
                await self._apply_outcome(
                    session, tenant_id, message_id, plan, status, provider_id, error
                )

        if status == "failed":
            raise PermanentError(error or "delivery failed")
        if status == "unknown":
            # Retryable on purpose: the runtime retries, but the retry hits
            # the §130 reconciliation guard in _deliver_one and dead-letters
            # — blind resending is forbidden (§129).
            raise RetryableError(error or "unknown delivery outcome")

    async def _deliver_one(
        self, session, tenant_id: uuid.UUID, message_id: uuid.UUID
    ) -> _SendPlan | None:
        """Phase 1: guards + claim. Returns the send plan, or None to skip.

        Raises PermanentError for states that must dead-letter immediately:
        reconciliation-required (§130) and structurally undeliverable messages.
        """
        message = (
            await session.execute(
                select(Message).where(Message.tenant_id == tenant_id, Message.id == message_id)
            )
        ).scalar_one_or_none()
        if message is None:
            return None
        # §130 reconciliation guards: a previous attempt ended in a state
        # whose provider outcome is unobservable — never resend; dead-letter
        # for manual reconciliation (delivery webhooks may still flip the
        # message status afterwards).
        if message.status in ("unknown", "sending"):
            reason = _UNKNOWN_REASON if message.status == "unknown" else _STUCK_SENDING_REASON
            logger.warning(
                "outbound.requires_reconciliation id=%s status=%s",
                message.id,
                message.status,
            )
            raise PermanentError(reason)
        # Idempotent re-delivery guard: never resend something already in
        # flight or delivered (dedupe on republish/replay).
        if message.status != "queued":
            logger.info("outbound.skip_not_queued id=%s status=%s", message.id, message.status)
            return None

        conversation = (
            await session.execute(
                select(Conversation).where(
                    Conversation.tenant_id == tenant_id,
                    Conversation.id == message.conversation_id,
                )
            )
        ).scalar_one()

        # §30: re-evaluate the channel policy at SEND time, not only when the
        # message was created. A reply queued during a backlog can easily be
        # delivered after the 24h window has closed, and the provider would
        # reject it silently — the sender would never know the customer was not
        # reached.
        decision = await MessagingPolicyService.evaluate_for_conversation(
            session, tenant_id, conversation, template_name=message.template_name
        )
        if not decision.allowed:
            message.status = "failed"
            message.error = f"blocked by messaging policy: {decision.reason}"
            raise PermanentError(decision.reason)

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
            raise PermanentError("no channel identity for customer")

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
            raise PermanentError(f"channel not configured: {conversation.channel}")

        # Claim: ATOMIC conditional update — two concurrent deliveries of the
        # same event (at-least-once redelivery / duplicate republish) can no
        # longer both pass a read-then-write guard and double-send.
        claim = await session.execute(
            sa_update(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.id == message.id,
                Message.status == "queued",
            )
            .values(status="sending")
        )
        if claim.rowcount == 0:
            logger.info("outbound.claim_lost id=%s — another worker claimed it", message.id)
            return None
        await session.flush()
        # §68: integration credentials are encrypted at rest — decrypt lazily,
        # only after the claim is won (a lost claim must not audit a read).
        # The decryption writes ONE "integration.credentials.read" audit row
        # per integration per event.
        credentials_config: dict = {}
        if integration is not None:
            from app.modules.platform.service import IntegrationCredentialsService

            credentials_config = await IntegrationCredentialsService.decrypt(session, integration)
        return _SendPlan(
            adapter=adapter,
            credentials=ProviderCredentials(config=credentials_config),
            outbound=OutboundMessage(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                message_id=message.id,
                customer_ref=identity.external_id,
                body=message.body,
                media_url=message.media_url,
                # §31: previously never passed, so an approved template could
                # not actually be delivered even when one was required.
                template_name=message.template_name,
                template_vars=message.template_vars or {},
            ),
            set_channel_message_id=conversation.channel != "webchat",
        )

    async def _send(self, plan: _SendPlan) -> tuple[str, str | None, str | None]:
        """Phase 2: call the adapter; classify, never propagate blindly.

        Returns (status, provider_id, error).
        """
        try:
            provider_id = await plan.adapter.send(plan.credentials, plan.outbound)
        except Exception as exc:  # noqa: BLE001 — classified below
            logger.exception("outbound.send_failed message=%s", plan.outbound.message_id)
            return _classify_send_failure(exc), None, str(exc)[:500]
        return "sent", provider_id, None

    async def _apply_outcome(
        self,
        session,
        tenant_id: uuid.UUID,
        message_id: uuid.UUID,
        plan: _SendPlan,
        status: str,
        provider_id: str | None,
        error: str | None,
    ) -> None:
        """Phase 3: terminal status, committed atomically with ProcessedEvent."""
        message = (
            await session.execute(
                select(Message).where(Message.tenant_id == tenant_id, Message.id == message_id)
            )
        ).scalar_one_or_none()
        if message is None:
            return
        message.status = status
        message.error = error
        if status == "sent" and plan.set_channel_message_id:
            if message.channel_message_id is None:
                message.channel_message_id = provider_id
        # §130: one DeliveryAttempt row per provider send attempt, committed in
        # the SAME transaction as the status flip — the audit cannot exist
        # without its outcome. The provider's id for this event is the message
        # id the adapter returned (provider_timestamp stays NULL here: only a
        # later delivery receipt knows when the provider saw the message).
        session.add(
            DeliveryAttempt(
                tenant_id=tenant_id,
                message_id=message.id,
                provider=plan.adapter.name,
                # column contract: sending | sent | unknown | failed
                outcome=status,
                request_payload={
                    "customer_ref": plan.outbound.customer_ref,
                    "template_name": plan.outbound.template_name,
                    "has_media": bool(plan.outbound.media_url),
                },
                provider_event_id=provider_id,
                error=error,
            )
        )
        if status == "sent":
            # §53/§171: canonical usage event, recorded in the SAME transaction
            # as the SENT status flip — a replayed send skips this phase via the
            # ProcessedEvent marker, so no double metering.
            from decimal import Decimal

            from app.modules.billing.service import BillingService

            await BillingService.record_usage(
                session, tenant_id, feature="messages_outbound", quantity=Decimal("1")
            )
        await session.flush()


def _classify_send_failure(exc: Exception) -> str:
    """Map a provider call failure to UNKNOWN (result unknown) or FAILED
    (definitive rejection). Timeouts/connection errors mid-request are
    UNKNOWN — the request may have reached the provider. A definitive HTTP
    status rejection is FAILED — the provider answered and refused."""
    from httpx import HTTPError, HTTPStatusError, TimeoutException

    if isinstance(exc, TimeoutException):
        return "unknown"
    if isinstance(exc, HTTPStatusError):
        # HTTPStatusError subclasses HTTPError — check it FIRST, else a
        # definitive 4xx/5xx dead-letters as "unknown" needing reconciliation.
        return "failed"
    if isinstance(exc, HTTPError):
        return "unknown"
    text = str(exc).lower()
    if any(marker in text for marker in ("timeout", "timed out", "connection", "unreachable")):
        return "unknown"
    return "failed"
