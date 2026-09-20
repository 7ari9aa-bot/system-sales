"""Wave 1 reliability primitives — pure unit tests (no database).

Covers: event envelope v2 fields, outbox writer v2 kwargs (meta passthrough),
the WebhookEvent system-ingress model registration, and worker retry
classification (permanent failures dead-letter immediately, everything else
retries with backoff).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.core.db import Base
from app.core.errors import ValidationError
from app.core.events.bus import Event
from app.core.events.schemas import EventEnvelope
from app.core.events.writer import add_outbox_event
from app.workers.base import PermanentError, RetryableError, StreamWorker

# --- envelope v2 fields ------------------------------------------------------


def _envelope(**overrides: Any) -> EventEnvelope:
    defaults: dict[str, Any] = {
        "type": "test.reliability",
        "tenant_id": uuid.uuid4(),
        "aggregate_type": "widget",
        "aggregate_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return EventEnvelope(**defaults)


def test_envelope_v2_fields_have_defaults() -> None:
    envelope = _envelope()
    assert envelope.correlation_id is None
    assert envelope.causation_id is None
    assert envelope.producer == "core"
    assert envelope.schema_version == 1
    assert envelope.aggregate_version is None


def test_envelope_v2_fields_accept_explicit_values() -> None:
    envelope = _envelope(
        correlation_id="corr-1",
        causation_id="cause-1",
        producer="orders-svc",
        schema_version=2,
        aggregate_version=7,
    )
    assert envelope.correlation_id == "corr-1"
    assert envelope.causation_id == "cause-1"
    assert envelope.producer == "orders-svc"
    assert envelope.schema_version == 2
    assert envelope.aggregate_version == 7


# --- outbox writer v2 kwargs -------------------------------------------------


def _assign_id(instance: Any) -> None:
    """Emulate the DB PK default so ``meta['outbox_id'] == str(row.id)`` is real."""
    if getattr(instance, "id", None) is None:
        instance.id = uuid.uuid4()


def _magic_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock(side_effect=_assign_id)
    session.flush = AsyncMock()
    return session


async def test_add_outbox_event_v2_kwargs_stored_in_meta() -> None:
    session = _magic_session()
    tenant_id = uuid.uuid4()

    event = await add_outbox_event(
        session,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=tenant_id,
        meta={"source": "unit-test"},
        correlation_id="corr-1",
        causation_id="cause-1",
        producer="orders-svc",
        aggregate_version=3,
        schema_version=2,
    )

    added = session.add.call_args[0][0]
    assert added is event
    assert added.meta["tenant_id"] == str(tenant_id)
    assert added.meta["source"] == "unit-test"
    assert added.meta["correlation_id"] == "corr-1"
    assert added.meta["causation_id"] == "cause-1"
    assert added.meta["producer"] == "orders-svc"
    assert added.meta["aggregate_version"] == 3
    assert added.meta["schema_version"] == 2
    # table shape untouched: v2 fields ride in meta, not in outbox columns
    assert added.stream == "order.events"
    assert added.payload["event_type"] == "order.created"
    assert added.status == "pending"


async def test_add_outbox_event_backward_compatible_defaults() -> None:
    session = _magic_session()
    tenant_id = uuid.uuid4()
    aggregate_id = uuid.uuid4()

    await add_outbox_event(
        session,
        aggregate_type="customer",
        aggregate_id=aggregate_id,
        event_type="customer.merged",
        tenant_id=tenant_id,
    )

    added = session.add.call_args[0][0]
    # outbox_id: the stable consumer-dedupe key that survives relay
    # crash-reclaim re-publishes (a per-publish bus uuid made replays new).
    assert added.meta["outbox_id"] == str(added.id)
    # Tenant isolation contract: the relay is cross-tenant and the SSE gateway
    # fails CLOSED without this claim, so it must always be present and exact.
    assert added.meta["tenant_id"] == str(tenant_id)
    # v2 lineage defaults ride in meta (the outbox columns are frozen).
    assert added.meta["producer"] == "core"
    assert added.meta["schema_version"] == 1
    # §19 envelope routing keys — what deserialize() needs to rebuild the event.
    assert added.meta["type"] == "customer.merged"
    assert added.meta["aggregate_type"] == "customer"
    assert added.meta["aggregate_id"] == str(aggregate_id)
    assert added.meta["version"] == 1
    assert "occurred_at" in added.meta


# --- WebhookEvent model ------------------------------------------------------


def test_webhook_event_registered_with_expected_shape() -> None:
    import app.core.model_registry  # noqa: F401 — registers every module's models

    table = Base.metadata.tables["webhook_events"]
    assert set(table.columns.keys()) == {
        "id",
        "provider",
        "external_event_id",
        "tenant_id",
        "received_at",
        "signature_valid",
        "payload",
        "processing_status",
        "attempts",
        "last_error",
        "processed_at",
    }
    # system-ingress table: tenant reference is a plain column, no FK / no RLS mixin
    assert not table.columns["tenant_id"].foreign_keys
    assert table.columns["processing_status"].server_default.arg == "pending"
    assert table.columns["signature_valid"].server_default.arg == "false"
    assert table.columns["attempts"].server_default.arg == "0"

    indexes = {ix.name: ix for ix in table.indexes}
    assert [c.name for c in indexes["ix_webhook_events_provider_ext"].columns] == [
        "provider",
        "external_event_id",
    ]
    assert [c.name for c in indexes["ix_webhook_events_status_created"].columns] == [
        "processing_status",
        "received_at",
    ]


# --- worker retry classification ---------------------------------------------


class FakeBus:
    """Records publish / ack / DLQ calls (the EventBus surface _process uses)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
        self.acked: list[tuple[str, str]] = []
        self.dlq: list[tuple[str, str, str]] = []

    async def publish(
        self, stream: str, payload: dict[str, Any], meta: dict[str, Any] | None = None
    ) -> str:
        self.published.append((stream, payload, meta))
        return "0-0"

    async def ack(self, stream: str, group: str, event: Event) -> None:
        self.acked.append((stream, event.id))

    async def send_to_dlq(self, stream: str, event: Event, reason: str) -> None:
        self.dlq.append((stream, event.id, reason))


class StubWorker(StreamWorker):
    stream = "test.stream"
    group = "test.group"

    def __init__(self, bus: FakeBus, exc: Exception | None = None) -> None:
        super().__init__(bus)
        self._exc = exc
        self.calls = 0

    async def handle(self, event: Event) -> None:
        self.calls += 1
        if self._exc is not None:
            raise self._exc


def _bus_event(event_id: str) -> Event:
    return Event(id=event_id, stream="test.stream", payload={"k": "v"}, meta={})


def _cause_wrapped(cause: Exception) -> RuntimeError:
    # replicates `raise RuntimeError(...) from cause` without raising here
    try:
        raise cause
    except Exception as caught:
        err = RuntimeError("handler crashed")
        err.__context__ = caught
        err.__cause__ = caught
        return err


def _context_wrapped(cause: Exception) -> RuntimeError:
    err = RuntimeError("handler crashed")
    err.__context__ = cause
    return err


async def test_permanent_error_goes_straight_to_dlq() -> None:
    bus = FakeBus()
    worker = StubWorker(bus, PermanentError("unsupported payload"))

    await worker._process(_bus_event("evt-permanent"))

    assert worker.calls == 1
    assert bus.dlq == [("test.stream", "evt-permanent", "permanent failure")]
    assert bus.acked == [("test.stream", "evt-permanent")]
    assert bus.published == []


async def test_wrapped_permanent_error_via_cause_goes_to_dlq() -> None:
    bus = FakeBus()
    worker = StubWorker(bus, _cause_wrapped(PermanentError("bad")))

    await worker._process(_bus_event("evt-cause"))

    assert bus.dlq == [("test.stream", "evt-cause", "permanent failure")]
    assert bus.acked == [("test.stream", "evt-cause")]
    assert bus.published == []


async def test_context_wrapped_permanent_error_goes_to_dlq() -> None:
    bus = FakeBus()
    worker = StubWorker(bus, _context_wrapped(PermanentError("bad")))

    await worker._process(_bus_event("evt-ctx"))

    assert bus.dlq == [("test.stream", "evt-ctx", "permanent failure")]
    assert bus.published == []


async def test_validation_error_is_treated_as_permanent() -> None:
    bus = FakeBus()
    worker = StubWorker(bus, ValidationError("malformed event"))

    await worker._process(_bus_event("evt-validation"))

    assert bus.dlq == [("test.stream", "evt-validation", "permanent failure")]
    assert bus.acked == [("test.stream", "evt-validation")]
    assert bus.published == []


class _FakeSessionCM:
    def __init__(self, session: MagicMock) -> None:
        self._session = session

    async def __aenter__(self) -> MagicMock:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _fake_session_factory() -> tuple[Any, MagicMock]:
    session = MagicMock()
    session.begin = lambda: _FakeSessionCM(session)
    session.add = MagicMock(side_effect=_assign_id)
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return (lambda: _FakeSessionCM(session)), session


async def _envelope_event(event_id: str, **kwargs: Any) -> Event:
    """A bus Event carrying a REAL §19 envelope, exactly as the relay publishes.

    Built through the canonical writer, so the retry path is exercised against
    the routing keys + payload + ``outbox_id`` a published row really carries.
    """
    row = await add_outbox_event(
        _magic_session(),
        aggregate_type=kwargs.pop("aggregate_type", "order"),
        aggregate_id=kwargs.pop("aggregate_id", uuid.uuid4()),
        event_type=kwargs.pop("event_type", "order.created"),
        tenant_id=kwargs.pop("tenant_id", uuid.uuid4()),
        payload=kwargs.pop("payload", {"order_id": "o-1"}),
        **kwargs,
    )
    return Event(id=event_id, stream=row.stream, payload=row.payload, meta=row.meta)


async def test_generic_failure_stages_durable_retry(monkeypatch) -> None:
    """Retryable failures stage an outbox row with not_before (durable retry).

    The previous fire-and-forget asyncio task lost the retry on shutdown while
    the original entry was already acked — the event vanished. The row is now
    staged through the canonical writer (``add_outbox_event``), so the retry
    carries a real §19 envelope instead of a hand-copied meta blob (finding 3).
    """
    monkeypatch.setattr("app.workers.base.random.uniform", lambda low, high: 0)
    factory, session = _fake_session_factory()
    monkeypatch.setattr("app.workers.base.SessionLocal", factory)
    bus = FakeBus()
    worker = StubWorker(bus, RuntimeError("transient outage"))
    original = await _envelope_event("evt-retry")

    await worker._process(original)

    assert worker.calls == 1
    assert bus.dlq == []
    assert bus.acked == [("test.stream", "evt-retry")]
    assert session.add.call_count == 1
    retry = session.add.call_args[0][0]
    assert retry.stream == "order.events"
    assert retry.status == "pending"
    assert retry.payload["event_type"] == "order.created"
    assert retry.not_before is not None
    # a real envelope, not a hand-copied meta blob
    assert retry.meta["type"] == "order.created"
    assert retry.meta["tenant_id"] == original.meta["tenant_id"]
    assert "occurred_at" in retry.meta
    assert retry.meta["attempts"] == 1
    # the consumer-inbox dedupe key survives the retry (else it double-sends)
    assert retry.meta["outbox_id"] == original.meta["outbox_id"]


async def test_retryable_error_marker_stages_durable_retry(monkeypatch) -> None:
    monkeypatch.setattr("app.workers.base.random.uniform", lambda low, high: 0)
    factory, session = _fake_session_factory()
    monkeypatch.setattr("app.workers.base.SessionLocal", factory)
    bus = FakeBus()
    worker = StubWorker(bus, RetryableError("provider 503"))

    await worker._process(await _envelope_event("evt-retryable"))

    assert bus.dlq == []
    assert session.add.call_count == 1
    retry = session.add.call_args[0][0]
    assert retry.meta["attempts"] == 1
    assert retry.not_before is not None


# --- scheduler recurring sweeps ----------------------------------------------


class _FakeJob:
    """Minimal ScheduledJob stand-in (only the fields the re-arm path touches)."""

    def __init__(self, job_type: str, tenant_id: uuid.UUID | None) -> None:
        self.job_type = job_type
        self.tenant_id = tenant_id
        self.status = "processing"
        self.run_at: datetime | None = None
        self.attempts = 3
        self.max_attempts = 5
        self.next_attempt_at: datetime | None = datetime.now(UTC)
        self.last_error: str | None = "previous failure"
        self.payload: dict = {"stale": True}
        self.result: dict | None = None


def _scheduler():
    """SchedulerWorker without a bus (the re-arm path never uses one)."""
    from app.workers.scheduler_worker import SchedulerWorker

    return SchedulerWorker.__new__(SchedulerWorker)


async def test_recurring_sweep_rearms_its_own_row() -> None:
    """A recurring sweep must re-arm its existing row, never insert a second.

    Inserting a new row with the same stable idempotency_key violated
    uq_scheduled_jobs_idem. The flush lands at commit time — OUTSIDE the
    per-job try/except — so the failure rolled back the entire claim batch:
    every poll re-claimed the same job and failed identically, and the
    reconcile/expire sweeps never ran at all.
    """
    from app.workers.scheduler_worker import RECURRING_JOBS

    job = _FakeJob("expire_reservations", uuid.uuid4())
    session = MagicMock()
    now = datetime.now(UTC)
    interval, payload = RECURRING_JOBS["expire_reservations"]

    rescheduled = await _scheduler()._reschedule_recurring(session, job, now)

    assert rescheduled is True
    assert session.add.call_count == 0, "duplicate idempotency_key row inserted"
    assert job.status == "queued"
    assert job.run_at == now + interval
    assert job.attempts == 0
    assert job.next_attempt_at is None
    assert job.last_error is None
    assert job.payload == payload


async def test_one_shot_job_is_not_rescheduled() -> None:
    job = _FakeJob("send_invoice", uuid.uuid4())
    session = MagicMock()

    rescheduled = await _scheduler()._reschedule_recurring(session, job, datetime.now(UTC))

    assert rescheduled is False
    assert session.add.call_count == 0
    assert job.status == "processing"


async def test_tenantless_job_is_not_rescheduled() -> None:
    """No tenant context → the sweep cannot bind RLS; leave it to the caller."""
    job = _FakeJob("reconcile_payments", None)
    session = MagicMock()

    rescheduled = await _scheduler()._reschedule_recurring(session, job, datetime.now(UTC))

    assert rescheduled is False
    assert session.add.call_count == 0
    assert job.status == "processing"
