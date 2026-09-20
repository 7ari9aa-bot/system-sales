"""§19 envelope contract for what the outbox ACTUALLY publishes.

The gap this pins: ``add_outbox_event`` used to hand-merge ``meta`` instead of
building an envelope, so a message on the wire lacked ``type`` / ``occurred_at``
/ ``aggregate_type`` / ``aggregate_id`` and ``deserialize()`` could not rebuild
it. The envelope existed and was unit-tested in isolation while the production
publish path bypassed it — a contract consumers rely on, never exercised.

These tests drive the REAL writer (not a hand-built envelope) and emulate the
relay + bus round trip: the relay publishes the outbox row's ``payload`` / ``meta``
and the bus hands them back as parsed dicts. No database, no Redis.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.events.schemas import EVENT_TYPES, build_envelope, deserialize
from app.core.events.writer import add_outbox_event

# The real, closed set of outbox event types. Each pair is a live
# add_outbox_event(aggregate_type=..., event_type=...) call site in app/ —
# nothing here is invented.
REAL_EVENT_TYPES: tuple[tuple[str, str], ...] = (
    ("customer", "customer.merged"),
    ("customer", "privacy.customer_deleted"),
    ("message", "message.outbound"),
    ("message", "message.received"),
    ("notification", "notification.queued"),
    ("order", "order.cancelled"),
    ("order", "order.created"),
    ("order", "order.refunded"),
    ("order", "order.status_changed"),
    ("webhook", "webhook.deliver"),
)


def _magic_session() -> MagicMock:
    session = MagicMock()
    session.flush = AsyncMock()
    return session


async def _publish(**kwargs: Any) -> dict[str, Any]:
    """Run the real writer, then emulate the relay+bus handing fields back.

    Returns exactly what a consumer's ``Event.payload`` / ``Event.meta`` hold:
    the outbox row's payload / meta as parsed dicts.
    """
    session = _magic_session()
    event = await add_outbox_event(session, **kwargs)
    return {"payload": event.payload, "meta": event.meta}


async def test_published_outbox_event_round_trips_through_deserialize() -> None:
    """A real published event must rebuild via deserialize() — the headline."""
    tenant_id = uuid.uuid4()
    order_id = uuid.uuid4()

    fields = await _publish(
        aggregate_type="order",
        aggregate_id=order_id,
        event_type="order.created",
        tenant_id=tenant_id,
        payload={"order_id": str(order_id), "number": "SO-1"},
    )

    envelope = deserialize(fields)  # what a consumer actually calls

    assert envelope.type == "order.created"
    assert envelope.tenant_id == tenant_id
    assert envelope.aggregate_type == "order"
    assert envelope.aggregate_id == order_id
    assert envelope.payload["order_id"] == str(order_id)
    assert envelope.occurred_at is not None


async def test_published_meta_carries_envelope_routing_keys() -> None:
    tenant_id = uuid.uuid4()
    aggregate_id = uuid.uuid4()

    fields = await _publish(
        aggregate_type="order",
        aggregate_id=aggregate_id,
        event_type="order.created",
        tenant_id=tenant_id,
        payload={"order_id": str(aggregate_id)},
        meta={"source": "unit-test"},
    )
    meta = fields["meta"]

    assert meta["type"] == "order.created"
    assert meta["tenant_id"] == str(tenant_id)
    assert meta["aggregate_type"] == "order"
    assert meta["aggregate_id"] == str(aggregate_id)
    assert "occurred_at" in meta
    assert meta["version"] == 1
    # user meta survives alongside the routing keys
    assert meta["source"] == "unit-test"
    # the worker dedupe key survives
    assert "outbox_id" in meta


async def test_payload_keeps_event_type_key() -> None:
    """Workers route on payload["event_type"] (message_worker, platform_workers)."""
    fields = await _publish(
        aggregate_type="message",
        aggregate_id=uuid.uuid4(),
        event_type="message.outbound",
        tenant_id=uuid.uuid4(),
        payload={"message_id": "m-1"},
    )
    assert fields["payload"]["event_type"] == "message.outbound"
    assert fields["payload"]["message_id"] == "m-1"


async def test_sse_tenant_claim_survives_publication() -> None:
    """The SSE gateway filters frames on meta["tenant_id"] and fails CLOSED.

    If publication dropped the tenant claim, every frame would be silently
    discarded (fail-closed = no realtime); if it mislabelled the claim, the
    frame would cross tenants. Pin that the published claim equals the writer's
    tenant and that a different tenant is distinguishable.
    """
    tenant_id = uuid.uuid4()
    other_tenant = uuid.uuid4()

    fields = await _publish(
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=tenant_id,
    )

    published_tenant = str(fields["meta"].get("tenant_id", ""))
    assert published_tenant == str(tenant_id)
    assert published_tenant != str(other_tenant)
    # the envelope agrees with the transport meta the SSE path reads
    assert str(deserialize(fields).tenant_id) == published_tenant


@pytest.mark.parametrize(("aggregate_type", "event_type"), REAL_EVENT_TYPES)
async def test_every_real_event_type_publishes_and_round_trips(
    aggregate_type: str, event_type: str
) -> None:
    tenant_id = uuid.uuid4()
    fields = await _publish(
        aggregate_type=aggregate_type,
        aggregate_id=uuid.uuid4(),
        event_type=event_type,
        tenant_id=tenant_id,
    )

    assert event_type in EVENT_TYPES
    envelope = deserialize(fields)
    assert envelope.type == event_type
    assert envelope.tenant_id == tenant_id


def test_build_envelope_carries_v2_lineage() -> None:
    """The writer's lineage kwargs must reach the envelope, not be dropped."""
    envelope = build_envelope(
        "order.created",
        tenant_id=uuid.uuid4(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        correlation_id="corr-1",
        causation_id="cause-1",
        producer="orders-svc",
        schema_version=2,
        aggregate_version=3,
    )
    assert envelope.correlation_id == "corr-1"
    assert envelope.causation_id == "cause-1"
    assert envelope.producer == "orders-svc"
    assert envelope.schema_version == 2
    assert envelope.aggregate_version == 3
