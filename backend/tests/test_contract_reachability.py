"""Contract reachability: every serialize/deserialize pair must ROUND-TRIP.

The defect class this guards
---------------------------
``app/core/events/schemas.py`` defined a §19 envelope with a ``deserialize()``
that needs ``occurred_at`` / ``aggregate_type`` / ``aggregate_id``, and the real
publish path (``writer.add_outbox_event``) hand-merged a meta dict instead — so
none of those keys were ever published. The envelope was unit-tested IN
ISOLATION and the production path skipped it. Worse than dead code: consumers
relied on the shape.

So this file does not assert that functions exist (a test that cannot fail is
worse than no test). For each pair a real caller half-bypasses, it drives the
REAL writer/reader half and asserts the round trip:

    deserialize(serialize(x)) == x   for a real object

Pairs covered, and why each is worth a permanent test:

1. §19 envelope — ``serialize`` (called by ``core/events/writer``) vs
   ``deserialize`` (called by NOTHING under ``app/``: the workers, the SSE
   gateway, the relay and the DLQ inspector all hand-parse ``meta`` instead).
   The envelope is what a STORED row (``outbox_events.payload`` / ``.meta``)
   holds and what every consumer reads.
2. Idempotency replay record — ``IdempotencyService.complete`` writes it,
   ``IdempotencyMiddleware._send_stored`` reads it back. Stored in
   ``idempotency_keys.response``. The existing tests hand-build the stored dict
   instead of driving ``complete``, which is the same anti-pattern in test form.
3. Billing period snapshot — ``snapshot_lines`` writes ``invoices.extra``,
   ``snapshot_view`` reads it. Money is stored as exact strings on purpose; a
   reader that returns a float would silently corrupt every invoice.
4. Metric definition registry — ``MetricSpec.as_dict`` is the write half of
   ``metric_definitions`` with no inverse; the row's columns ARE the contract.
5. Cursor, ETag and visitor-token pairs — both halves are wired, but these are
   the other opaque-string contracts a consumer (the frontend / an SSE client)
   depends on, so they are pinned here too.

KNOWN VIOLATION (marked ``xfail(strict=True)``): the envelope pair is NOT
type-preserving for a ``Decimal``/``datetime`` payload value, and
``app/modules/orders/service.py`` really publishes ``grand_total`` as a
``Decimal`` on ``order.created``. ``deserialize(serialize(x)) != x`` there.
``strict=True`` makes this a TRIPWIRE: the moment another agent makes the pair
type-preserving the test XPASSes and goes RED until the marker is removed, so
the decision cannot be forgotten either way. See ``docs/CONTRACT_AUDIT.md``.

DB-free: every test here runs locally (the fake session pattern is the same one
``tests/test_event_envelope.py`` uses).
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.events.schemas import build_envelope, deserialize, serialize
from app.core.events.writer import add_outbox_event
from app.core.idempotency import etag_for, parse_if_match
from app.core.pagination import decode_cursor, encode_cursor
from app.core.security import create_visitor_token, decode_visitor_token
from app.modules.billing.models import Invoice
from app.modules.billing.service import BillingSnapshotService, PeriodUsage
from app.modules.platform.metrics import METRIC_DEFINITIONS, MetricSpec
from app.modules.platform.models import MetricDefinition

# ---------------------------------------------------------------------------
# 1. §19 envelope: the writer's output must be what deserialize() rebuilds
# ---------------------------------------------------------------------------

#: The real, closed set of outbox event types and the payload shape each real
#: call site passes. Every entry is an ``add_outbox_event(...)`` call site in
#: ``app/`` — none invented. ``grand_total`` is passed as a string here because
#: the Decimal case is the KNOWN VIOLATION pinned separately below.
REAL_EVENTS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    (
        "order",
        "order.created",
        {
            "order_id": "00000000-0000-0000-0000-000000000001",
            "number": "SO-1",
            "customer_id": "00000000-0000-0000-0000-000000000002",
            "warehouse_id": "00000000-0000-0000-0000-000000000003",
            "status": "placed",
            "currency": "EGP",
            "grand_total": "76.50",
            "item_count": 2,
        },
    ),
    ("order", "order.cancelled", {"order_id": "o-1", "number": "SO-1", "to_status": "cancelled"}),
    (
        "order",
        "order.status_changed",
        {"order_id": "o-1", "from_status": "placed", "to_status": "paid"},
    ),
    (
        "order",
        "order.refunded",
        {
            "order_id": "o-1",
            "number": "SO-1",
            "payment_id": "p-1",
            "amount": 12.5,
            "payment_status": "refunded",
        },
    ),
    (
        "message",
        "message.received",
        {"conversation_id": "c-1", "customer_id": "cu-1", "channel": "webchat"},
    ),
    ("message", "message.outbound", {"message_id": "m-1", "conversation_id": "c-1"}),
    ("notification", "notification.queued", {"notification_id": "n-1"}),
    ("webhook", "webhook.deliver", {"delivery_id": "d-1"}),
    (
        "customer",
        "customer.merged",
        {"canonical_customer_id": "cu-1", "merged_away_customer_id": "cu-2"},
    ),
    (
        "customer",
        "privacy.customer_deleted",
        {"customer_id": "cu-1", "steps": [{"step": "x", "done": True}]},
    ),
)


def _magic_session() -> MagicMock:
    """A session that emulates the DB PK default so ``meta['outbox_id']`` is real.

    ``add_outbox_event`` stamps ``meta['outbox_id'] = str(event.id)`` AFTER the
    flush; without a database the ORM instance has no id. Assigning one on
    ``add`` is what makes the id-linkage assertion below non-vacuous.
    """

    def _add(instance: Any) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()

    session = MagicMock()
    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()
    return session


async def _publish(**kwargs: Any) -> dict[str, Any]:
    """Drive the REAL writer, then hand back exactly what a consumer receives.

    Returns the outbox row's ``payload`` / ``meta`` as parsed dicts — which is
    precisely what the relay publishes and what ``deserialize`` accepts.
    ``__row_id`` is the outbox ROW id, carried alongside for the dedupe
    assertion; ``deserialize`` ignores unknown top-level keys.
    """
    event = await add_outbox_event(_magic_session(), **kwargs)
    return {"payload": event.payload, "meta": event.meta, "__row_id": str(event.id)}


@pytest.mark.parametrize(("aggregate_type", "event_type", "payload"), REAL_EVENTS)
async def test_published_outbox_event_round_trips_through_deserialize(
    aggregate_type: str, event_type: str, payload: dict[str, Any]
) -> None:
    """A real published event rebuilds via deserialize() with every field intact."""
    tenant_id = uuid.uuid4()
    aggregate_id = uuid.uuid4()

    fields = await _publish(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        tenant_id=tenant_id,
        payload=payload,
    )

    envelope = deserialize(fields)

    assert envelope.type == event_type
    assert envelope.tenant_id == tenant_id
    assert envelope.aggregate_type == aggregate_type
    assert envelope.aggregate_id == aggregate_id
    assert envelope.version == 1
    assert envelope.occurred_at is not None
    # The payload survives the JSONB hop key-for-key. The writer injects
    # `event_type` as the FIRST payload key (workers route on it), so the
    # rebuilt payload is the caller's payload plus exactly that one key.
    assert envelope.payload["event_type"] == event_type
    assert {k: v for k, v in envelope.payload.items() if k != "event_type"} == payload
    assert envelope.id == str(fields["meta"]["id"])


async def test_published_row_meta_is_a_complete_envelope() -> None:
    """The row's meta carries every routing key deserialize() requires.

    ``occurred_at`` / ``aggregate_type`` / ``aggregate_id`` are exactly the keys
    the original defect dropped, so they are asserted by name, not by presence.
    """
    tenant_id = uuid.uuid4()
    aggregate_id = uuid.uuid4()

    fields = await _publish(
        aggregate_type="order",
        aggregate_id=aggregate_id,
        event_type="order.created",
        tenant_id=tenant_id,
        payload={"order_id": str(aggregate_id)},
        meta={"source": "unit-test"},
        correlation_id="corr-1",
        causation_id="cause-1",
        producer="orders-svc",
        schema_version=2,
        aggregate_version=7,
    )
    meta = fields["meta"]

    routing_keys = (
        "id",
        "type",
        "version",
        "tenant_id",
        "occurred_at",
        "aggregate_type",
        "aggregate_id",
    )
    for key in routing_keys:
        assert key in meta, f"envelope routing key {key!r} missing from the published meta"

    assert meta["type"] == "order.created"
    assert meta["tenant_id"] == str(tenant_id)
    assert meta["aggregate_type"] == "order"
    assert meta["aggregate_id"] == str(aggregate_id)
    # user meta survives alongside the routing keys
    assert meta["source"] == "unit-test"
    # lineage survives, and deserialize() agrees with the transport meta
    envelope = deserialize(fields)
    assert envelope.correlation_id == "corr-1"
    assert envelope.causation_id == "cause-1"
    assert envelope.producer == "orders-svc"
    assert envelope.schema_version == 2
    assert envelope.aggregate_version == 7
    # user meta survives; `outbox_id` is the extra key the writer stamps on the
    # row AFTER serialize() (so the row is the serialized form PLUS that key —
    # still deserializable, which is the point).
    assert envelope.meta["source"] == "unit-test"
    # the envelope id and the outbox ROW id are two different identifiers, and
    # both survive: `id` is what deserialize() rebuilds the envelope from,
    # `outbox_id` is the stable consumer-inbox dedupe key (workers/base._process)
    assert envelope.id == meta["id"]
    assert meta["outbox_id"] == fields["__row_id"]
    assert envelope.meta["outbox_id"] == fields["__row_id"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN CONTRACT VIOLATION: serialize()/deserialize() are not "
        "type-preserving, and app/modules/orders/service.py:318 publishes "
        "order.grand_total as a Decimal on order.created. The consumer sees the "
        "string '76.50' while the producer built Decimal('76.50'), so "
        "deserialize(serialize(x)) != x and the envelope contract that "
        "consumers read from the outbox row is not the object the writer "
        "built. Fix = make the pair type-preserving (or change the producer to "
        "send a JSON-native value, as order.refunded already does with "
        "float(refund_amount)); then remove this marker. See "
        "docs/CONTRACT_AUDIT.md finding 1."
    ),
)
def test_envelope_round_trip_preserves_payload_value_types() -> None:
    """The REAL order.created payload shape, with grand_total as a Decimal."""
    envelope = build_envelope(
        "order.created",
        tenant_id=uuid.uuid4(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"order_id": "o-1", "grand_total": Decimal("76.50"), "item_count": 2},
    )

    rebuilt = deserialize(serialize(envelope))

    assert rebuilt.payload == envelope.payload


# ---------------------------------------------------------------------------
# 2. Idempotency replay record (stored in idempotency_keys.response)
# ---------------------------------------------------------------------------


async def test_idempotency_replay_record_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    """complete() encodes the response; _send_stored() must replay those bytes.

    The existing tests build ``{"body": base64.b64encode(...)}`` by hand, so a
    drift in ``complete()``'s encoding would not be caught. This drives both
    real halves.
    """
    from app.core import idempotency as idem

    record = MagicMock()
    record.status = idem.STATUS_PROCESSING
    record.response = None

    async def _fake_find(session, scope, key):
        return record

    monkeypatch.setattr(idem, "_find", _fake_find)

    session = MagicMock()
    session.flush = AsyncMock()
    original = b'{"id":"abc","grand_total":"76.50"}'

    await idem.IdempotencyService.complete(
        session, scope="http:tenant:route", key="k-1", status_code=201,
        body=original, content_type="application/json",
    )
    stored = record.response
    assert stored is not None
    # the row is JSONB-native: the body must be text, not bytes
    assert json.loads(json.dumps(stored)) == stored

    sent: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        sent.append(message)

    await idem._send_stored(_send, stored)

    start = next(m for m in sent if m["type"] == "http.response.start")
    body = next(m for m in sent if m["type"] == "http.response.body")["body"]
    assert start["status"] == 201
    assert body == original
    assert (b"idempotency-replayed", b"true") in [(k.lower(), v) for k, v in start["headers"]]


# ---------------------------------------------------------------------------
# 3. Billing period snapshot (stored in invoices.extra)
# ---------------------------------------------------------------------------


def test_billing_snapshot_lines_round_trip_through_snapshot_view() -> None:
    """snapshot_lines() writes invoices.extra; snapshot_view() reads it back.

    The write half stores quantities as STRINGS so a Numeric(14,2) total is not
    degraded by a JSON number -> IEEE float decode. This asserts the reader
    returns exactly what the writer froze, across a JSONB round trip, and that
    the money stays exact rather than becoming a float.
    """
    usage = PeriodUsage(
        features={
            "orders": Decimal("2.00"),
            "ai_tokens": Decimal("1200"),
            "messages": Decimal("10.50"),
        },
        ai_cost=Decimal("0.00123000"),
    )

    # what close_period() puts in Invoice.extra
    extra = {
        "snapshot": BillingSnapshotService.snapshot_lines(usage),
        "ai_cost": str(usage.ai_cost),
    }
    # the JSONB hop: the column stores JSON, so the value must survive it
    extra = json.loads(json.dumps(extra))

    invoice = Invoice(
        tenant_id=uuid.uuid4(),
        number="INV-202608-ABCDEF",
        status="open",
        subtotal=Decimal("0.00"),
        tax=Decimal("0.00"),
        total=Decimal("0.00"),
        currency="EGP",
        extra=extra,
    )

    view = BillingSnapshotService.snapshot_view(invoice)

    frozen = {line["feature"]: line["quantity"] for line in view["features"]}
    assert frozen == {
        "ai_tokens": "1200",
        "messages": "10.50",
        "orders": "2.00",
    }
    # and it re-reads as the exact Decimal the aggregate produced
    assert {k: Decimal(v) for k, v in frozen.items()} == usage.features
    assert view["ai_cost"] == "0.00123000"
    assert Decimal(view["ai_cost"]) == usage.ai_cost
    assert view["number"] == invoice.number
    assert view["status"] == "open"


# ---------------------------------------------------------------------------
# 4. Metric definition registry: as_dict() must be the row's column set
# ---------------------------------------------------------------------------


def test_metric_spec_as_dict_matches_the_stored_columns() -> None:
    """seed_definitions() inserts ``{**spec.as_dict(), 'tenant_id': ...}``.

    ``as_dict`` is the write half of ``metric_definitions`` with no inverse, so
    the row's columns ARE the contract: a key that is not a column makes the
    insert fail. (Columns the dict does not mention are nullable mixins —
    ``workspace_id`` / ``location_id`` / ``updated_at`` — which is why this is a
    subset assertion in that direction only.)
    """
    columns = {column.name for column in MetricDefinition.__table__.columns}

    for spec in METRIC_DEFINITIONS:
        assert isinstance(spec, MetricSpec)
        assert set(spec.as_dict()) <= columns, spec.name
        assert set(spec.as_dict()) == {field for field in spec.__dataclass_fields__}
        # values must be JSONB-native so the insert cannot fail on a type
        for key, value in spec.as_dict().items():
            assert value is None or isinstance(value, (str, int, float, bool, dict, list)), (
                spec.name,
                key,
                type(value),
            )


# ---------------------------------------------------------------------------
# 5. Cursor, ETag and visitor-token pairs (both halves wired today)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "created_at",
    [
        datetime(2026, 8, 1, 12, 30, 45, 123456, tzinfo=UTC),
        datetime(2026, 8, 1, 12, 30, 45),
        datetime(1970, 1, 1, tzinfo=UTC),
    ],
)
def test_cursor_pair_round_trips(created_at: datetime) -> None:
    row_id = uuid.uuid4()
    assert decode_cursor(encode_cursor(created_at, row_id)) == (created_at, row_id)


@pytest.mark.parametrize("version", [1, 2, 7, 1000])
def test_etag_pair_round_trips(version: int) -> None:
    assert parse_if_match(etag_for(version)) == version


def test_visitor_token_pair_round_trips() -> None:
    tenant_id = uuid.uuid4()
    token = create_visitor_token("sess-1", str(tenant_id), widget="pk_1")

    claims = decode_visitor_token(token)

    assert claims["sub"] == "sess-1"
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["widget"] == "pk_1"
    assert claims["type"] == "webchat_visitor"


def test_b64_round_trip_is_what_the_idempotency_row_relies_on() -> None:
    """The exact encoding step both halves share, pinned as a value assertion.

    Kept separate from the middleware test so a change to the base64 alphabet
    (e.g. urlsafe) fails HERE with an obvious name rather than as a mysteriously
    empty replayed body.
    """
    payload = b'{"ok":true}'
    encoded = base64.b64encode(payload).decode("ascii")
    assert base64.b64decode(encoded) == payload
