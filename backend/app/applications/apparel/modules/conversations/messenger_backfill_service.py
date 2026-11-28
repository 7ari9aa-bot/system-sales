"""Put what the backfill read into the shop's own inbox.

The walk (``gateway/messenger_backfill.py``) only *reads* Meta. Without this module a store that
connects today still opens an empty inbox: the messages Meta returned are counted and thrown away.
Here they become real rows, and three properties matter more than anything else:

* **Idempotent.** Meta's message id is the key, so a retry, a second sweep or an overlapping run
  stores nothing twice. The reconciliation sweep depends on that.
* **Silent.** A backfilled message is history, not news: no ``message.received`` outbox event is
  written, so the Customer Agent never answers a four-day-old message, and the thread does not
  jump to the top of the queue with a fake unread badge.
* **Honest about time.** ``ConversationService.add_message`` anchors the 24-hour messaging window
  and the unread counter at *now*, which is wrong for history. Both are reset to what Meta itself
  reports (the message's ``created_time`` and the conversation's ``unread_count``) after the
  writes, so a backfill cannot silently re-open a closed messaging window.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.apparel.modules.conversations.gateway.messenger_backfill import (
    DEFAULT_MAX_CONVERSATIONS,
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_SIZE,
    BackfillResult,
    MessengerBackfill,
)
from app.applications.apparel.modules.conversations.models import Message
from app.applications.apparel.modules.conversations.service import ConversationService
from app.applications.apparel.modules.customers.service import CustomerService

logger = logging.getLogger(__name__)

#: Per thread. A conversation can hold hundreds of messages; the newest ones are what the merchant
#: needs, and Meta returns them newest first.
DEFAULT_MAX_MESSAGES_PER_CONVERSATION = 50


def _created_at(raw: Any) -> datetime | None:
    """Meta's ``created_time`` as an aware datetime, or None when it is not one we can trust."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class MessengerBackfillService:
    """Turn one walk result into messages, without pretending history is new."""

    @staticmethod
    def customer_ref(conversation: dict, page_id: str) -> str | None:
        """The PSID of the person on the other side of this thread.

        Meta's participant list carries the Page and the person; the Page is the one whose id we
        connected with, so the other id is the customer. Nothing is guessed: a thread with no
        identifiable person is skipped rather than filed under the Page's own id.
        """
        participants = ((conversation.get("participants") or {}).get("data")) or []
        for participant in participants:
            pid = str((participant or {}).get("id") or "")
            if pid and pid != str(page_id):
                return pid
        return None

    @classmethod
    async def persist(
        cls,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        page_id: str,
        result: BackfillResult,
        channel: str = "messenger",
        max_messages_per_conversation: int = DEFAULT_MAX_MESSAGES_PER_CONVERSATION,
    ) -> dict[str, int]:
        """Store the walk's conversations and messages; returns what actually happened."""
        stored = 0
        duplicates = 0
        skipped = 0
        threads = 0

        for conversation_row in result.conversations:
            provider_conversation_id = str(conversation_row.get("id") or "")
            customer_ref = cls.customer_ref(conversation_row, page_id)
            if not provider_conversation_id or not customer_ref:
                skipped += 1
                continue
            messages = result.messages_by_conversation.get(provider_conversation_id) or []
            if not messages:
                skipped += 1
                continue

            customer = await CustomerService.get_or_create_by_identity(
                session, tenant_id, channel=channel, external_id=customer_ref, name=None
            )
            conversation = await ConversationService.get_or_create(
                session, tenant_id, customer_id=customer.id, channel=channel
            )
            window_anchor_before = conversation.last_customer_message_at
            newest_inbound: datetime | None = None
            stored_here = 0

            for message in messages[: max(0, max_messages_per_conversation)]:
                mid = str((message or {}).get("id") or "")
                body = message.get("message")
                if not mid or not isinstance(body, str) or not body:
                    # A sticker, an attachment or a message we cannot represent is counted, never
                    # invented: a row with a guessed body would be a lie in the thread.
                    skipped += 1
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
                    duplicates += 1
                    continue

                sender_id = str(((message.get("from") or {}).get("id")) or "")
                outbound = bool(sender_id) and sender_id == str(page_id)
                await ConversationService.add_message(
                    session,
                    tenant_id,
                    conversation_id=conversation.id,
                    direction="outbound" if outbound else "inbound",
                    sender_type="agent" if outbound else "customer",
                    body=body,
                    channel_message_id=mid,
                    payload={
                        "source": "messenger_backfill",
                        "provider_conversation_id": provider_conversation_id,
                    },
                    provider_metadata={"backfilled": True},
                )
                stored += 1
                stored_here += 1
                if not outbound:
                    sent_at = _created_at(message.get("created_time"))
                    if sent_at and (newest_inbound is None or sent_at > newest_inbound):
                        newest_inbound = sent_at

            if stored_here:
                threads += 1
                # History must not arrive as unread, and must not re-open the messaging window
                # at "now". Meta's own numbers replace the ones add_message just wrote.
                raw_unread = conversation_row.get("unread_count")
                conversation.unread_count = (
                    max(0, int(raw_unread)) if isinstance(raw_unread, int) else 0
                )
                if newest_inbound is not None:
                    conversation.last_customer_message_at = max(
                        newest_inbound, window_anchor_before or newest_inbound
                    )

        summary = {
            "threads": threads,
            "messages_stored": stored,
            "duplicates": duplicates,
            "skipped": skipped,
        }
        logger.info(
            "messenger.backfill_persisted tenant=%s threads=%s stored=%s duplicates=%s skipped=%s",
            tenant_id,
            threads,
            stored,
            duplicates,
            skipped,
        )
        return summary

    @classmethod
    async def backfill_tenant(
        cls,
        tenant_id: uuid.UUID,
        *,
        session: AsyncSession,
        page_id: str,
        token: str,
        http=None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
        max_pages: int = DEFAULT_MAX_PAGES,
        client=None,
    ) -> dict[str, Any]:
        """Walk Meta with the caps, then store what came back. One call per store."""
        import httpx

        owned = None
        if http is None:
            owned = httpx.AsyncClient(timeout=30)
            http = owned
        try:
            walk = await MessengerBackfill().walk(
                http,
                page_id=page_id,
                token=token,
                page_size=page_size,
                max_conversations=max_conversations,
                max_pages=max_pages,
            )
        finally:
            if owned is not None:
                await owned.aclose()

        summary = await cls.persist(session, tenant_id, page_id=page_id, result=walk)
        summary.update(
            {
                "stopped": walk.stopped,
                "error": walk.error,
                "conversations_read": len(walk.conversations),
                "pages_read": walk.pages_read,
            }
        )
        return summary
