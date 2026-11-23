"""Tell a WhatsApp or Instagram customer we read their message, and that we are typing.

On WhatsApp both ride ONE Cloud API request (``status: read`` + ``typing_indicator``).
On Instagram they are two separate sender actions (``mark_seen`` and ``typing_on``), and
they need no message id: Instagram marks the whole thread. They are courtesies: a
failure here must never stop an agent from working, so the route reports it as
``sent: false`` instead of raising.

Rules, because a wrong signal is visible on the customer's phone:
* WhatsApp and Instagram only. Other channels have their own (or no) equivalent.
* Only about the customer's NEWEST inbound message, and only one that came from
  the provider (it needs the provider's own id).
* Only inside the customer-service window; outside it nothing can be answered.
* The "typing" part only while the agent is actually typing; opening a chat sends
  just the read receipt.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversations.gateway.base import ProviderCredentials
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.models import Message
from app.modules.conversations.policy import MessagingPolicyService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReadSignalResult:
    sent: bool
    # Why nothing was sent, in words the UI never has to show. None when sent.
    skipped: str | None = None


class ReadSignalService:
    @staticmethod
    async def latest_inbound_provider_id(
        session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> str | None:
        """The provider id of the customer's newest real message (a reaction is not one).

        "Newest" is decided the way the chat itself decides it: by our timestamp and,
        for messages stored in the same instant (one webhook batch), by the time the
        PROVIDER gives. A recent slice is enough; nothing older can be the newest.
        """
        from app.modules.conversations.routers.inbox import _provider_order

        rows = (
            (
                await session.execute(
                    select(Message)
                    .where(
                        Message.tenant_id == tenant_id,
                        Message.conversation_id == conversation_id,
                        Message.direction == "inbound",
                        Message.deleted.is_(False),
                        Message.content_type != "reaction",
                        Message.channel_message_id.is_not(None),
                    )
                    .order_by(Message.created_at.desc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return None
        return max(rows, key=_provider_order).channel_message_id

    @staticmethod
    async def send(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        conversation,
        *,
        typing: bool,
        load_channel_config: Callable[[], Awaitable[dict | None]] | None = None,
    ) -> ReadSignalResult:
        """``load_channel_config`` fetches the connected WhatsApp channel's ready-to-use settings
        (the caller owns that lookup, it lives in platform); None, or a lookup that finds nothing,
        means the shop has no WhatsApp connection.

        It is a loader and not a value so the credentials are read, and the read audited, only
        AFTER every check above that can stop the signal. A chat opened outside the 24h window
        must not leave a "credentials read" row behind."""
        if conversation.channel not in ("whatsapp", "instagram", "messenger"):
            return ReadSignalResult(False, "channel")
        if not MessagingPolicyService.evaluate(conversation).allowed:
            return ReadSignalResult(False, "window_closed")
        if conversation.channel in ("instagram", "messenger"):
            return await ReadSignalService._send_sender_action(
                session,
                tenant_id,
                conversation,
                channel=conversation.channel,
                typing=typing,
                load_channel_config=load_channel_config,
            )
        provider_id = await ReadSignalService.latest_inbound_provider_id(
            session, tenant_id, conversation.id
        )
        if not provider_id:
            return ReadSignalResult(False, "no_message")
        adapter = get_adapter("whatsapp")
        if adapter is None or not hasattr(adapter, "send_read_signal"):
            return ReadSignalResult(False, "unsupported")
        channel_config = await load_channel_config() if load_channel_config else None
        if channel_config is None:
            return ReadSignalResult(False, "not_connected")
        try:
            await adapter.send_read_signal(
                ProviderCredentials(config=channel_config), provider_id, typing=typing
            )
        except Exception as exc:  # noqa: BLE001 - a courtesy signal never blocks the agent
            logger.warning(
                "whatsapp.read_signal_failed conversation=%s err=%s", conversation.id, exc
            )
            return ReadSignalResult(False, "provider_error")
        return ReadSignalResult(True)

    @staticmethod
    async def _send_sender_action(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        conversation,
        *,
        channel: str,
        typing: bool,
        load_channel_config: Callable[[], Awaitable[dict | None]] | None,
    ) -> ReadSignalResult:
        """Instagram and Messenger: ``mark_seen`` when a chat is opened, ``typing_on`` while the
        agent writes. Both are the same Graph ``sender_action``, addressed to the customer's
        page-scoped id (what the thread is addressed by) rather than a message id, and still fire
        only when the customer has written something we received.
        """
        if not await ReadSignalService.latest_inbound_provider_id(
            session, tenant_id, conversation.id
        ):
            return ReadSignalResult(False, "no_message")
        adapter = get_adapter(channel)
        if adapter is None or not hasattr(adapter, "send_sender_action"):
            return ReadSignalResult(False, "unsupported")
        channel_config = await load_channel_config() if load_channel_config else None
        if channel_config is None:
            return ReadSignalResult(False, "not_connected")
        customer_ref = await ReadSignalService._customer_ref(session, tenant_id, conversation)
        if not customer_ref:
            return ReadSignalResult(False, "no_customer")
        credentials = ProviderCredentials(config=channel_config)
        try:
            await adapter.send_sender_action(credentials, customer_ref, "mark_seen")
            if typing:
                await adapter.send_sender_action(credentials, customer_ref, "typing_on")
        except Exception as exc:  # noqa: BLE001 - a courtesy signal never blocks the agent
            logger.warning(
                "%s.read_signal_failed conversation=%s err=%s", channel, conversation.id, exc
            )
            return ReadSignalResult(False, "provider_error")
        return ReadSignalResult(True)

    @staticmethod
    async def _customer_ref(
        session: AsyncSession, tenant_id: uuid.UUID, conversation
    ) -> str | None:
        """The scoped id this thread is addressed by, on the conversation's OWN channel.

        Instagram addresses a thread by the Instagram-scoped id and Messenger by the page-scoped
        id (PSID). Reading a fixed ``instagram`` identity for a Messenger thread finds no row, so
        ``mark_seen`` and ``typing_on`` silently never fired on Messenger at all.
        """
        from app.modules.conversations.customer_profile import customers

        channel = str(getattr(conversation, "channel", "") or "")
        if not channel:
            return None
        identity = await customers().channel_identity(
            session, tenant_id, conversation.customer_id, channel
        )
        row = identity.external_id if identity is not None else None
        return str(row) if row else None
