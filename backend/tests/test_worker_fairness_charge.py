"""§144 — WORKER_SECONDS is charged at the point of consumption.

The fairness budgets only mean something if someone SPENDS them there:
AI tokens are charged in the gateway, outbound messages in the campaign
pump — and worker time must be charged in the worker runtime itself, or
"a tenant's long-running jobs should not occupy all workers" is a slogan.

The base StreamWorker times every handled event and charges the whole
seconds to the envelope tenant's WORKER_SECONDS counter — on success AND
on failure (a crashing handler burned real capacity). The charge is
accounting; the GATE belongs to the priority tier that may be throttled
(bulk/campaign defers on it — see the campaign pump), because §144
ranks human and AI work ABOVE the budget fight: interactive tiers are
never starved by their own meter.
"""

from __future__ import annotations

import uuid

from tests.test_reliability import (
    FakeBus,
    StubWorker,
    _bus_event,
    _envelope_event,
    _fake_session_factory,
)

TENANT = uuid.uuid4()


def _fake_redis(monkeypatch):
    from fakeredis.aioredis import FakeRedis

    from app.core import fairness

    fake = FakeRedis(decode_responses=True)
    monkeypatch.setattr(fairness, "get_redis", lambda: fake)
    return fake, fairness._budget_key(TENANT, fairness.ResourceType.WORKER_SECONDS)


async def test_successful_handler_charges_worker_seconds(monkeypatch):
    fake, key = _fake_redis(monkeypatch)
    factory, _session = _fake_session_factory()
    monkeypatch.setattr("app.workers.base.SessionLocal", factory)
    bus = FakeBus()
    worker = StubWorker(bus)

    await worker._process(await _envelope_event("evt-charge-1", tenant_id=TENANT))

    assert worker.calls == 1
    charged = int(await fake.get(key) or 0)
    assert charged >= 1  # whole seconds, rounded up — one event is a floor of 1


async def test_failed_handler_still_pays_for_the_time_it_burned(monkeypatch):
    fake, key = _fake_redis(monkeypatch)
    factory, _session = _fake_session_factory()
    monkeypatch.setattr("app.workers.base.SessionLocal", factory)
    monkeypatch.setattr("app.workers.base.random.uniform", lambda low, high: 0)
    bus = FakeBus()
    worker = StubWorker(bus, RuntimeError("transient crash"))

    await worker._process(await _envelope_event("evt-charge-2", tenant_id=TENANT))

    # The event is retried through the outbox — but the seconds already spent
    # on this attempt are charged.
    assert bus.dlq == []
    assert int(await fake.get(key) or 0) >= 1


async def test_non_envelope_entries_are_not_charged(monkeypatch):
    """No tenant attribution → no charge to ANYONE (fail closed on the
    metering, exactly like the workers' fail-closed envelope read)."""
    fake, key = _fake_redis(monkeypatch)
    factory, _session = _fake_session_factory()
    monkeypatch.setattr("app.workers.base.SessionLocal", factory)
    bus = FakeBus()
    worker = StubWorker(bus)

    await worker._process(_bus_event("evt-plain"))

    assert worker.calls == 1
    assert await fake.get(key) is None
