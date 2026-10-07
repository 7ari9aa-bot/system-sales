"""§176 gate scenario 22 — event schema compatibility, FOR REAL (§153).

The gate that stood here before asserted one thing: the outbox row's
``meta["schema_version"]`` is a positive integer. That claim cannot fail for
any event the writer produces, and it proves nothing §153 actually asks for:

    Event schema evolution: backward-compatible change -> allowed;
    breaking change -> new event/schema version.
    An OLD event must remain readable through a versioned consumer/adapter.

Compatibility is a property of the CONSUMER, so these tests exercise the real
read half (`deserialize` / `deserialize_event`) and the real relay legacy-row
completion (`OutboxRelay._envelope_for_log`) against wire shapes produced by
older versions of this code — hand-built, because a consumer must keep reading
what a producer wrote months ago. Nothing here mocks the rule under test; the
registry, the codec and the relay's own mapping all run for real.

No PostgreSQL needed: this file runs locally and in CI.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.core.events.bus import Event
from app.core.events.outbox import OutboxRelay
from app.core.events.schemas import (
    EVENT_TYPES,
    VERSIONED_EVENT_TYPES,
    EventEnvelope,
    build_envelope,
    deserialize,
    deserialize_event,
    serialize,
)

pytestmark = [pytest.mark.gate]

TYPE = "order.created"  # a real DOMAIN_EVENT_TYPES entry, published by orders
TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _row(**over: Any) -> dict[str, Any]:
    """The outbox row shape the relay reads (a plain mapping of columns)."""
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "stream": "order.events",
        "aggregate_type": "order",
        "aggregate_id": uuid.uuid4(),
        "created_at": datetime.now(UTC),
    }
    row.update(over)
    return row


# ---------------------------------------------------------------------------
# 1. An old event must stay readable once the consumer evolves
# ---------------------------------------------------------------------------


class OrderCreatedV2(EventEnvelope):
    """A consumer that grew a typed view for schema_version 2 only."""


def test_gate_a_v1_event_is_still_readable_after_the_consumer_adds_a_v2_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The v1 wire is produced BEFORE the adapter exists, read AFTER it."""
    monkeypatch.setitem(VERSIONED_EVENT_TYPES, (TYPE, 2), OrderCreatedV2)

    # Producer side: an event written last quarter (schema_version 1).
    v1 = build_envelope(
        TYPE,
        tenant_id=TENANT,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"grand_total": Decimal("76.50"), "number": "ORD-1"},
    )
    wire = serialize(v1)
    assert json.loads(wire["meta"])["schema_version"] == 1

    # Consumer side, now that a v2 adapter is registered for the same type.
    restored = deserialize({"payload": wire["payload"], "meta": wire["meta"]})

    assert type(restored) is EventEnvelope, (
        "a v1 event was routed into the v2 adapter — the old wire must be read "
        "through the base contract it was written against"
    )
    assert restored.schema_version == 1
    assert restored.payload["number"] == "ORD-1"
    assert restored.payload["grand_total"] == Decimal("76.50")


def test_gate_a_newer_wire_than_any_registered_adapter_uses_the_base_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown FUTURE version must never be read through an older adapter.

    Silently applying the v2 shape to a v3 payload is the misread this pins:
    the consumer must fall back to the permissive type-level contract, which
    is what keeps a producer rollout from breaking a not-yet-upgraded consumer.
    """
    monkeypatch.setitem(VERSIONED_EVENT_TYPES, (TYPE, 2), OrderCreatedV2)

    v3 = build_envelope(
        TYPE,
        tenant_id=TENANT,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        schema_version=3,
        payload={"grand_total": Decimal("10.00"), "new_field": "added later"},
    )
    restored = deserialize(serialize(v3))

    assert type(restored) is EventEnvelope
    assert restored.schema_version == 3
    assert restored.payload["new_field"] == "added later"


def test_gate_backward_compatible_field_addition_reads_both_wires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A narrowed contract with an OPTIONAL field reads old and new payloads."""

    class LineItem(BaseModel):
        variant_id: str
        qty: Decimal

    class OrderCreatedNarrowed(EventEnvelope):
        """Type-level contract evolved: payload typed, `note` optional."""

        class Payload(BaseModel):
            grand_total: Decimal
            number: str
            lines: list[LineItem] = []
            note: str | None = None

        payload: Payload  # type: ignore[assignment]

    monkeypatch.setitem(EVENT_TYPES, TYPE, OrderCreatedNarrowed)

    old_wire = {
        "payload": json.dumps(
            {"grand_total": "76.50", "number": "ORD-1"}  # pre-evolution: no lines/note
        ),
        "meta": json.dumps(
            {
                "type": TYPE,
                "tenant_id": str(TENANT),
                "occurred_at": "2026-01-01T00:00:00+00:00",
                "aggregate_type": "order",
                "aggregate_id": str(uuid.uuid4()),
                "schema_version": 1,
            }
        ),
    }
    restored = deserialize(old_wire)
    assert restored.payload.note is None
    assert restored.payload.lines == []
    assert restored.payload.grand_total == Decimal("76.50")

    new_wire = json.loads(json.dumps(old_wire))  # same shape, plus the new field
    new_payload = json.loads(new_wire["payload"])
    new_payload["note"] = "call before delivery"
    new_payload["lines"] = [{"variant_id": "v-1", "qty": "2"}]
    new_wire["payload"] = json.dumps(new_payload)

    evolved = deserialize(new_wire)
    assert evolved.payload.note == "call before delivery"
    assert evolved.payload.lines[0].qty == Decimal("2")


def test_gate_a_breaking_change_under_the_same_version_is_refused_not_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A REQUIRED field means the old wire is a breaking change, and the
    consumer says so loudly instead of substituting a default."""

    class OrderCreatedStrict(EventEnvelope):
        class Payload(BaseModel):
            amount_cents: int  # §153 says this needed a NEW schema_version

        payload: Payload  # type: ignore[assignment]

    monkeypatch.setitem(EVENT_TYPES, TYPE, OrderCreatedStrict)
    # The wire an OLD producer wrote (before `amount_cents` existed). Built by
    # hand, because the producer and the consumer share this registry: calling
    # build_envelope here would validate through the NEW class and never
    # produce the old shape.
    old_wire = {
        "payload": json.dumps({"event_type": TYPE, "grand_total": "76.50"}),
        "meta": json.dumps(
            {
                "type": TYPE,
                "tenant_id": str(TENANT),
                "occurred_at": "2026-01-01T00:00:00+00:00",
                "aggregate_type": "order",
                "aggregate_id": str(uuid.uuid4()),
                "schema_version": 1,
            }
        ),
    }

    with pytest.raises(PydanticValidationError):
        deserialize(old_wire)


def test_gate_an_unregistered_type_is_rejected_by_both_halves() -> None:
    """Fail closed: an unknown event type is never decoded into something loose."""
    with pytest.raises(ValidationError):
        build_envelope(
            "not.a.registered.type",
            tenant_id=TENANT,
            aggregate_type="x",
            aggregate_id=uuid.uuid4(),
        )
    with pytest.raises(ValidationError):
        deserialize(
            {
                "payload": "{}",
                "meta": json.dumps(
                    {
                        "type": "not.a.registered.type",
                        "tenant_id": str(TENANT),
                        "occurred_at": "2026-01-01T00:00:00+00:00",
                        "aggregate_type": "x",
                        "aggregate_id": str(uuid.uuid4()),
                    }
                ),
            }
        )


# ---------------------------------------------------------------------------
# 2. Money and the JSON boundary (money is NUMERIC(14,2), string on the wire)
# ---------------------------------------------------------------------------


def test_gate_money_crosses_the_wire_as_a_string_and_returns_as_decimal() -> None:
    """`float` would be the corruption; the wire must stay textual."""
    envelope = build_envelope(
        TYPE,
        tenant_id=TENANT,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={
            "grand_total": Decimal("1234.56"),
            "nested": {"refund": Decimal("-0.01")},
            "list": [Decimal("99.99")],
        },
    )
    wire = serialize(envelope)

    payload_json = json.loads(wire["payload"])  # must be valid JSON...
    assert payload_json["grand_total"] == {
        "__event_value__": "decimal",
        "value": "1234.56",
    }
    assert payload_json["nested"]["refund"]["value"] == "-0.01"
    assert payload_json["list"][0]["value"] == "99.99"
    assert "1234.56" in wire["payload"]  # textual, never 1234.5 or 1234.5600000001
    assert "e-" not in wire["payload"].lower()  # no float exponents on the wire

    restored = deserialize(wire)
    assert restored.payload["grand_total"] == Decimal("1234.56")
    assert isinstance(restored.payload["grand_total"], Decimal)
    assert isinstance(restored.payload["nested"]["refund"], Decimal)
    assert restored.payload["list"] == [Decimal("99.99")]


def test_gate_a_pre_tag_legacy_row_still_deserializes() -> None:
    """Rows written before the type-tagging codec exist hold plain strings.

    The encoding is additive, so no migration was needed — which is only true
    if the consumer still reads them. It reads them as strings (no silent
    Decimal invention), and the event stays processable.
    """
    legacy_wire = {
        "payload": json.dumps({"event_type": TYPE, "grand_total": "76.50"}),
        "meta": json.dumps(
            {
                "id": str(uuid.uuid4()),
                "type": TYPE,
                "version": 1,
                "tenant_id": str(TENANT),
                "occurred_at": "2026-01-01T00:00:00+00:00",
                "aggregate_type": "order",
                "aggregate_id": str(uuid.uuid4()),
            }
        ),
    }
    restored = deserialize(legacy_wire)

    assert restored.schema_version == 1  # defaulted, not rejected
    assert restored.aggregate_version is None
    assert restored.correlation_id is None
    assert restored.payload["grand_total"] == "76.50"  # string, as written


def test_gate_the_full_envelope_round_trips_through_the_consumer_read_half() -> None:
    """A worker receives an `Event` with parsed dicts — the real read path."""
    correlation, causation = uuid.uuid4(), uuid.uuid4()
    envelope = build_envelope(
        TYPE,
        tenant_id=TENANT,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        payload={"grand_total": Decimal("76.50")},
        correlation_id=str(correlation),
        causation_id=str(causation),
        producer="orders",
        schema_version=2,
        aggregate_version=7,
    )
    wire = serialize(envelope)
    received = Event(
        id=wire["id"] if "id" in wire else str(uuid.uuid4()),
        stream="order.events",
        payload=json.loads(wire["payload"]),
        meta=json.loads(wire["meta"]),
    )

    restored = deserialize_event(received)

    assert isinstance(restored.payload["grand_total"], Decimal)
    assert restored.workspace_id == envelope.workspace_id
    assert restored.correlation_id == str(correlation)
    assert restored.causation_id == str(causation)
    assert restored.producer == "orders"
    assert (restored.schema_version, restored.aggregate_version) == (2, 7)
    assert restored.occurred_at == envelope.occurred_at


# ---------------------------------------------------------------------------
# 3. The relay is the first consumer of an OLD row: legacy completion, not guess
# ---------------------------------------------------------------------------


class _NoBus:
    async def publish(self, *a: Any, **k: Any) -> str:  # pragma: no cover
        raise AssertionError("this gate never publishes")


def test_gate_a_legacy_outbox_row_still_builds_its_envelope() -> None:
    """Pre-envelope rows carry only what the old writer stamped.

    §152/§153: the relay must complete them from the row's own columns instead
    of dropping the replay history — and must NOT invent a tenant.
    """
    relay = OutboxRelay(_NoBus())  # type: ignore[arg-type]
    aggregate_id = uuid.uuid4()
    row = _row(aggregate_id=aggregate_id)
    legacy_meta = {"tenant_id": str(TENANT), "outbox_id": str(row["id"])}
    legacy_payload = {"event_type": "order.created", "grand_total": "76.50"}

    envelope = relay._envelope_for_log(row, legacy_payload, legacy_meta)

    assert envelope is not None
    assert envelope.type == "order.created"  # completed from the payload
    assert envelope.aggregate_type == "order"  # completed from the columns
    assert envelope.aggregate_id == aggregate_id
    assert envelope.tenant_id == TENANT
    assert envelope.schema_version == 1
    assert envelope.occurred_at is not None  # never left null on the way to history


def test_gate_a_row_without_a_tenant_is_never_replayed_under_someone_elses() -> None:
    """event_log is RLS-guarded: no tenant claim means no history, not a guess."""
    relay = OutboxRelay(_NoBus())  # type: ignore[arg-type]
    row = _row()
    envelope = relay._envelope_for_log(
        row, {"event_type": "order.created"}, {"outbox_id": str(row["id"])}
    )
    assert envelope is None


def test_gate_a_current_row_is_read_through_the_same_mapping_as_its_producer() -> None:
    """One field mapping in the system: what the writer stamped, the relay reads."""
    relay = OutboxRelay(_NoBus())  # type: ignore[arg-type]
    envelope = build_envelope(
        TYPE,
        tenant_id=TENANT,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"grand_total": Decimal("76.50")},
        aggregate_version=3,
    )
    wire = serialize(envelope)
    row = _row()

    rebuilt = relay._envelope_for_log(row, json.loads(wire["payload"]), json.loads(wire["meta"]))

    assert rebuilt is not None
    assert rebuilt.id == envelope.id
    assert rebuilt.tenant_id == TENANT
    assert rebuilt.aggregate_version == 3
    assert rebuilt.payload["grand_total"] == Decimal("76.50")
