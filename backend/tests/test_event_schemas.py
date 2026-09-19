"""Event envelope build / serialize / deserialize tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from app.core.errors import DomainError
from app.core.events.schemas import (
    EVENT_TYPES,
    EventEnvelope,
    build_envelope,
    deserialize,
    register_event,
    serialize,
)


class OrderCreatedPayload(BaseModel):
    order_id: str
    total: float


@register_event("test.order.created")
class OrderCreated(EventEnvelope):
    payload: OrderCreatedPayload


@pytest.fixture
def tenant_id() -> UUID:
    return uuid4()


def test_build_envelope_sets_defaults_and_validates_payload(tenant_id: UUID) -> None:
    before = datetime.now(UTC)
    envelope = build_envelope(
        "test.order.created",
        tenant_id=tenant_id,
        aggregate_type="order",
        aggregate_id=uuid4(),
        payload={"order_id": "o-1", "total": 42.5},
    )
    after = datetime.now(UTC)

    assert envelope.version == 1
    assert envelope.type == "test.order.created"
    assert UUID(envelope.id)  # default id is a uuid4 string
    assert before <= envelope.occurred_at <= after
    assert envelope.payload == OrderCreatedPayload(order_id="o-1", total=42.5)
    assert envelope.payload.order_id == "o-1"  # narrowed to the typed payload model
    assert envelope.meta == {}


def test_unregistered_event_type_rejected(tenant_id: UUID) -> None:
    with pytest.raises(DomainError) as excinfo:
        build_envelope(
            "nope.not_registered",
            tenant_id=tenant_id,
            aggregate_type="widget",
            aggregate_id=uuid4(),
        )
    assert excinfo.value.details["event_type"] == "nope.not_registered"
    assert "nope.not_registered" not in EVENT_TYPES


def test_serialize_round_trip(tenant_id: UUID) -> None:
    aggregate_id = uuid4()
    occurred = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    envelope = build_envelope(
        "test.order.created",
        tenant_id=tenant_id,
        aggregate_type="order",
        aggregate_id=aggregate_id,
        payload={"order_id": "o-9", "total": 7.0},
        meta={"trace_id": "abc"},
        occurred_at=occurred,
    )

    fields = serialize(envelope)
    assert set(fields) == {"payload", "meta"}
    assert all(isinstance(value, str) for value in fields.values())

    meta = json.loads(fields["meta"])
    assert meta["type"] == "test.order.created"
    assert meta["tenant_id"] == str(tenant_id)
    assert meta["version"] == 1
    assert meta["aggregate_type"] == "order"
    assert meta["aggregate_id"] == str(aggregate_id)
    assert json.loads(fields["payload"]) == {"order_id": "o-9", "total": 7.0}

    rebuilt = deserialize(fields)
    assert rebuilt.id == envelope.id
    assert rebuilt.type == envelope.type
    assert rebuilt.version == envelope.version
    assert rebuilt.tenant_id == envelope.tenant_id
    assert rebuilt.occurred_at == envelope.occurred_at
    assert rebuilt.aggregate_type == "order"
    assert rebuilt.aggregate_id == aggregate_id
    assert rebuilt.payload == OrderCreatedPayload(order_id="o-9", total=7.0)
    assert rebuilt.meta == {"trace_id": "abc"}  # routing keys stay out of user meta


def test_lineage_fields_survive_round_trip(tenant_id: UUID) -> None:
    register_event("test.lineage")(EventEnvelope)
    envelope = EventEnvelope(
        type="test.lineage",
        tenant_id=tenant_id,
        aggregate_type="order",
        aggregate_id=uuid4(),
        correlation_id="corr-1",
        causation_id="cause-1",
        producer="orders",
        schema_version=3,
        aggregate_version=7,
    )

    rebuilt = deserialize(serialize(envelope))

    assert rebuilt.correlation_id == "corr-1"
    assert rebuilt.causation_id == "cause-1"
    assert rebuilt.producer == "orders"
    assert rebuilt.schema_version == 3
    assert rebuilt.aggregate_version == 7


def test_deserialize_accepts_parsed_bus_fields(tenant_id: UUID) -> None:
    envelope = build_envelope(
        "test.order.created",
        tenant_id=tenant_id,
        aggregate_type="order",
        aggregate_id=uuid4(),
        payload={"order_id": "o-2", "total": 1.0},
    )
    fields = serialize(envelope)
    parsed = {"payload": json.loads(fields["payload"]), "meta": json.loads(fields["meta"])}

    rebuilt = deserialize(parsed)
    assert rebuilt.id == envelope.id
    assert rebuilt.payload == envelope.payload


def test_free_form_payload_envelope_round_trip(tenant_id: UUID) -> None:
    # the bare envelope class stays registered as-is: free-form dict payload
    register_event("test.ping")(EventEnvelope)
    envelope = build_envelope(
        "test.ping",
        tenant_id=tenant_id,
        aggregate_type="ping",
        aggregate_id=uuid4(),
        payload={"k": "v"},
        meta={"seq": 1},
    )

    rebuilt = deserialize(serialize(envelope))
    assert rebuilt.payload == {"k": "v"}
    assert rebuilt.meta == {"seq": 1}


def test_deserialize_unregistered_type_rejected() -> None:
    with pytest.raises(DomainError):
        deserialize({"payload": "{}", "meta": json.dumps({"type": "nope"})})


def test_duplicate_registration_rejected() -> None:
    with pytest.raises(ValueError, match="already registered"):

        @register_event("test.order.created")
        class Duplicate(EventEnvelope):
            pass


def test_re_registering_same_class_is_idempotent() -> None:
    register_event("test.order.created")(OrderCreated)
    assert EVENT_TYPES["test.order.created"] is OrderCreated
