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

from app.modules.conversations import whatsapp_sync
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.models import Conversation, Message, WhatsAppSyncRun
from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService
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


def _chunk(*messages: dict, phase=0, chunk_order=0, progress=0, request_id="req-1") -> dict:
    return {
        "phone_number_id": NUMBER,
        "request_id": request_id,
        "phase": phase,
        "chunk_order": chunk_order,
        "progress": progress,
        "messages": list(messages),
    }


async def _run(
    session,
    tenant_id,
    *,
    sync_type: str = whatsapp_sync.WHATSAPP_SYNC_HISTORY,
    request_id: str = "req-1",
) -> WhatsAppSyncRun:
    """The run the durable reservation commits BEFORE Meta is asked for data.

    Every import in production lands on a run that already exists, so the tests create it too —
    a chunk that matches no run is stale by definition, and must not be folded in.
    """
    run = WhatsAppSyncRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        phone_number_id=NUMBER,
        waba_id="1001",
        sync_type=sync_type,
        onboarding_epoch=EPOCH,
        state="in_progress",
        request_id=request_id,
    )
    session.add(run)
    await session.flush()
    return run


async def _count(session, model, **filters) -> int:
    query = select(func.count()).select_from(model)
    for key, value in filters.items():
        query = query.where(getattr(model, key) == value)
    return (await session.execute(query)).scalar_one()


# --------------------------------------------------------------- history


async def test_history_is_stored_at_its_own_time_and_never_answered(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    await _run(session, tenant_id)
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
    await _run(session, tenant_id)
    chunk = _chunk(_message("wamid.H2"))

    assert await IngestService.apply_history(session, tenant_id, "whatsapp", [chunk]) == 1
    assert await IngestService.apply_history(session, tenant_id, "whatsapp", [chunk]) == 0
    assert await _count(session, Message, tenant_id=tenant_id) == 1


async def test_late_chunks_land_and_never_walk_the_transfer_backwards(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    await _run(session, tenant_id)

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
    await _run(session, tenant_id, request_id="req-1")
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


async def test_an_echo_already_imported_by_history_still_takes_the_thread(tenant_ctx) -> None:
    """The launch blocker: history sync stores the merchant's own reply first.

    The echo that follows finds the wamid already stored, so nothing new is written — but the
    conversation MUST still leave the agent's hands. Coupling the handover to "did we write a row"
    left the AI free to answer a customer the merchant had already answered from the phone.
    """
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    await _run(session, tenant_id)
    long_ago = datetime.now(UTC) - timedelta(days=3)
    await IngestService.apply_history(
        session,
        tenant_id,
        "whatsapp",
        [_chunk(_message("wamid.E9", when=long_ago, direction="outbound"))],
    )

    assert (
        await IngestService.apply_app_echoes(session, tenant_id, "whatsapp", [_echo("wamid.E9")])
        == 0
    )

    assert await _count(session, Message, tenant_id=tenant_id) == 1
    conversation = (
        await session.execute(select(Conversation).where(Conversation.tenant_id == tenant_id))
    ).scalar_one()
    assert conversation.status == "waiting_human"


async def test_our_own_send_echoed_back_does_not_take_the_thread(tenant_ctx) -> None:
    """The opposite case, and the reason the handover is not unconditional.

    Meta echoes messages this system sent too. If a duplicate echo took the thread every time, the
    agent would silence itself with its own reply.
    """
    from app.modules.conversations.service import ConversationService

    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    customer = await CustomerService.get_or_create_by_identity(
        session, tenant_id, channel="whatsapp", external_id=CUSTOMER, name=None, phone=CUSTOMER
    )
    conversation = await ConversationService.get_or_create(
        session, tenant_id, customer_id=customer.id, channel="whatsapp"
    )
    await ConversationService.add_message(
        session,
        tenant_id,
        conversation_id=conversation.id,
        direction="outbound",
        sender_type="agent",
        body="رد من فهرست",
        channel_message_id="wamid.OWN",
        payload={"source": "fihrist"},
    )

    assert (
        await IngestService.apply_app_echoes(session, tenant_id, "whatsapp", [_echo("wamid.OWN")])
        == 0
    )
    await session.refresh(conversation)
    assert conversation.status != "waiting_human"


async def test_a_replayed_echo_creates_one_handover(tenant_ctx) -> None:
    from app.modules.ai.models import AIHandover

    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    await IngestService.apply_app_echoes(session, tenant_id, "whatsapp", [_echo("wamid.E7")])
    await IngestService.apply_app_echoes(session, tenant_id, "whatsapp", [_echo("wamid.E7")])

    assert await _count(session, AIHandover, tenant_id=tenant_id) == 1


async def test_a_handover_failure_fails_the_batch_so_it_is_retried(tenant_ctx, monkeypatch) -> None:  # noqa: ANN001
    """Swallowing the failure left the agent answering over the merchant.

    Raising fails the webhook event, which Meta retries; the retry is safe because the message row
    is already deduped by wamid.
    """
    import app.modules.ai.handover as handover

    async def explode(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("handover store unavailable")

    monkeypatch.setattr(handover, "request_human_takeover", explode)

    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    with pytest.raises(RuntimeError):
        await IngestService.apply_app_echoes(session, tenant_id, "whatsapp", [_echo("wamid.E8")])


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


# ----------------------------------------------------- attribution (stale chunks)


async def test_a_stale_chunk_from_an_older_link_is_ignored(tenant_ctx) -> None:
    """A re-link starts a new epoch and a new run; the old link's chunks keep arriving.

    They must not land: not one message, not one percent of progress, not a completion. Otherwise
    the current transfer looks finished while the customer's real history was never imported.
    """
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    run = await _run(session, tenant_id, request_id="req-new")

    stored = await IngestService.apply_history(
        session,
        tenant_id,
        "whatsapp",
        [_chunk(_message("wamid.S1"), request_id="req-old", progress=100)],
    )

    assert stored == 0
    assert await _count(session, Message, tenant_id=tenant_id) == 0
    await session.refresh(run)
    assert (run.progress, run.state, run.messages_stored) == (0, "in_progress", 0)


async def test_a_chunk_with_no_run_is_dropped_instead_of_becoming_one(tenant_ctx) -> None:
    """record_chunk used to invent a run "to keep the evidence".

    That is how a stale chunk after a re-link turned into progress on a transfer nobody asked
    for. The reservation commits the run before Meta is called, so a chunk with no run is stale.
    """
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)

    stored = await IngestService.apply_history(
        session, tenant_id, "whatsapp", [_chunk(_message("wamid.S2"))]
    )

    assert stored == 0
    assert await _count(session, WhatsAppSyncRun, tenant_id=tenant_id) == 0
    assert await _count(session, Message, tenant_id=tenant_id) == 0


async def test_a_stale_contact_batch_creates_no_customers(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    run = await _run(
        session, tenant_id, sync_type=whatsapp_sync.WHATSAPP_SYNC_CONTACTS, request_id="req-new"
    )

    stored = await IngestService.apply_app_state_sync(
        session,
        tenant_id,
        "whatsapp",
        [
            {
                "phone_number_id": NUMBER,
                "request_id": "req-old",
                "contacts": [{"phone": CUSTOMER, "name": "قديم", "action": "add"}],
            }
        ],
    )

    assert stored == 0
    assert await _count(session, Customer, tenant_id=tenant_id) == 0
    await session.refresh(run)
    assert (run.state, run.chunks_seen or 0) == ("in_progress", 0)


# --------------------------------------------------------------- contacts


async def test_contacts_become_customers_without_opening_conversations(tenant_ctx) -> None:
    session, tenant_id = tenant_ctx.session, tenant_ctx.tenant_id
    await _connected_channel(session, tenant_id)
    await _run(
        session, tenant_id, sync_type=whatsapp_sync.WHATSAPP_SYNC_CONTACTS, request_id="req-2"
    )

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
