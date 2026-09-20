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

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.events.bus import Event
from app.core.events.schemas import (
    EVENT_TYPES,
    build_envelope,
    deserialize,
    serialize,
)
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


# ---------------------------------------------------------------------------
# Finding 2 — the read half (deserialize) is exercised by real consumers
# ---------------------------------------------------------------------------


async def _published(**_kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Payload/meta of a real outbox row — exactly what the relay publishes."""
    row = await add_outbox_event(_magic_session(), **_kwargs)
    return row.payload, row.meta


def _wire_batch(
    stream: str, msg_id: str, payload: dict[str, Any], meta: dict[str, Any]
) -> list[Any]:
    """The Redis Streams reply shape the SSE gateway consumes."""
    return [
        (
            stream,
            [(msg_id, {"payload": json.dumps(payload), "meta": json.dumps(meta)})],
        )
    ]


class _BatchRedis:
    """``xread`` serves one batch, then nothing."""

    def __init__(self, batch: list[Any]) -> None:
        self._batch = batch
        self._served = False

    async def xread(self, **_kwargs: Any) -> list[Any] | None:
        if self._served:
            return None
        self._served = True
        return self._batch


class _OnePollRequest:
    """Disconnected after the first poll, so the generator runs exactly once."""

    def __init__(self) -> None:
        self._calls = 0

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > 1


async def _gateway_frames(
    monkeypatch: pytest.MonkeyPatch, tenant_id: uuid.UUID, batch: list[Any]
) -> list[bytes]:
    from app.modules.realtime import router as rt

    monkeypatch.setattr(rt, "get_redis", lambda: _BatchRedis(batch))
    frames: list[bytes] = []
    async for frame in rt._event_stream(
        tenant_id=str(tenant_id),
        user_id="u-1",
        streams=["order.events"],
        cursor=None,
        request=_OnePollRequest(),
    ):
        frames.append(frame)
    return frames


def _frame_data(frame: bytes) -> dict[str, Any]:
    line = next(
        ln for ln in frame.decode().split("\n") if ln.startswith("data:")
    )
    return json.loads(line[len("data:") :].strip())


async def test_sse_gateway_streams_a_frame_for_its_own_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tenant claim reaches the gateway and the frame is streamed."""
    tenant_id = uuid.uuid4()
    payload, meta = await _published(
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=tenant_id,
        payload={"order_id": "o-1", "grand_total": Decimal("76.50")},
    )

    frames = await _gateway_frames(
        monkeypatch, tenant_id, _wire_batch("order.events", "1-0", payload, meta)
    )

    assert len(frames) == 1
    data = _frame_data(frames[0])
    assert data["stream"] == "order.events"
    assert data["payload"]["event_type"] == "order.created"
    # money survives as the producer's Decimal; the SSE encoder renders it
    assert data["payload"]["grand_total"] == "76.50"


async def test_sse_gateway_refuses_a_frame_without_a_tenant_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail CLOSED: an event with no tenant claim must never reach a client."""
    payload, meta = await _published(
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=uuid.uuid4(),
        payload={"order_id": "o-1"},
    )
    meta.pop("tenant_id")

    frames = await _gateway_frames(
        monkeypatch, uuid.uuid4(), _wire_batch("order.events", "1-0", payload, meta)
    )

    assert frames == []


async def test_sse_gateway_refuses_a_frame_for_another_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, meta = await _published(
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=uuid.uuid4(),
        payload={"order_id": "o-1"},
    )

    frames = await _gateway_frames(
        monkeypatch, uuid.uuid4(), _wire_batch("order.events", "1-0", payload, meta)
    )

    assert frames == []


async def test_sse_gateway_refuses_a_partial_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 2: the gateway reads through deserialize(), so a partial envelope
    — the shape the old hand-parse tolerated (tenant_id only) — is refused
    instead of streamed."""
    tenant_id = uuid.uuid4()
    batch = _wire_batch(
        "order.events", "1-0", {"event_type": "order.created"}, {"tenant_id": str(tenant_id)}
    )

    frames = await _gateway_frames(monkeypatch, tenant_id, batch)

    assert frames == []


async def test_message_worker_refuses_a_partial_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 2: the worker reads the type + tenant through deserialize()."""
    from app.workers import message_worker as mw

    handled: list[Any] = []

    async def _spy(*args: Any) -> None:
        handled.append(args)

    monkeypatch.setattr(mw.MessageWorker, "_on_received", _spy)
    worker = mw.MessageWorker(bus=MagicMock())

    await worker.handle(
        Event(
            id="e-1",
            stream="message.events",
            payload={"event_type": "message.received", "conversation_id": "c-1"},
            meta={"tenant_id": str(uuid.uuid4())},  # partial: no routing keys
        )
    )

    assert handled == [], "a non-envelope event must not be dispatched"


class _NullResult:
    def scalar_one_or_none(self) -> None:
        return None


class _NullSession:
    async def __aenter__(self) -> _NullSession:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    def begin(self) -> _NullSession:
        return self

    async def execute(self, *_args: Any, **_kwargs: Any) -> _NullResult:
        return _NullResult()


async def test_notification_worker_refuses_a_partial_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 2: the platform worker reads the type + tenant through deserialize."""
    from app.workers import platform_workers as pw

    bound: list[Any] = []

    async def _spy_bind(session: Any, tenant_id: Any) -> None:
        bound.append(tenant_id)

    monkeypatch.setattr(pw, "bind_tenant", _spy_bind)
    monkeypatch.setattr(pw, "SessionLocal", _NullSession)
    worker = pw.NotificationWorker(bus=MagicMock())

    await worker.handle(
        Event(
            id="e-2",
            stream="notification.events",
            payload={"event_type": "notification.queued", "notification_id": "n-1"},
            meta={"tenant_id": str(uuid.uuid4())},  # partial: no routing keys
        )
    )

    assert bound == [], "a non-envelope event must not be processed"


async def test_relay_event_log_records_the_envelopes_own_occurred_at() -> None:
    """Finding 2: §152 replay history records the event's OWN instant
    (``meta['occurred_at']``), not the outbox row's DB ``created_at``."""
    from app.core.events.outbox import OutboxRelay

    tenant_id = uuid.uuid4()
    occurred_at = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    created_at = datetime(2020, 1, 1, tzinfo=UTC)  # the row's DB timestamp

    envelope = build_envelope(
        "order.created",
        tenant_id=tenant_id,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"order_id": "o-1"},
        occurred_at=occurred_at,
    )
    fields = serialize(envelope)
    payload = {"event_type": "order.created", **json.loads(fields["payload"])}
    meta = json.loads(fields["meta"])
    row = {
        "id": uuid.uuid4(),
        "aggregate_type": "order",
        "aggregate_id": envelope.aggregate_id,
        "created_at": created_at,
    }

    class _CapturingSession:
        def __init__(self) -> None:
            self.params: list[Any] = []

        async def execute(self, _statement: Any, params: Any = None) -> None:
            self.params.append(params)

    session = _CapturingSession()
    relay = OutboxRelay(bus=MagicMock())
    await relay._write_event_log(session, row, payload, meta)

    insert = next(p for p in session.params if p and "event_id" in p)
    assert insert["occurred_at"] == occurred_at
    assert insert["occurred_at"] != created_at
    assert insert["event_type"] == "order.created"
    assert insert["tenant_id"] == str(tenant_id)
