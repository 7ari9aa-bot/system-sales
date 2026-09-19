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
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal, bind_tenant
from app.core.events.bus import Event
from app.core.lease import conversation_lease
from app.modules.conversations.gateway.base import (
    ChannelAdapter,
    OutboundMessage,
    ProviderCredentials,
)
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.models import Conversation, Message
from app.modules.customers.models import CustomerIdentity
from app.modules.platform.models import Integration, ProcessedEvent
from app.workers.base import PermanentError, RetryableError, StreamWorker

logger = logging.getLogger(__name__)

_UNKNOWN_REASON = "unknown delivery state — requires reconciliation"
_STUCK_SENDING_REASON = "stuck in sending — requires reconciliation"


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
        if not conversation_id:
            return
        try:
            from app.modules.ai.hooks import maybe_auto_reply

            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_id)
                    try:
                        async with session.begin_nested():
                            session.add(
                                ProcessedEvent(
                                    consumer_name=self.name,
                                    event_id=uuid.UUID(str(event.id)),
                                    status="done",
                                )
                            )
                            await session.flush()
                    except IntegrityError:
                        logger.info("received.event_already_processed id=%s", event.id)
                        return
                    # §126: one state-mutating processor per conversation.
                    async with conversation_lease(session, uuid.UUID(conversation_id)):
                        await maybe_auto_reply(
                            session, tenant_id, uuid.UUID(conversation_id)
                        )
        except ImportError:
            logger.debug("ai.hooks not installed — skipping auto-reply")
        except Exception:  # noqa: BLE001 — AI failures must not kill the hot path
            logger.exception("ai.auto_reply_failed conversation=%s", conversation_id)

    # ------------------------------------------------------- outbound ----

    async def _deliver(self, event: Event, tenant_id: uuid.UUID) -> None:
        message_id_raw = event.payload.get("message_id")
        if not message_id_raw:
            logger.warning("outbound.event_missing_message_id id=%s", event.id)
            return
        message_id = uuid.UUID(str(message_id_raw))

        # Phase 1 — claim (§129): QUEUED -> SENDING committed before the
        # provider call, so a crash mid-request leaves an observable
        # in-flight state and a retry dead-letters instead of resending.
        plan = None
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                plan = await self._deliver_one(session, tenant_id, message_id)
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
                                event_id=uuid.UUID(event.id),
                                status="done",
                            )
                        )
                        await session.flush()
                except IntegrityError:
                    logger.info(
                        "outbound.event_already_processed id=%s", event.id
                    )
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
                select(Message).where(
                    Message.tenant_id == tenant_id, Message.id == message_id
                )
            )
        ).scalar_one_or_none()
        if message is None:
            return None
        # §130 reconciliation guards: a previous attempt ended in a state
        # whose provider outcome is unobservable — never resend; dead-letter
        # for manual reconciliation (delivery webhooks may still flip the
        # message status afterwards).
        if message.status in ("unknown", "sending"):
            reason = (
                _UNKNOWN_REASON
                if message.status == "unknown"
                else _STUCK_SENDING_REASON
            )
            logger.warning(
                "outbound.requires_reconciliation id=%s status=%s",
                message.id,
                message.status,
            )
            raise PermanentError(reason)
        # Idempotent re-delivery guard: never resend something already in
        # flight or delivered (dedupe on republish/replay).
        if message.status != "queued":
            logger.info(
                "outbound.skip_not_queued id=%s status=%s", message.id, message.status
            )
            return None

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

        # Claim: SENDING persists (committed by the caller's transaction)
        # before the provider call.
        message.status = "sending"
        await session.flush()
        return _SendPlan(
            adapter=adapter,
            credentials=ProviderCredentials(
                config=(integration.credentials if integration else {}) or {}
            ),
            outbound=OutboundMessage(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                message_id=message.id,
                customer_ref=identity.external_id,
                body=message.body,
                media_url=message.media_url,
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
            logger.exception(
                "outbound.send_failed message=%s", plan.outbound.message_id
            )
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
                select(Message).where(
                    Message.tenant_id == tenant_id, Message.id == message_id
                )
            )
        ).scalar_one_or_none()
        if message is None:
            return
        message.status = status
        message.error = error
        if status == "sent" and plan.set_channel_message_id:
            if message.channel_message_id is None:
                message.channel_message_id = provider_id
        await session.flush()


def _classify_send_failure(exc: Exception) -> str:
    """Map a provider call failure to UNKNOWN (result unknown) or FAILED
    (definitive rejection). Timeouts/connection errors mid-request are
    UNKNOWN — the request may have reached the provider."""
    from httpx import HTTPError, TimeoutException

    if isinstance(exc, TimeoutException | HTTPError):
        return "unknown"
    text = str(exc).lower()
    if any(
        marker in text
        for marker in ("timeout", "timed out", "connection", "unreachable")
    ):
        return "unknown"
    return "failed"
