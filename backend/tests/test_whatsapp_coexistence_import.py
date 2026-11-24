"""Coexistence data import: chat history, contacts and the merchant's own app replies.

DB-backed (skips without Postgres). What it pins is the difference between importing data and
receiving a message:

* history is stored at Meta's timestamp, with NO outbox event, so a 180-day backfill never
  produces a single AI answer and never opens a fake 24-hour service window;
* a replayed chunk adds nothing, and a late chunk never walks a finished transfer backwards;
* an echo from the phone is a HUMAN outbound reply and takes the thread away from the agent,
  which is the only thing stopping a second, contradictory answer;
* a contact update creates a customer and no conversation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.models import Conversation, Message, WhatsAppSyncRun
from app.modules.platform.models import Integration, OutboxEvent

pytestmark = pytest.mark.asyncio

NUMBER = "456"
CUSTOMER = "201111111111"
EPOCH = "2026-11-24T00:00:00+00:00"


async def _connected_channel(session, tenant_id) -> Integration:
    integration = Integration(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider="whatsapp",
        kind="channel",
        config={
            "phone_number_id": NUMBER,
            "waba_id": "1001",
            "onboarding_mode": "coexistence",
            "coexistence_status": "verified",
            "coexistence_verified_at": EPOCH,
        },
        credentials={},
        status="active",
    )
    session.add(integration)
    await session.flush()
    return integration


def _message(mid: str, *, when: datetime | None = None, direction="inbound", **overrides) -> dict:
    item = {
        "channel_message_id": mid,
        "customer_ref": CUSTOMER,
        "direction": direction,
        "occurred_at": when,
        "body": "رسالة",
        "media_url": None,
        "media_type": None,
        "content_type": "text",
        "reply_to_message_id": None,
        "raw": {"id": mid},
    }
    item.update(overrides)
    return item


def _chunk(*messages: dict, phase=0, chunk_order=0, progress=0) -> dict:
    return {
        "phone_number_id": NUMBER,
        "request_id": "req-1",
        "phase": phase,
        "chunk_order": chunk_order,
        "progress": progress,
        "messages": list(messages),
    }


async def _count(session, model, **filters) -> int:
    query = select(func.count()).select_from(model)
    for key, value in filters.items():
        query = query.where(getattr(model, key) == value)
    return (await session.execute(query)).scalar_one()


# --------------------------------------------------------------- history


async def test_history_is_stored_at_its_own_time_and_never_answered(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    long_ago = datetime.now(UTC) - timedelta(days=40)
    before_events = await _count(session, OutboxEvent)

    stored = await IngestService.apply_history(
        session, tenant_id, "whatsapp", [_chunk(_message("wamid.H1", when=long_ago))]
    )
    assert stored == 1

    row = (
        await session.execute(select(Message).where(Message.channel_message_id == "wamid.H1"))
    ).scalar_one()
    assert row.created_at == long_ago
    assert (row.direction, row.sender_type) == ("inbound", "customer")
    assert row.provider_metadata.get("imported_from") == "whatsapp_history"

    # Not one event: the AI must never answer a message from months ago.
    assert await _count(session, OutboxEvent) == before_events

    conversation = (
        await session.execute(select(Conversation).where(Conversation.tenant_id == tenant_id))
    ).scalar_one()
    # The service window is whatever it honestly is — NOT the moment of the import.
    assert conversation.last_customer_message_at == long_ago
    assert conversation.unread_count == 0


async def test_a_replayed_chunk_adds_nothing(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    chunk = _chunk(_message("wamid.H2"))

    assert await IngestService.apply_history(session, tenant_id, "whatsapp", [chunk]) == 1
    assert await IngestService.apply_history(session, tenant_id, "whatsapp", [chunk]) == 0
    assert await _count(session, Message, tenant_id=tenant_id) == 1


async def test_late_chunks_land_and_never_walk_the_transfer_backwards(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)

    # Phase 2 arrives first (out of order) and reports the transfer complete.
    await IngestService.apply_history(
        session, tenant_id, "whatsapp", [_chunk(_message("wamid.P2"), phase=2, progress=100)]
    )
    # Then phase 0 with an older message.
    await IngestService.apply_history(
        session, tenant_id, "whatsapp", [_chunk(_message("wamid.P0"), phase=0, progress=10)]
    )

    assert await _count(session, Message, tenant_id=tenant_id) == 2
    run = (
        await session.execute(select(WhatsAppSyncRun).where(WhatsAppSyncRun.tenant_id == tenant_id))
    ).scalar_one()
    assert run.state == "completed"
    assert run.progress == 100
    assert set(run.phases) == {"0", "2"}
    assert run.chunks_seen == 2


async def test_history_records_its_request_id_and_completion(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    await IngestService.apply_history(
        session, tenant_id, "whatsapp", [_chunk(_message("wamid.H3"), progress=100)]
    )
    run = (
        await session.execute(select(WhatsAppSyncRun).where(WhatsAppSyncRun.tenant_id == tenant_id))
    ).scalar_one()
    assert run.onboarding_epoch == EPOCH
    assert run.sync_type == "history"
    assert run.completed_at is not None


# --------------------------------------------------------------- the app's replies


def _echo(mid: str, **overrides) -> dict:
    item = {
        "channel_message_id": mid,
        "customer_ref": CUSTOMER,
        "occurred_at": datetime.now(UTC),
        "body": "تم الشحن",
        "media_url": None,
        "media_type": None,
        "content_type": "text",
        "reply_to_message_id": None,
        "source": "whatsapp_business_app",
        "raw": {"id": mid},
    }
    item.update(overrides)
    return item


async def test_an_app_echo_is_a_human_outbound_reply_that_takes_the_thread(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)

    assert (
        await IngestService.apply_app_echoes(session, tenant_id, "whatsapp", [_echo("wamid.E1")])
        == 1
    )

    row = (
        await session.execute(select(Message).where(Message.channel_message_id == "wamid.E1"))
    ).scalar_one()
    assert (row.direction, row.sender_type) == ("outbound", "agent")
    assert row.provider_metadata.get("imported_from") == "whatsapp_business_app"

    conversation = (
        await session.execute(select(Conversation).where(Conversation.tenant_id == tenant_id))
    ).scalar_one()
    # waiting_human is what stops the agent answering a message the merchant already answered.
    assert conversation.status == "waiting_human"


async def test_a_media_only_echo_is_stored(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    await IngestService.apply_app_echoes(
        session,
        tenant_id,
        "whatsapp",
        [
            _echo(
                "wamid.E2", body=None, content_type="image", media_url="media-9", media_type="image"
            )
        ],
    )
    row = (
        await session.execute(select(Message).where(Message.channel_message_id == "wamid.E2"))
    ).scalar_one()
    assert (row.content_type, row.media_url) == ("image", "media-9")


async def test_a_replayed_echo_is_stored_once(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    await IngestService.apply_app_echoes(session, tenant_id, "whatsapp", [_echo("wamid.E3")])
    assert (
        await IngestService.apply_app_echoes(session, tenant_id, "whatsapp", [_echo("wamid.E3")])
        == 0
    )
    assert await _count(session, Message, tenant_id=tenant_id) == 1


# --------------------------------------------------------------- contacts


async def test_contacts_become_customers_without_opening_conversations(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)

    stored = await IngestService.apply_app_state_sync(
        session,
        tenant_id,
        "whatsapp",
        [
            {
                "phone_number_id": NUMBER,
                "request_id": "req-2",
                "contacts": [
                    {"phone": CUSTOMER, "name": "أحمد", "action": "add"},
                    {"phone": "201222222222", "name": None, "action": "update"},
                    {"phone": "201333333333", "name": "اتشال", "action": "remove"},
                ],
            }
        ],
    )
    assert stored == 2
    # A contact update is not a message: nothing to answer, nobody to page.
    assert await _count(session, Conversation, tenant_id=tenant_id) == 0
    run = (
        await session.execute(
            select(WhatsAppSyncRun).where(
                WhatsAppSyncRun.tenant_id == tenant_id, WhatsAppSyncRun.sync_type == "contacts"
            )
        )
    ).scalar_one()
    assert run.chunks_seen == 1


# --------------------------------------------------------------- unsupported messages


async def test_an_unsupported_notice_is_recorded_without_touching_the_channel(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    integration = await _connected_channel(session, tenant_id)

    recorded = await IngestService.apply_unsupported_notices(
        session,
        tenant_id,
        "whatsapp",
        [
            {
                "code": 131060,
                "title": "Unsupported message",
                "details": "companion device",
                "channel_message_id": "wamid.U1",
                "recipient_ref": CUSTOMER,
            }
        ],
    )
    assert recorded == 1
    assert await _count(session, Message, tenant_id=tenant_id) == 1
    notice = (
        await session.execute(
            select(Message).where(
                Message.tenant_id == tenant_id,
                Message.channel_message_id == "unsupported:wamid.U1",
            )
        )
    ).scalar_one()
    assert notice.sender_type == "system"
    assert notice.content_type == "unsupported"
    assert integration.status == "active"
