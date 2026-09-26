"""OPS-1: the worker counters have writers, proven per outcome.

`/metrics` published ``worker_events_total`` and ``worker_seconds_total``
before anything incremented them — an exposition that renders empty series
(GAP_REGISTER "two gaps this wave created and did not close"). This file
drives one StreamWorker through every terminal path of ``_process_event`` /
``_run_with_lineage`` with a scripted bus and a stubbed inbox, and asserts the
catalogue-legal increment each path owes:

- contested inbox claim  -> worker_events_total{outcome="contested"}
- committed marker seen  -> {outcome="skipped"}
- effect succeeded       -> {outcome="processed"} (+ the seconds charge)
- DeferredError          -> {outcome="deferred"}
- transient failure      -> {outcome="retried"} (staged retry)
- permanent failure      -> {outcome="dead_lettered"}
- attempts exhausted     -> {outcome="dead_lettered"}

DB-free: the inbox claim is monkeypatched, the bus is a recorder, and
``app.core.metrics.increment`` is replaced by an async recorder so the label
pairs can be asserted without Redis.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.events.bus import ATTEMPTS_META_KEY, Event
from app.workers.base import DeferredError, StreamWorker

STREAM = "message.events"


class _RecorderBus:
    def __init__(self) -> None:
        self.acked: list[str] = []
        self.dlq: list[str] = []

    async def ack(self, stream, group, event) -> None:
        self.acked.append(event.id)

    async def send_to_dlq(self, stream, event, reason) -> None:
        self.dlq.append((event.id, reason))


class _RecordingWorker(StreamWorker):
    stream = STREAM
    group = "test-group"
    name = "test-pool"

    def __init__(self, bus, *, outcome=None) -> None:
        super().__init__(bus)
        self._outcome = outcome

    async def handle(self, event: Event) -> None:
        if self._outcome == "transient":
            raise RuntimeError("boom")
        if self._outcome == "permanent":
            from app.core.errors import NotFoundError

            raise NotFoundError("no such row")
        if self._outcome == "deferred":
            raise DeferredError("wait for it", delay_seconds=30)


def _event(*, attempts: int = 0) -> Event:
    return Event(
        id=str(uuid.uuid4()),
        stream=STREAM,
        payload={"type": "x", "aggregate_type": "test", "aggregate_id": "a"},
        meta={ATTEMPTS_META_KEY: attempts} if attempts else {},
    )


@pytest.fixture()
def recorded(monkeypatch):
    calls: list[tuple[str, float, dict]] = []

    async def _increment(name, *, value=1.0, labels=None, **kwargs):
        calls.append((name, value, dict(labels or {})))

    monkeypatch.setattr("app.core.metrics.increment", _increment)
    return calls


def _claimed(monkeypatch) -> None:
    async def _claim(self, dedupe_id):
        return "claimed", None, None

    async def _close(self, session, tx, dedupe_id, *, marker):
        return None

    monkeypatch.setattr(StreamWorker, "_claim_inbox", _claim)
    monkeypatch.setattr(StreamWorker, "_close_inbox", _close)


def _failing_consume(*a, **kw):
    raise RuntimeError("no db in this test")


def _envelope_event() -> Event:
    """A §19 envelope the read half accepts: registered type + tenant + time."""
    from app.core.events.schemas import EVENT_TYPES

    return Event(
        id=str(uuid.uuid4()),
        stream=STREAM,
        payload={"event_type": "test"},
        meta={
            "outbox_id": "outbox-1",
            "type": sorted(EVENT_TYPES)[0],
            "tenant_id": str(uuid.uuid4()),
            "aggregate_type": "test",
            "aggregate_id": str(uuid.uuid4()),
            "occurred_at": "2026-09-27T00:00:00+00:00",
        },
    )


def _events_of(calls) -> list[dict]:
    return [labels for name, _v, labels in calls if name == "worker_events_total"]


async def test_a_successful_effect_counts_processed_and_charges_seconds(recorded, monkeypatch):
    _claimed(monkeypatch)
    monkeypatch.setattr(
        "app.core.fairness.consume", _failing_consume, raising=False
    )
    bus = _RecorderBus()
    worker = _RecordingWorker(bus)

    # _process (not _process_event) so the §144 finally-block runs: the
    # seconds series is written in the same place fairness bills.
    await worker._process(_envelope_event())

    assert bus.acked and not bus.dlq
    assert {"stream": STREAM, "outcome": "processed"} in _events_of(recorded)
    seconds = [
        (value, meter_labels)
        for name, value, meter_labels in recorded
        if name == "worker_seconds_total"
    ]
    assert seconds and seconds[0][0] >= 1 and seconds[0][1] == {"stream": STREAM}


async def test_a_committed_marker_counts_skipped(recorded, monkeypatch) -> None:
    async def _seen(self, dedupe_id):
        return "seen", None, None

    monkeypatch.setattr(StreamWorker, "_claim_inbox", _seen)
    bus = _RecorderBus()
    worker = _RecordingWorker(bus, outcome="processed")

    await worker._process_event(_event())

    assert {"stream": STREAM, "outcome": "skipped"} in _events_of(recorded)
    assert bus.acked


async def test_a_contested_claim_counts_contested_without_acking(recorded, monkeypatch) -> None:
    async def _contested(self, dedupe_id):
        return "contested", None, None

    monkeypatch.setattr(StreamWorker, "_claim_inbox", _contested)
    bus = _RecorderBus()
    worker = _RecordingWorker(bus)

    await worker._process_event(_event())

    assert {"stream": STREAM, "outcome": "contested"} in _events_of(recorded)
    assert not bus.acked, "a stood-down claimer must leave the entry in the PEL"


async def test_a_transient_failure_counts_retried(recorded, monkeypatch) -> None:
    _claimed(monkeypatch)
    staged: list[Event] = []

    async def _stage(self, event, meta, delay):
        staged.append(event)

    monkeypatch.setattr(StreamWorker, "_republish_after", _stage)
    bus = _RecorderBus()
    worker = _RecordingWorker(bus, outcome="transient")

    await worker._process_event(_event())

    assert {"stream": STREAM, "outcome": "retried"} in _events_of(recorded)
    assert staged, "the retry must be durably staged"


async def test_a_permanent_failure_counts_dead_lettered(recorded, monkeypatch) -> None:
    _claimed(monkeypatch)
    bus = _RecorderBus()
    worker = _RecordingWorker(bus, outcome="permanent")

    await worker._process_event(_event())

    assert {"stream": STREAM, "outcome": "dead_lettered"} in _events_of(recorded)
    assert bus.dlq


async def test_exhausted_attempts_count_dead_lettered(recorded, monkeypatch) -> None:
    _claimed(monkeypatch)
    bus = _RecorderBus()
    worker = _RecordingWorker(bus, outcome="transient")

    await worker._process_event(_event(attempts=99))

    assert {"stream": STREAM, "outcome": "dead_lettered"} in _events_of(recorded)
    assert bus.dlq


async def test_a_defer_counts_deferred_without_touching_the_retry_budget(
    recorded, monkeypatch
):
    _claimed(monkeypatch)
    bus = _RecorderBus()
    worker = _RecordingWorker(bus, outcome="deferred")

    await worker._process_event(_event())

    assert {"stream": STREAM, "outcome": "deferred"} in _events_of(recorded)
