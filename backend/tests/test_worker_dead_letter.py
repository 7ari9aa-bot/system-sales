"""Dead-letter last will — the durable trace a poisoned turn used to erase.

Two layers are pinned here:

* **base.StreamWorker** (pure): the failure path invokes ``_on_dead_letter``
  exactly once, BEFORE the DLQ routing and the ack — for both the permanent
  and the exhausted-retries branches — and never on a normal retry.
* **MessageWorker._on_dead_letter** (DB-backed, CI): a message.received event
  that dead-letters lands a durable ai_handover (the owner is notified, the
  conversation moves to waiting_human) in a FRESH committed transaction —
  the production telegram incident (2026-10-16) erased every write the
  failing turn made and left the customer in silence with no trace.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.core.events.bus import Event
from app.core.events.schemas import build_envelope, serialize
from app.workers.base import ATTEMPTS_META_KEY, PermanentError, StreamWorker


class _FakeBus:
    def __init__(self):
        self.acked: list[str] = []
        self.dlq: list[tuple[str, str]] = []

    async def ack(self, stream, group, event):
        self.acked.append(event.id)

    async def send_to_dlq(self, stream, event, reason):
        self.dlq.append((stream, reason))


class _StubWorker(StreamWorker):
    """Drives the failure path without a real bus, a DB, or a handler."""

    stream = "stub.events"
    group = "stub-group"
    name = "stub-worker"
    _skip_generic_idempotency = True

    def __init__(self, bus: _FakeBus, *, fail_with: Exception):
        super().__init__(bus)
        self.fail_with = fail_with
        self.last_will: list[tuple[Event, Exception]] = []
        self.republished: list[dict] = []

    async def handle(self, event: Event) -> None:
        raise self.fail_with

    async def _on_dead_letter(self, event: Event, exc: Exception) -> None:
        self.last_will.append((event, exc))

    async def _republish_after(self, event: Event, meta: dict, delay: float) -> None:
        # the real one stages the retry through the outbox (a DB write); this
        # unit test only asserts WHO gets told, so record and move on
        self.republished = getattr(self, "republished", [])
        self.republished.append(meta)


def _event(*, attempts: int | None = None) -> Event:
    envelope = build_envelope(
        "order.created",
        tenant_id=uuid.uuid4(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"number": "ORD-1"},
    )
    wire = serialize(envelope)
    meta = json.loads(wire["meta"])
    meta["outbox_id"] = str(uuid.uuid4())
    if attempts is not None:
        meta[ATTEMPTS_META_KEY] = attempts
    return Event(
        id=meta["outbox_id"],
        stream="stub.events",
        payload=json.loads(wire["payload"]),
        meta=meta,
        entry_id=None,
    )


async def test_permanent_failure_invokes_the_last_will_before_the_dlq():
    bus = _FakeBus()
    worker = _StubWorker(bus, fail_with=PermanentError("downstream rejected"))
    event = _event()

    effect = await worker._process_event(event)

    assert not effect  # not acked as processed
    assert len(worker.last_will) == 1
    assert worker.last_will[0][0].id == event.id
    assert isinstance(worker.last_will[0][1], PermanentError)
    assert bus.dlq and bus.dlq[0][1] == "permanent failure"
    assert bus.acked == [event.id]


async def test_exhausted_retries_invoke_the_last_will():
    bus = _FakeBus()
    worker = _StubWorker(bus, fail_with=RuntimeError("gateway down"))
    event = _event(attempts=5)  # worker_max_attempts defaults to 5

    effect = await worker._process_event(event)

    assert not effect
    assert len(worker.last_will) == 1
    assert bus.dlq and bus.dlq[0][1] == "max attempts exceeded"


async def test_a_plain_retry_never_invokes_the_last_will():
    bus = _FakeBus()
    worker = _StubWorker(bus, fail_with=RuntimeError("transient blip"))
    event = _event(attempts=1)

    effect = await worker._process_event(event)

    assert not effect
    assert worker.last_will == []  # still has retry budget — nobody is told yet
    assert bus.dlq == []


# ------------------------------------------------- MessageWorker last will --


async def test_message_worker_dead_letter_lands_a_durable_handover(
    db, tenant_ctx, app_sessions_on_test_connection, monkeypatch
):
    # The worker binds ``SessionLocal`` at import time, so patching the factory alone only works
    # when this module is imported after the fixture ran. Point the worker's own name at the test
    # connection too, whatever order the suite imported things in.
    monkeypatch.setattr("app.workers.message_worker.SessionLocal", app_sessions_on_test_connection)
    from app.modules.ai.models import AIHandover
    from app.modules.conversations.service import ConversationService
    from app.modules.customers.models import Customer
    from app.workers.message_worker import MessageWorker

    tenant_id = tenant_ctx.tenant_id
    customer = Customer(tenant_id=tenant_id, name="Silenced Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="whatsapp"
    )
    await db.flush()

    envelope = build_envelope(
        "message.received",
        tenant_id=tenant_id,
        aggregate_type="message",
        aggregate_id=uuid.uuid4(),
        payload={
            "conversation_id": str(conversation.id),
            "message_id": str(uuid.uuid4()),
        },
    )
    wire = serialize(envelope)
    event = Event(
        id=str(uuid.uuid4()),
        stream="message.events",
        payload=json.loads(wire["payload"]),
        meta=json.loads(wire["meta"]),
        entry_id=None,
    )

    worker = MessageWorker.__new__(MessageWorker)
    StreamWorker.__init__(worker, _FakeBus())
    await worker._on_dead_letter(event, RuntimeError("turn failed on every attempt"))

    (handover,) = (
        (
            await db.execute(
                select(AIHandover).where(
                    AIHandover.tenant_id == tenant_id,
                    AIHandover.conversation_id == conversation.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert handover.reason == "failure"
    assert "dead-lettered" in (handover.note or "")
    assert handover.status == "pending"
