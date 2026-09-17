"""Messaging flow tests — webchat ingest end-to-end + conversation service."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.webchat import webchat_adapter
from app.modules.conversations.models import Conversation, Message
from app.modules.conversations.service import ConversationService
from app.modules.platform.models import Integration


async def _make_webchat_integration(db, tenant_id: uuid.UUID, public_key: str) -> None:
    db.add(
        Integration(
            tenant_id=tenant_id,
            provider="webchat",
            kind="channel",
            status="connected",
            config={"public_key": public_key},
            credentials={},
        )
    )
    await db.flush()


async def test_webchat_ingest_end_to_end(db, tenant_ctx):
    public_key = f"pk-{uuid.uuid4().hex[:12]}"
    await _make_webchat_integration(db, tenant_ctx.tenant_id, public_key)

    payload = {
        "public_key": public_key,
        "session_key": f"visitor-{uuid.uuid4().hex[:12]}",
        "body": "عايز أعرف سعر المنتج",
        "client_message_id": f"cm-{uuid.uuid4().hex[:10]}",
        "visitor_name": "Ahmed",
    }
    messages = webchat_adapter.parse_inbound(payload)
    assert len(messages) == 1
    conversation_id = await IngestService.ingest(
        db,
        tenant_id=tenant_ctx.tenant_id,
        message=messages[0],
        idempotency_scope="webhook:webchat",
    )
    assert conversation_id is not None

    conversation = (
        await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one()
    assert conversation.unread_count == 1
    assert conversation.channel == "webchat"
    assert conversation.status == "open"

    msgs = (
        (await db.execute(select(Message).where(Message.conversation_id == conversation_id)))
        .scalars()
        .all()
    )
    assert len(msgs) == 1
    assert msgs[0].direction == "inbound"
    assert msgs[0].body == "عايز أعرف سعر المنتج"
    assert msgs[0].status == "received"


async def test_webchat_ingest_idempotent_on_client_message_id(db, tenant_ctx):
    public_key = f"pk-{uuid.uuid4().hex[:12]}"
    await _make_webchat_integration(db, tenant_ctx.tenant_id, public_key)
    cm_id = f"cm-{uuid.uuid4().hex[:10]}"
    message = webchat_adapter.parse_inbound(
        {
            "public_key": public_key,
            "session_key": f"visitor-{uuid.uuid4().hex[:12]}",
            "body": "hi",
            "client_message_id": cm_id,
        }
    )[0]
    first = await IngestService.ingest(
        db, tenant_id=tenant_ctx.tenant_id, message=message, idempotency_scope="webhook:webchat"
    )
    second = await IngestService.ingest(
        db, tenant_id=tenant_ctx.tenant_id, message=message, idempotency_scope="webhook:webchat"
    )
    assert first is not None
    assert second is None  # duplicate rejected
    count = len(
        (await db.execute(select(Message).where(Message.channel_message_id == cm_id)))
        .scalars()
        .all()
    )
    assert count == 1


async def test_conversation_service_flow(db, tenant_ctx):
    from app.modules.customers.models import Customer

    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Walk-in")
    db.add(customer)
    await db.flush()

    conversation = await ConversationService.get_or_create(
        db, tenant_ctx.tenant_id, customer_id=customer.id, channel="webchat"
    )
    message = await ConversationService.add_message(
        db,
        tenant_ctx.tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="مرحبا",
    )
    assert message.status == "received"

    with pytest.raises(ValidationError):
        await ConversationService.add_message(
            db,
            tenant_ctx.tenant_id,
            conversation_id=conversation.id,
            direction="outbound",
            sender_type="agent",
        )  # no body, no media

    reply = await ConversationService.add_message(
        db,
        tenant_ctx.tenant_id,
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="agent",
        body="أهلاً بيك!",
    )
    assert reply.status == "queued"

    await ConversationService.close(db, tenant_ctx.tenant_id, conversation.id)
    reopened_view = await ConversationService.get(db, tenant_ctx.tenant_id, conversation.id)
    assert reopened_view.status == "closed"


async def test_conversation_tenant_isolation(db, tenant_ctx):
    from app.modules.customers.models import Customer

    customer = Customer(tenant_id=tenant_ctx.tenant_id, name="Isolated")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_ctx.tenant_id, customer_id=customer.id, channel="webchat"
    )
    foreign_tenant = uuid.uuid4()
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await ConversationService.get(db, foreign_tenant, conversation.id)
