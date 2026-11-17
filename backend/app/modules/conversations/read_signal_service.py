"""Tell a WhatsApp customer we read their message, and that we are typing.

Both ride ONE Cloud API request (``status: read`` + ``typing_indicator``). They are
courtesies: a failure here must never stop an agent from working, so the route
reports it as ``sent: false`` instead of raising.

Rules, because a wrong signal is visible on the customer's phone:
* WhatsApp only. Other channels have their own (or no) equivalent.
* Only about the customer's NEWEST inbound message, and only one that came from
  the provider (it needs the provider's own id).
* Only inside the customer-service window; outside it nothing can be answered.
* The "typing" part only while the agent is actually typing; opening a chat sends
  just the read receipt.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversations.gateway.base import ProviderCredentials
from app.modules.conversations.gateway.registry import get_adapter
from app.modules.conversations.models import Message
from app.modules.conversations.policy import MessagingPolicyService
from app.modules.platform.models import Integration

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
    ) -> ReadSignalResult:
        if conversation.channel != "whatsapp":
            return ReadSignalResult(False, "channel")
        if not MessagingPolicyService.evaluate(conversation).allowed:
            return ReadSignalResult(False, "window_closed")
        provider_id = await ReadSignalService.latest_inbound_provider_id(
            session, tenant_id, conversation.id
        )
        if not provider_id:
            return ReadSignalResult(False, "no_message")
        adapter = get_adapter("whatsapp")
        if adapter is None or not hasattr(adapter, "send_read_signal"):
            return ReadSignalResult(False, "unsupported")
        integration = (
            await session.execute(
                select(Integration).where(
                    Integration.tenant_id == tenant_id,
                    Integration.provider == "whatsapp",
                    Integration.kind == "channel",
                )
            )
        ).scalar_one_or_none()
        if integration is None:
            return ReadSignalResult(False, "not_connected")

        from app.modules.platform.service import IntegrationCredentialsService

        config = dict(integration.config or {})
        config.update(await IntegrationCredentialsService.decrypt(session, integration))
        try:
            await adapter.send_read_signal(
                ProviderCredentials(config=config), provider_id, typing=typing
            )
        except Exception as exc:  # noqa: BLE001 - a courtesy signal never blocks the agent
            logger.warning(
                "whatsapp.read_signal_failed conversation=%s err=%s", conversation.id, exc
            )
            return ReadSignalResult(False, "provider_error")
        return ReadSignalResult(True)
