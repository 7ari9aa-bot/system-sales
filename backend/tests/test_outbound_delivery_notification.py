"""A dead-lettered outbound message must RING, not just sit in a row.

Before this: a provider rejection flipped the message to `failed`, the event
dead-lettered for MANUAL reconciliation (§130) — and nobody was told. The
customer had asked a question, an answer had been written, and it died in the
queue while the merchant believed the bot was answering. The bell is what turns
a silent failure into a repairable one.

DB-backed on purpose: the notification is a row keyed to the tenant's OWNER,
deduped per message. Skips locally (no `DATABASE_URL_APP_ADMIN`), runs on CI.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import select

from app.modules.conversations.models import Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer
from app.modules.notifications.models import Notification
from app.workers.message_worker import MessageWorker


async def _failed_outbound_message(db, tenant_id) -> Message:
    customer = Customer(tenant_id=tenant_id, name="Waiting Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    message = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="ai",
        body="إجابة ما وصلتش للعميل",
    )
    await db.flush()
    return message


async def test_a_failed_delivery_rings_the_owners_bell(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    message = await _failed_outbound_message(db, tenant_id)
    worker = MessageWorker(bus=MagicMock())

    await worker._notify_delivery_failed(
        db, tenant_id, message=message, status="failed", error="provider refused: 400"
    )
    await db.flush()

    bells = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.kind == "delivery_failed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(bells) == 1, "the dead letter was never made visible"
    assert bells[0].user_id == tenant_ctx.user.id, "the OWNER must be the one told"
    assert bells[0].payload["message_id"] == str(message.id)
    assert bells[0].payload["outcome"] == "failed"
    assert "provider refused" in bells[0].payload["error"]


async def test_one_bell_per_message_even_when_called_twice(db, tenant_ctx):
    """The dedup key is the message id: a webhook flip or a second scan of the
    queue must not stack identical bells."""
    tenant_id = tenant_ctx.tenant_id
    message = await _failed_outbound_message(db, tenant_id)
    worker = MessageWorker(bus=MagicMock())

    for _ in range(2):
        await worker._notify_delivery_failed(
            db, tenant_id, message=message, status="failed", error="provider refused"
        )
    await db.flush()

    bells = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.kind == "delivery_failed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(bells) == 1


async def test_an_unknown_outcome_rings_too(db, tenant_ctx):
    """`unknown` dead-letters after its retry hits the reconciliation guard —
    the owner hears about it on the terminal outcome, not never."""
    tenant_id = tenant_ctx.tenant_id
    message = await _failed_outbound_message(db, tenant_id)
    worker = MessageWorker(bus=MagicMock())

    await worker._notify_delivery_failed(
        db, tenant_id, message=message, status="unknown", error="timeout mid-send"
    )
    await db.flush()

    bells = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.kind == "delivery_failed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(bells) == 1
    assert bells[0].payload["outcome"] == "unknown"


async def test_a_sent_message_rings_nobody(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    message = await _failed_outbound_message(db, tenant_id)
    worker = MessageWorker(bus=MagicMock())

    await worker._notify_delivery_failed(
        db, tenant_id, message=message, status="sent", error=None
    )
    await db.flush()

    bells = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.kind == "delivery_failed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert bells == []
