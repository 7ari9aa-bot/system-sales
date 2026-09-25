"""O10 (workers half): every worker log line carries a correlation id.

The API path already had lineage: ``request_id_contextvar`` feeds the v2 error
envelope, the ``x-request-id`` header and the request log line. Workers consume
Redis Streams OUTSIDE any HTTP request, so they had no id at all — a
``worker.handle_failed`` line named a stream and an event id, and nothing tied
it back to the request that caused the event or to the SAME message after it
was retried or reclaimed.

The property worth pinning is NOT "a field exists". It is:

* every line emitted while a message is in scope names that message;
* a message that FAILS and is reprocessed (retry staged through the outbox, or
  an XAUTOCLAIM reclaim of a crashed worker's PEL entry) is logged under the
  SAME id, so one grep reconstructs one message's whole life.

No database and no Redis server: the outbox write in the retry path is captured
at its own boundary, and the bus runs on fakeredis.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis

from app.core.events.bus import ATTEMPTS_META_KEY, Event, RedisStreamsBus
from app.core.events.schemas import build_envelope, serialize

TENANT_ID = "11111111-1111-1111-1111-111111111111"
AGGREGATE_ID = "22222222-2222-2222-2222-222222222222"
CORRELATION_ID = "req-abc-123"

probe_logger = logging.getLogger("app.workers.probe")


# ------------------------------------------------------------------ fixtures


def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every worker DB access raise immediately instead of dialling a port.

    ``StreamWorker._claim_inbox`` and ``_charge_worker_seconds`` open their own
    sessions; both are specified to fail open, so a raising factory is the
    honest stand-in for "the inbox is unreachable" and keeps the test off the
    network.
    """
    from app.workers import base

    def _boom(*_a, **_kw):
        raise AssertionError("no database in this test")

    monkeypatch.setattr(base, "SessionLocal", _boom)


@pytest.fixture
def worker_env(monkeypatch: pytest.MonkeyPatch):
    """A worker runtime with no DB, a fake Redis, and log capture on."""
    _no_database(monkeypatch)

    from app.core import fairness

    fake = FakeRedis(decode_responses=True)
    monkeypatch.setattr(fairness, "get_redis", lambda: fake)
    return fake


class _FakeBus:
    def __init__(self) -> None:
        self.acked: list[str] = []
        self.dlq: list[tuple[str, str]] = []

    async def ack(self, stream: str, group: str, event: Event) -> None:
        self.acked.append(event.id)

    async def send_to_dlq(self, stream: str, event: Event, reason: str) -> None:
        self.dlq.append((event.id, reason))


from app.workers.base import StreamWorker  # noqa: E402  (after fixtures on purpose)


def _ProbeWorkerFor(bus, exc: BaseException | None = None) -> _Worker:
    return _Worker(bus, exc)


class _Worker(StreamWorker):
    stream = "test.events"
    group = "test-workers"
    name = "test-worker"

    def __init__(self, bus, exc: BaseException | None = None) -> None:
        super().__init__(bus)
        self._exc = exc
        self.staged: list[tuple[dict, float]] = []

    async def handle(self, event: Event) -> None:
        probe_logger.info("probe.handler.line")
        if self._exc is not None:
            raise self._exc

    async def _republish_after(self, event: Event, meta: dict, delay: float) -> None:
        # The real method stages an outbox row; the retry test lets it run for
        # real (see _capture_add_outbox_event) and only this override's absence
        # would hide it, so the default is to record, not to skip.
        self.staged.append((meta, delay))


# --------------------------------------------------------------- envelope builders


def _bus_event(
    *, correlation_id: str | None = CORRELATION_ID, outbox_id: str = "outbox-1", **meta
) -> Event:
    """A bus entry shaped exactly the way the relay publishes one.

    Built through ``build_envelope`` + ``serialize`` (the writer's own pair),
    then parsed the way ``RedisStreamsBus.consume`` parses it — so the worker
    sees a genuine §19 envelope, not a hand-made dict that happens to have the
    keys this test cares about.
    """
    envelope = build_envelope(
        "test.relay",
        tenant_id=TENANT_ID,
        aggregate_type="test",
        aggregate_id=AGGREGATE_ID,
        payload={"event_type": "test.relay"},
        meta={"outbox_id": outbox_id},
        correlation_id=correlation_id,
    )
    fields = serialize(envelope)
    parsed_meta = json.loads(fields["meta"])
    parsed_meta.update(meta)
    return Event(
        id=parsed_meta["id"],
        stream="test.events",
        payload=json.loads(fields["payload"]),
        meta=parsed_meta,
        entry_id="1-1",
    )


def _bare_event(outbox_id: str = "outbox-plain") -> Event:
    """A transport entry with no §19 envelope at all (legacy / hand-injected)."""
    return Event(
        id="evt-bare",
        stream="test.events",
        payload={"event_type": "test.relay"},
        meta={"outbox_id": outbox_id},
        entry_id="1-2",
    )


def _worker_lines(caplog) -> list[tuple[str, str | None]]:
    """``(message, correlation_id)`` for every captured worker-namespace line."""
    out: list[tuple[str, str | None]] = []
    for record in caplog.records:
        if record.name.startswith("app.workers"):
            out.append((record.getMessage(), getattr(record, "correlation_id", "<MISSING>")))
    return out


# ------------------------------------------------------------------- presence


async def test_every_line_emitted_while_a_message_is_in_scope_names_its_correlation_id(
    worker_env, caplog
) -> None:
    """The envelope's correlation_id must be on the handler's OWN log line.

    This is the field an operator greps to tie a worker line back to the HTTP
    request that staged the event.
    """
    caplog.set_level(logging.INFO)
    worker = _Worker(_FakeBus())

    await worker._process(_bus_event())

    lines = _worker_lines(caplog)
    assert lines, "the probe handler emitted no log line — the test proves nothing"
    missing = [msg for msg, cid in lines if cid != CORRELATION_ID]
    assert not missing, f"worker lines without the message's correlation id: {missing}"


async def test_the_runtime_lines_of_a_failed_message_also_carry_the_id(
    worker_env, caplog
) -> None:
    """``worker.handle_failed`` / ``worker.permanent_failure`` are the lines that
    matter most and the ones a contextvar-only fix would still miss: they are
    emitted by the runtime, not by the handler."""
    caplog.set_level(logging.INFO)
    bus = _FakeBus()
    worker = _Worker(bus, exc=RuntimeError("boom"))

    await worker._process(_bus_event())

    names = [msg for msg, _ in _worker_lines(caplog)]
    runtime = [n for n in names if n.startswith("worker.")]
    assert runtime, f"no runtime lines captured, got: {names}"
    missing = [
        msg for msg, cid in _worker_lines(caplog) if cid != CORRELATION_ID
    ]
    assert not missing, f"runtime lines missing the correlation id: {missing}"


# ------------------------------------------------------------------- rendering


async def test_the_shipped_worker_log_format_renders_the_correlation_id(
    worker_env, caplog
) -> None:
    """An attribute nobody formats is as invisible as a missing one.

    ``app/workers/run.py`` owns the worker process's ``logging`` format string;
    the field has to be IN it, or the log line an operator reads still names no
    message. Pinning the shipped constant (not a copy in this test) is the point.
    """
    from app.workers.run import WORKER_LOG_FORMAT

    caplog.set_level(logging.INFO)
    worker = _Worker(_FakeBus())
    await worker._process(_bus_event())

    record = next(r for r in caplog.records if r.name == "app.workers.probe")
    rendered = logging.Formatter(WORKER_LOG_FORMAT).format(record)
    assert f"correlation_id={CORRELATION_ID}" in rendered, rendered


# ------------------------------------------------------------------- stability


async def test_a_message_with_no_envelope_correlation_id_still_gets_a_stable_one(
    worker_env, caplog
) -> None:
    """Legacy / hand-injected entries carry no §19 lineage.

    They must still be greppable, and the id must be a property of the MESSAGE
    (its dedupe identity), not of the attempt — so minting one per delivery is
    the wrong fix and this test fails on it.
    """
    caplog.set_level(logging.INFO)
    worker = _Worker(_FakeBus())

    await worker._process(_bare_event(outbox_id="outbox-77"))
    first = [cid for _, cid in _worker_lines(caplog) if cid not in ("", "<MISSING>")]
    caplog.clear()
    await worker._process(_bare_event(outbox_id="outbox-77"))
    second = [cid for _, cid in _worker_lines(caplog) if cid not in ("", "<MISSING>")]

    assert first, "no correlation id at all on a legacy entry"
    assert set(first) == set(second), (
        f"{set(first)!r} != {set(second)!r}: the id is per-delivery, not per-message"
    )


async def test_two_different_messages_do_not_share_a_correlation_id(
    worker_env, caplog
) -> None:
    caplog.set_level(logging.INFO)
    worker = _Worker(_FakeBus())

    await worker._process(_bus_event(correlation_id="cid-one"))
    caplog.clear()
    await worker._process(_bus_event(correlation_id="cid-two"))

    first = {cid for _, cid in _worker_lines(caplog) if cid != "<MISSING>"}
    assert first == {"cid-two"}, f"second message logged under {first!r}"


# ------------------------------------------------------------------- retry


def _capture_add_outbox_event(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Let the REAL ``_republish_after`` run and record what it stages.

    Only the database boundary is replaced; the correlation preservation this
    test pins is a property of the real staging code, so stubbing that method
    out — as the other worker tests do — would prove nothing here.
    """
    captured: dict[str, Any] = {}

    class _Tx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Session:
        def begin(self):
            return _Tx()

        async def execute(self, *a, **kw):
            return None

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    async def _fake_bind_tenant(session, tenant_id, **kw):
        return None

    async def _fake_add(session, **kwargs):
        captured.update(kwargs)

        class _Row:
            not_before = None
            meta = dict(kwargs.get("meta") or {})

            async def _flush(self):
                return None

        row = _Row()
        row.meta["outbox_id"] = "staged-outbox-row-1"
        return row

    import app.core.db
    import app.core.events.writer
    from app.workers import base

    monkeypatch.setattr(base, "SessionLocal", _Factory())
    monkeypatch.setattr(app.core.db, "bind_tenant", _fake_bind_tenant)
    monkeypatch.setattr(app.core.events.writer, "add_outbox_event", _fake_add)
    return captured


def _relay_publishes(captured: dict[str, Any], *, attempts: int) -> Event:
    """Rebuild the bus entry the relay would publish for a staged retry row.

    Same three calls the production writer/relay pair make: ``build_envelope``,
    ``serialize``, then the row's ``meta`` + ``payload`` as ``XADD`` fields.
    """
    envelope = build_envelope(
        captured["event_type"],
        tenant_id=captured["tenant_id"],
        aggregate_type=captured["aggregate_type"],
        aggregate_id=captured["aggregate_id"],
        payload=captured["payload"],
        meta=captured["meta"],
        correlation_id=captured["correlation_id"],
        causation_id=captured.get("causation_id"),
        producer=captured.get("producer", "core"),
        schema_version=captured.get("schema_version", 1),
        aggregate_version=captured.get("aggregate_version"),
    )
    fields = serialize(envelope)
    meta = json.loads(fields["meta"])
    meta["outbox_id"] = "staged-outbox-row-1"
    meta[ATTEMPTS_META_KEY] = attempts
    payload = json.loads(fields["payload"])
    return Event(
        id=meta["id"],
        stream="test.events",
        payload=payload,
        meta=meta,
        entry_id="2-1",
    )


async def test_a_retried_message_is_logged_under_the_same_correlation_id(
    monkeypatch, worker_env, caplog
) -> None:
    """The load-bearing property.

    A failure stages a retry through the outbox with the attempts counter
    bumped. If staging lost or re-minted the correlation id, the second
    attempt would be un-greppable against the first — which is exactly the
    hole O10 reports.
    """
    from app.workers.base import StreamWorker

    captured = _capture_add_outbox_event(monkeypatch)
    caplog.set_level(logging.INFO)

    class _FailingWorker(StreamWorker):
        stream = "test.events"
        group = "test-workers"
        name = "test-worker"

        async def handle(self, event: Event) -> None:
            probe_logger.info("probe.handler.line")
            raise RuntimeError("transient")

    bus = _FakeBus()
    worker = _FailingWorker(bus)
    original = _bus_event()

    await worker._process(original)
    first = {cid for _, cid in _worker_lines(caplog) if cid != "<MISSING>"}
    assert first == {CORRELATION_ID}, first
    assert captured, "the retry path never staged an outbox row"
    assert captured["correlation_id"] == CORRELATION_ID, (
        f"staging lost the correlation id: {captured['correlation_id']!r}"
    )

    caplog.clear()
    retried = _relay_publishes(captured, attempts=1)
    await worker._process(retried)
    second = {cid for _, cid in _worker_lines(caplog) if cid != "<MISSING>"}
    assert second == {CORRELATION_ID}, (
        f"the retry logged under {second!r}, not the original {CORRELATION_ID!r}"
    )


# ------------------------------------------------------------------- reclaim


async def test_a_reclaimed_message_is_logged_under_the_same_correlation_id(
    worker_env, caplog
) -> None:
    """XAUTOCLAIM hands a crashed worker's PEL entry to a live one.

    The reclaimed entry is the SAME serialized envelope (the bus re-reads the
    stored fields), so the reclaim must not re-mint an id. Uses a real
    ``RedisStreamsBus`` over fakeredis rather than constructing the event by
    hand, so "the reclaim returns the same fields" is exercised, not assumed.
    """

    bus = RedisStreamsBus(worker_env)
    original = _bus_event()
    await bus.publish(original.stream, original.payload, original.meta)

    consumed = []
    async for event in bus.consume(original.stream, "test-workers", "c-1", block_ms=10):
        consumed.append(event)
        break
    assert consumed, "fakeredis did not deliver the published entry"
    first_delivery = consumed[0]

    caplog.set_level(logging.INFO)
    worker = _ProbeWorkerFor(_FakeBus())
    await worker._process(first_delivery)
    caplog.clear()

    reclaimed = await bus.reclaim_stale(
        original.stream, "test-workers", "c-2", min_idle_ms=0
    )
    assert reclaimed, "reclaim returned nothing — the test would prove nothing"
    await worker._process(reclaimed[0])

    ids = {cid for _, cid in _worker_lines(caplog) if cid != "<MISSING>"}
    assert ids == {CORRELATION_ID}, f"reclaimed entry logged under {ids!r}"
