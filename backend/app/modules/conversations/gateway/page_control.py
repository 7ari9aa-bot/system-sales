"""What Meta tells us about WHO is talking to a customer: human replies and thread control.

Two kinds of Messenger event used to be parsed and then thrown away:

* **Echoes.** A reply typed in Meta Business Suite or the Page inbox comes back to us as a message
  with ``is_echo``. Dropped, it left a conversation in FIHRIST that looked unanswered: the
  customer's last message sat there with no reply, the first-response clock kept running, and the
  AI could answer a question a person had already answered.
* **Thread handovers.** ``pass_thread_control`` hands the conversation to another app or to a
  person; ``take_thread_control`` takes it back. Dropped, the AI went on replying after the thread
  was handed to a human.

Both are recorded here as FACTS, not as sends. An echo is a message that has already left, so it
is written straight as a ``sent`` agent message: it never goes through the outbound policy gate
(which could refuse something already delivered) and never raises a ``message.outbound`` event
(which would send it a second time). Our own sends come back as echoes too; they are recognised by
their provider id and by ``app_id`` and ignored.

Handover is deliberately conservative. Only an event that moves control AWAY from this app, or
brings it back to it, changes anything, and only by using the status the AI already respects
(``waiting_human``), so a human who has the thread is never talked over.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Why a conversation was parked, so a reader can tell a Meta hand-over from an AI give-up.
HANDOVER_REASON = "meta_thread_control"


def _text(value: Any, limit: int = 4000) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


async def _conversation_for(
    session: AsyncSession, tenant_id: uuid.UUID, channel: str, customer_ref: str
):
    """The open conversation of the customer behind this provider id, or None."""
    from app.modules.conversations.models import Conversation
    from app.modules.customers.models import CustomerIdentity

    if not customer_ref:
        return None
    customer_id = (
        await session.execute(
            select(CustomerIdentity.customer_id).where(
                CustomerIdentity.tenant_id == tenant_id,
                CustomerIdentity.channel == channel,
                CustomerIdentity.external_id == customer_ref,
            )
        )
    ).scalar_one_or_none()
    if customer_id is None:
        return None
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


async def record_echoes(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    channel: str,
    echoes: list[dict],
    *,
    own_app_id: str,
) -> int:
    """Store replies typed outside FIHRIST. Returns how many new messages were written."""
    from datetime import UTC, datetime

    from app.modules.conversations.models import Message

    written = 0
    for echo in echoes:
        mid = _text(echo.get("mid"), 255)
        body = _text(echo.get("text"))
        # Our own send, echoed back: already stored under its provider id.
        if own_app_id and str(echo.get("app_id") or "") == own_app_id:
            continue
        if not mid or not body:
            continue
        conversation = await _conversation_for(
            session, tenant_id, channel, str(echo.get("customer_ref") or "")
        )
        if conversation is None:
            # An echo for a person who never wrote to us: no thread to put it in, and one must
            # not be invented from a reply alone.
            continue
        already = (
            await session.execute(
                select(Message.id).where(
                    Message.tenant_id == tenant_id, Message.channel_message_id == mid
                )
            )
        ).first()
        if already is not None:
            continue
        now = datetime.now(UTC)
        session.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                direction="outbound",
                sender_type="agent",
                channel=conversation.channel,
                channel_message_id=mid,
                body=body,
                content_type="text",
                status="sent",
                provider_metadata={"source": "page_inbox_echo", "app_id": echo.get("app_id")},
                payload={},
            )
        )
        conversation.last_message_at = now
        written += 1
        # A person answered: the first-response clock is met and the thread is a human's now.
        from app.modules.operations.sla import SlaService

        await SlaService.mark_met(session, tenant_id, conversation_id=conversation.id)
        if conversation.status in ("open", "waiting_ai", "waiting_customer"):
            conversation.status = "waiting_human"
    if written:
        await session.flush()
    return written


async def apply_handovers(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    channel: str,
    handovers: list[dict],
    *,
    own_app_id: str,
) -> int:
    """Pause the AI when control leaves this app, resume it when control comes back.

    Returns the number of conversations whose state changed.
    """
    changed = 0
    for event in handovers:
        conversation = await _conversation_for(
            session, tenant_id, channel, str(event.get("customer_ref") or "")
        )
        if conversation is None:
            continue
        kind = event.get("event")
        new_owner = str(event.get("new_owner_app_id") or "")
        previous = str(event.get("previous_owner_app_id") or "")
        leaving = kind == "pass_thread_control" and new_owner != own_app_id
        returning = (kind == "take_thread_control" and new_owner == own_app_id) or (
            kind == "pass_thread_control" and new_owner == own_app_id
        )
        # `take_thread_control` by someone else, and any `request_thread_control`, also mean a
        # person (or another app) is in charge or wants to be: the AI stands down for both.
        taken_elsewhere = kind == "take_thread_control" and new_owner != own_app_id
        requested = kind == "request_thread_control" and previous in ("", own_app_id)
        if leaving or taken_elsewhere or requested:
            if conversation.status in ("open", "waiting_ai", "waiting_customer"):
                from app.modules.ai.handover import request_human_takeover

                if await request_human_takeover(
                    session,
                    tenant_id,
                    conversation_id=conversation.id,
                    reason=HANDOVER_REASON,
                    note=f"Meta {kind}",
                ):
                    changed += 1
        elif returning and conversation.status == "waiting_human":
            # Control is back with this app: the AI may answer the next message again.
            conversation.status = "open"
            changed += 1
    if changed:
        await session.flush()
    return changed
