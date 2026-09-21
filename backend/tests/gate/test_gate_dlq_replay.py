"""§176 gate scenario 14 — DLQ replay (§24).

§24 promises that a dead-lettered message "does not disappear": the original
payload is kept and an operator can inspect it and replay it. Until now the
inspector's `requeue` had no test that drove a real event through the runtime:
fail -> DLQ -> inspect -> requeue -> handled.

Everything here runs against a REAL Redis (the bus is the thing under test), on
unique stream names that are deleted afterwards. It does not need PostgreSQL:
failures used are `PermanentError`, which dead-letters immediately and therefore
never touches the durable-retry outbox path.

Skips loudly when no Redis is reachable rather than erroring.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.events.bus import DLQ_SUFFIX, Event, RedisStreamsBus
from app.core.events.schemas import build_envelope, serialize
from app.workers.base import PermanentError, StreamWorker
from app.workers.inspector import list_dlq, requeue

pytestmark = [pytest.mark.gate]


@pytest.fixture
async def redis_client():
    client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        await client.aclose()
        pytest.skip(f"no Redis reachable at {get_settings().redis_url}: {exc}")
    yield client
    await client.aclose()


@pytest.fixture
async def stream(redis_client):
    name = f"gate-dlq-{uuid.uuid4().hex[:10]}.events"
    yield name
    await redis_client.delete(name, name + DLQ_SUFFIX)


class FlakyWorker(StreamWorker):
    """A consumer whose handler can be switched between failing and working."""

    name = "gate-dlq-worker"
    group = "gate-dlq-group"

    def __init__(self, bus: RedisStreamsBus, stream: str) -> None:
        super().__init__(bus)
        self.stream = stream
        self.broken = True
        self.handled: list[dict[str, Any]] = []

    async def handle(self, event: Event) -> None:
        if self.broken:
            raise PermanentError("downstream rejected the payload")
        self.handled.append(event.payload)


def _envelope_fields() -> tuple[dict[str, Any], dict[str, Any]]:
    """A genuine §19 envelope, in the shape the relay would publish."""
    envelope = build_envelope(
        "order.created",
        tenant_id=uuid.uuid4(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"number": "ORD-1042", "total": "250.00"},
    )
    wire = serialize(envelope)
    meta = json.loads(wire["meta"])
    meta["outbox_id"] = str(uuid.uuid4())  # the stable consumer-dedupe key
    return json.loads(wire["payload"]), meta


async def _next_event(bus: RedisStreamsBus, stream: str, group: str) -> Event:
    agen = bus.consume(stream, group, "gate-consumer", block_ms=200)
    try:
        return await asyncio.wait_for(agen.__anext__(), timeout=5)
    finally:
        await agen.aclose()


async def _pending(client, stream: str, group: str) -> int:
    return (await client.xpending(stream, group))["pending"]


async def _dead_letter_one(bus, worker, stream, payload, meta) -> None:
    await bus.publish(stream, payload, meta)
    await worker._process(await _next_event(bus, stream, worker.group))


async def test_gate_dead_letter_keeps_payload_and_is_inspectable(redis_client, stream):
    bus = RedisStreamsBus(redis_client)
    worker = FlakyWorker(bus, stream)
    payload, meta = _envelope_fields()

    await _dead_letter_one(bus, worker, stream, payload, meta)

    # The source entry was acked (the group keeps moving) …
    assert await _pending(redis_client, stream, worker.group) == 0
    # … and the message is NOT gone: it sits in the DLQ with its reason.
    entries = await list_dlq(redis_client, stream + DLQ_SUFFIX)
    assert len(entries) == 1
    [item] = entries
    assert item["envelope"] is True
    assert item["type"] == "order.created"
    assert item["payload"] == payload  # original payload preserved (§24)
    assert item["meta"]["dlq_reason"] == "permanent failure"
    assert item["meta"]["source_stream"] == stream
    assert worker.handled == []


async def test_gate_replay_processes_once_and_empties_the_dlq(redis_client, stream):
    bus = RedisStreamsBus(redis_client)
    worker = FlakyWorker(bus, stream)
    payload, meta = _envelope_fields()
    await _dead_letter_one(bus, worker, stream, payload, meta)
    dlq = stream + DLQ_SUFFIX
    [entry] = await list_dlq(redis_client, dlq)

    # The operator fixes the cause, then replays.
    worker.broken = False
    assert await requeue(redis_client, dlq, entry["entry_id"]) is True

    assert await redis_client.xlen(dlq) == 0
    await worker._process(await _next_event(bus, stream, worker.group))

    assert worker.handled == [payload], "the replayed event must be handled exactly once"
    assert await _pending(redis_client, stream, worker.group) == 0
    assert await redis_client.xlen(dlq) == 0

    # Replaying the same entry again is a harmless no-op, not a second delivery.
    assert await requeue(redis_client, dlq, entry["entry_id"]) is False
    assert await redis_client.xlen(dlq) == 0


async def test_gate_replay_that_fails_again_returns_to_dlq_not_lost(redis_client, stream):
    """A replay before the cause is fixed must not loop forever or vanish."""
    bus = RedisStreamsBus(redis_client)
    worker = FlakyWorker(bus, stream)  # stays broken
    payload, meta = _envelope_fields()
    await _dead_letter_one(bus, worker, stream, payload, meta)
    dlq = stream + DLQ_SUFFIX
    [entry] = await list_dlq(redis_client, dlq)

    assert await requeue(redis_client, dlq, entry["entry_id"]) is True
    await worker._process(await _next_event(bus, stream, worker.group))

    again = await list_dlq(redis_client, dlq)
    assert len(again) == 1, "the event must be back in the DLQ exactly once"
    assert again[0]["payload"] == payload
    assert await redis_client.xlen(stream) >= 1
    assert await _pending(redis_client, stream, worker.group) == 0
    assert worker.handled == []


async def test_gate_legacy_non_envelope_entry_is_listed_and_replayable(redis_client, stream):
    """The inspector must show what is stuck even when it is not a §19 envelope.

    Production `outbox_events` contains pre-envelope rows, so a DLQ entry that
    `deserialize()` rejects has to be listed from its raw fields (not crash the
    tool an operator reaches for during an incident) and still be requeueable.
    """
    dlq = stream + DLQ_SUFFIX
    await redis_client.xadd(
        dlq,
        {
            "id": "legacy-1",
            "payload": json.dumps({"event_type": "order.created", "n": 7}),
            "meta": json.dumps({"dlq_reason": "permanent failure", "source_stream": stream}),
        },
    )

    [item] = await list_dlq(redis_client, dlq)
    assert item["envelope"] is False
    assert item["payload"] == {"event_type": "order.created", "n": 7}
    assert item["meta"]["dlq_reason"] == "permanent failure"

    assert await requeue(redis_client, dlq, item["entry_id"]) is True
    assert await redis_client.xlen(dlq) == 0
    assert await redis_client.xlen(stream) == 1
