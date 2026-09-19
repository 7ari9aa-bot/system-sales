"""Wiring tests — the audit gaps G1-G11: models that existed but were unused.

Covers:
- (a) ProcessedEvent consumer-inbox dedupe via nested savepoint (§127)
- (b) durable ACTIVE reservation row on order creation (§140)
- (c) cancel_order flips reservations to CANCELLED and releases stock (§140)
- (d) add_payment flips reservations to CONVERTED (§140)
- (e) canonical message columns: content_type default, reply_to, metadata (§155)
- (f) WebhookEvent ingress insert + lookup by (provider, external_event_id)
- (g) EventLog insert with v2 envelope meta fields (§152)
plus: conversation lifecycle states (§156), Integration webhook_health (§145),
tool risk levels (§135) and the relay's EventLog param mapping (§152).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.ai.tools import TOOLS, requires_approval
from app.modules.catalog.service import CatalogService
from app.modules.conversations.models import CONVERSATION_STATUSES, Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.service import CustomerService
from app.modules.inventory.models import InventoryBalance, InventoryReservation, Warehouse
from app.modules.inventory.service import InventoryService
from app.modules.orders.service import OrderService
from app.modules.platform.models import EventLog, Integration, ProcessedEvent, WebhookEvent
from app.workers.run import POOLS

# ---------------------------------------------------------------- helpers --


async def _warehouse(db: AsyncSession, tenant_id: uuid.UUID) -> Warehouse:
    warehouse = Warehouse(
        tenant_id=tenant_id,
        name="Wiring WH",
        code=f"WH-{uuid.uuid4().hex[:6].upper()}",
    )
    db.add(warehouse)
    await db.flush()
    return warehouse


async def _customer_and_variant(
    db: AsyncSession, tenant_id: uuid.UUID, stock: int = 10
):
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:10]}",
        name="Wiring Buyer",
        phone=f"+2011{uuid.uuid4().hex[:8]}",
    )
    wh = await _warehouse(db, tenant_id)
    product = await CatalogService.create_product(
        db, tenant_id, title="Wiring Widget", slug=f"ww-{uuid.uuid4().hex[:10]}"
    )
    variant = await CatalogService.add_variant(
        db, tenant_id, product.id, sku=f"WWG-{uuid.uuid4().hex[:6].upper()}", price="25.50"
    )
    if stock:
        await InventoryService.move(
            db,
            tenant_id,
            variant.id,
            wh.id,
            direction="in",
            quantity=stock,
            reason="purchase",
        )
    return customer, variant, wh


async def _balance(
    db: AsyncSession, tenant_id: uuid.UUID, variant_id: uuid.UUID, warehouse_id: uuid.UUID
) -> InventoryBalance:
    return (
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.tenant_id == tenant_id,
                InventoryBalance.variant_id == variant_id,
                InventoryBalance.warehouse_id == warehouse_id,
            )
        )
    ).scalar_one()


async def _reservations(
    db: AsyncSession, tenant_id: uuid.UUID, order_id: uuid.UUID
) -> list[InventoryReservation]:
    return list(
        (
            await db.execute(
                select(InventoryReservation).where(
                    InventoryReservation.tenant_id == tenant_id,
                    InventoryReservation.order_id == order_id,
                )
            )
        ).scalars().all()
    )


# ------------------------------------------------- (a) ProcessedEvent §127 --


async def test_processed_event_dedupe_via_savepoint(db, tenant_ctx):
    """Duplicate (consumer_name, event_id) dies on the unique constraint; the
    savepoint rolls back and the session stays usable — exactly-once §127."""
    event_id = uuid.uuid4()
    db.add(
        ProcessedEvent(consumer_name="message-worker", event_id=event_id, status="done")
    )
    await db.flush()

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                ProcessedEvent(
                    consumer_name="message-worker", event_id=event_id, status="done"
                )
            )
            await db.flush()

    # The savepoint rollback leaves the session usable; a different event id
    # for the same consumer inserts fine and the original row is intact.
    db.add(
        ProcessedEvent(consumer_name="message-worker", event_id=uuid.uuid4(), status="done")
    )
    await db.flush()
    rows = (
        await db.execute(
            select(ProcessedEvent).where(
                ProcessedEvent.consumer_name == "message-worker",
                ProcessedEvent.event_id == event_id,
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "done"


# ------------------------------------------- (b/c/d) Reservation rows §140 --


async def test_order_creation_writes_active_reservation(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, wh = await _customer_and_variant(db, tenant_id, stock=10)

    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 3}]
    )
    await db.flush()

    reservations = await _reservations(db, tenant_id, order.id)
    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation.status == "ACTIVE"
    assert reservation.variant_id == variant.id
    assert reservation.warehouse_id == wh.id
    assert reservation.quantity == 3
    assert reservation.expires_at is not None  # TTL: now + 15 min
    # The balance-level hold is in place alongside the durable row.
    assert (await _balance(db, tenant_id, variant.id, wh.id)).reserved == 3


async def test_cancel_order_marks_reservation_cancelled(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, wh = await _customer_and_variant(db, tenant_id, stock=10)

    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 2}]
    )
    await OrderService.cancel_order(db, tenant_id, order.id)
    await db.flush()

    reservations = await _reservations(db, tenant_id, order.id)
    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation.status == "CANCELLED"
    assert reservation.cancelled_at is not None
    assert reservation.converted_at is None
    # The stock hold went back too.
    assert (await _balance(db, tenant_id, variant.id, wh.id)).reserved == 0


async def test_add_payment_marks_reservation_converted(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer, variant, wh = await _customer_and_variant(db, tenant_id, stock=10)

    order = await OrderService.create_order(
        db, tenant_id, customer.id, [{"variant_id": variant.id, "quantity": 1}]
    )
    payment = await OrderService.add_payment(
        db, tenant_id, order.id, method="cash", amount="25.50"
    )
    await db.flush()

    assert payment.status == "captured"
    assert order.status == "confirmed"
    reservations = await _reservations(db, tenant_id, order.id)
    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation.status == "CONVERTED"
    assert reservation.converted_at is not None
    assert reservation.cancelled_at is None
    # Converting is NOT releasing: the hold stays until fulfilment moves it.
    assert (await _balance(db, tenant_id, variant.id, wh.id)).reserved == 1


# ------------------------------- (e) canonical message columns (§155) ------


async def test_message_canonical_columns(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:10]}"
    )
    convo = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="whatsapp"
    )

    inbound = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=convo.id,
        direction="inbound",
        sender_type="customer",
        body="مرحبا",
    )
    # Defaults: plain text message, not edited/deleted, no thread, no extras.
    assert inbound.content_type == "text"
    assert inbound.reply_to_message_id is None
    assert inbound.edited is False
    assert inbound.deleted is False
    assert inbound.provider_metadata == {}

    reply = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=convo.id,
        direction="outbound",
        sender_type="agent",
        body=None,
        media_url="https://cdn.example.test/catalog.jpg",
        media_type="image",
        content_type="image",
        reply_to_message_id=inbound.id,
        provider_metadata={"wamid": f"wamid.{uuid.uuid4().hex[:10]}"},
    )
    await db.flush()
    assert reply.content_type == "image"
    assert reply.reply_to_message_id == inbound.id
    assert reply.provider_metadata["wamid"].startswith("wamid.")

    # Thread is queryable via the reply_to index column.
    threaded = (
        await db.execute(
            select(Message).where(
                Message.tenant_id == tenant_id,
                Message.reply_to_message_id == inbound.id,
            )
        )
    ).scalars().all()
    assert [m.id for m in threaded] == [reply.id]


# ------------------------- (f) WebhookEvent ingress lookup -----------------


async def test_webhook_event_insert_and_lookup(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    external_id = f"evt-{uuid.uuid4().hex[:12]}"
    db.add(
        WebhookEvent(
            provider="whatsapp",
            external_event_id=external_id,
            tenant_id=tenant_id,
            payload={"field": "messages"},
            signature_valid=True,
        )
    )
    db.add(
        WebhookEvent(
            provider="whatsapp",
            external_event_id=f"other-{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            payload={},
        )
    )
    await db.flush()

    found = (
        await db.execute(
            select(WebhookEvent).where(
                WebhookEvent.provider == "whatsapp",
                WebhookEvent.external_event_id == external_id,
            )
        )
    ).scalar_one()
    assert found.tenant_id == tenant_id
    assert found.payload == {"field": "messages"}
    assert found.signature_valid is True
    assert found.received_at is not None
    assert found.processing_status == "pending"


# --------------------------- (g) EventLog v2 replay history (§152) ---------


async def test_event_log_insert_with_v2_meta_fields(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    row = EventLog(
        tenant_id=tenant_id,
        event_id=uuid.uuid4(),
        event_type="order.created",
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        aggregate_version=3,
        schema_version=2,
        occurred_at=datetime.now(UTC),
        producer="orders-svc",
        correlation_id="corr-123",
        causation_id="cause-456",
        payload={"number": "ORD-2026-0001", "grand_total": 76.5},
    )
    db.add(row)
    await db.flush()

    fetched = (
        await db.execute(select(EventLog).where(EventLog.event_id == row.event_id))
    ).scalar_one()
    assert fetched.tenant_id == tenant_id
    assert fetched.event_type == "order.created"
    assert fetched.aggregate_type == "order"
    assert fetched.aggregate_id == row.aggregate_id
    assert fetched.aggregate_version == 3
    assert fetched.schema_version == 2
    assert fetched.producer == "orders-svc"
    assert fetched.correlation_id == "corr-123"
    assert fetched.causation_id == "cause-456"
    assert fetched.payload == {"number": "ORD-2026-0001", "grand_total": 76.5}
    assert fetched.created_at is not None


# ---------------------------- (§156) conversation lifecycle states ---------


async def test_conversation_lifecycle_states_and_legacy_alias(db, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "webchat", f"visitor-{uuid.uuid4().hex[:10]}"
    )
    convo = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    assert convo.status == "open"

    for status in ("waiting_human", "waiting_ai", "waiting_customer", "paused"):
        updated = await ConversationService.set_status(db, tenant_id, convo.id, status)
        assert updated.status == status

    # Legacy alias: "pending" normalizes to "open" (documented §156).
    reopened = await ConversationService.set_status(db, tenant_id, convo.id, "pending")
    assert reopened.status == "open"

    closed = await ConversationService.set_status(db, tenant_id, convo.id, "closed")
    assert closed.status == "closed"

    with pytest.raises(ValidationError):
        await ConversationService.set_status(db, tenant_id, convo.id, "archived")
    assert CONVERSATION_STATUSES == {
        "open",
        "waiting_customer",
        "waiting_human",
        "waiting_ai",
        "paused",
        "closed",
    }


# -------------------------- (§145) Integration webhook_health --------------


def test_scheduler_worker_is_registered():
    from app.workers.scheduler_worker import SchedulerWorker

    assert POOLS["scheduler"] is SchedulerWorker


async def test_integration_webhook_health_column(db, tenant_ctx):
    integration = Integration(
        tenant_id=tenant_ctx.tenant_id,
        provider="webchat",
        kind="channel",
        config={"public_key": f"pk-{uuid.uuid4().hex[:10]}"},
    )
    db.add(integration)
    await db.flush()

    assert integration.webhook_health == {}
    # Legacy status value still accepted (migration maps it to 'active').
    assert integration.status == "connected"

    integration.webhook_health = {"last_webhook_at": "2026-09-18T00:00:00Z"}
    await db.flush()
    refetched = (
        await db.execute(select(Integration).where(Integration.id == integration.id))
    ).scalar_one()
    assert refetched.webhook_health["last_webhook_at"] == "2026-09-18T00:00:00Z"


# ------------------------------ (§135) tool risk levels --------------------


def test_tool_risk_levels_and_requires_approval():
    create_order = TOOLS["create_order"]
    assert create_order.risk_level == "HIGH"
    for name in ("search_products", "get_variant_price", "check_stock"):
        assert TOOLS[name].risk_level == "LOW"

    assert asyncio.run(requires_approval(create_order)) is True
    assert asyncio.run(requires_approval(TOOLS["check_stock"])) is False


# ----------------- (§152) relay EventLog param mapping (pure unit) ---------


def test_relay_event_log_param_mapping_is_defensive():
    from app.core.events.outbox import OutboxRelay

    relay = OutboxRelay(bus=MagicMock())
    session = MagicMock()
    session.execute = AsyncMock()
    created_at = datetime.now(UTC)
    row = {
        "id": uuid.uuid4(),
        "aggregate_type": "order",
        "aggregate_id": uuid.uuid4(),
        "created_at": created_at,
    }
    payload = {"event_type": "order.created", "number": "ORD-1"}
    meta = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "correlation_id": "corr-1",
        "causation_id": "cause-2",
        "producer": "orders-svc",
        "schema_version": 2,
        "aggregate_version": "7",  # arrives as string in JSON meta
    }

    import asyncio

    asyncio.run(relay._write_event_log(session, row, payload, meta))

    insert_calls = [
        c for c in session.execute.await_args_list if len(c.args) == 2
    ]
    params = insert_calls[-1].args[1]
    assert params["event_id"] == row["id"]
    assert params["event_type"] == "order.created"
    assert params["aggregate_type"] == "order"
    assert params["aggregate_id"] == row["aggregate_id"]
    assert params["aggregate_version"] == 7
    assert params["schema_version"] == 2
    assert params["occurred_at"] == created_at
    assert params["producer"] == "orders-svc"
    assert params["correlation_id"] == "corr-1"
    assert params["causation_id"] == "cause-2"
    assert params["tenant_id"] == meta["tenant_id"]
    assert json.loads(params["payload"]) == payload

    # Missing tenant: no insert attempted (defensive skip, never a crash).
    session_no_tenant = MagicMock()
    session_no_tenant.execute = AsyncMock()
    asyncio.run(
        relay._write_event_log(
            session_no_tenant,
            dict(row),
            payload,
            {"producer": "core"},
        )
    )
    assert session_no_tenant.execute.await_count == 0


# ------------- (§129/§130) outbound reconciliation guards (pure unit) ------


async def test_deliver_one_dead_letters_unknown_and_sending(db, tenant_ctx, monkeypatch):
    """§130: a message previously in unknown/sending is NEVER resent — the
    worker raises PermanentError so the event dead-letters for reconciliation."""
    from app.workers.base import PermanentError
    from app.workers.message_worker import MessageWorker

    tenant_id = tenant_ctx.tenant_id
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "webchat", f"visitor-{uuid.uuid4().hex[:10]}"
    )
    convo = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )

    async def _message_with(status: str) -> Message:
        message = await ConversationService.add_message(
            db,
            tenant_id,
            conversation_id=convo.id,
            direction="outbound",
            sender_type="agent",
            body="pending delivery",
        )
        message.status = status
        await db.flush()
        return message

    import app.workers.message_worker as mw

    sent_calls: list[int] = []

    class FakeAdapter:
        name = "webchat"

        async def send(self, credentials, outbound):
            sent_calls.append(1)
            return "provider-1"

    monkeypatch.setattr(mw, "get_adapter", lambda name: FakeAdapter())
    worker = MessageWorker.__new__(MessageWorker)  # skip __init__ (bus unused)

    for status in ("unknown", "sending"):
        message = await _message_with(status)
        with pytest.raises(PermanentError):
            await worker._deliver_one(db, tenant_id, message.id)
        assert sent_calls == []  # never resent

    # A non-queued, unremarkable status (sent) is skipped silently.
    message = await _message_with("sent")
    plan = await worker._deliver_one(db, tenant_id, message.id)
    assert plan is None
    assert sent_calls == []
