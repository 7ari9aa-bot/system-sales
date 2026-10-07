"""§144 P5 — per-tenant concurrency cap (the last dead fairness constant).

``tenancy.py`` declared the concurrency/queue-depth defaults with the promise
"excess requests are rejected with 429" — and nothing ever enforced it. One
tenant hammering the API with slow requests could occupy every worker slot
while other tenants waited behind them. The gate's default is now DERIVED
from the DB pool (never wider than the pool it fronts); TENANT_CONCURRENCY
overrides it.

The governor is IN-PROCESS asyncio state (a Condition + per-tenant counters),
not a Redis budget: the §144 daily consumption counters are the cross-process
meter, and what an in-process cap genuinely provides is backpressure against a
tenant flooding the workers this process is running. It is deliberately
dependency-free (no Redis, no DB) so it always enforces, even during an outage
the rate limiter fails open through.

Middleware tests reuse the ASGITransport harness from test_request_integrity:
FakeRedis for the layered limiter, distinct IPs/users so ONLY the concurrency
tier can deny.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core import middleware as mw
from app.core.config import get_settings
from app.core.security import create_access_token
from app.core.tenancy import (
    DEFAULT_TENANT_QUEUE_DEPTH,
    TenantBusyError,
    TenantConcurrencyGovernor,
    default_tenant_concurrency,
)

# ------------------------------------------------------------ governor ----


class _PoolSettings:
    db_pool_size = 12
    db_max_overflow = 10
    tenant_concurrency = 0


class _ExplicitSettings(_PoolSettings):
    tenant_concurrency = 7


async def test_the_default_gate_is_the_pool_capacity_itself(monkeypatch):
    """The §144 gate sits in front of the DB pool, so its default is DERIVED
    from the pool (pool + overflow), never the old flat 50 — a gate wider
    than the pool let an admitted tenant starve on pool timeouts."""
    monkeypatch.setattr("app.core.config.get_settings", lambda: _PoolSettings())

    governor = TenantConcurrencyGovernor()
    assert governor.concurrency == 22  # 12 + 10, the pool capacity
    assert governor.concurrency == default_tenant_concurrency()
    assert governor.queue_depth == DEFAULT_TENANT_QUEUE_DEPTH


async def test_an_explicit_tenant_concurrency_overrides_the_derivation(monkeypatch):
    monkeypatch.setattr("app.core.config.get_settings", lambda: _ExplicitSettings())

    assert TenantConcurrencyGovernor().concurrency == 7
    # An explicit constructor argument still wins over everything.
    assert TenantConcurrencyGovernor(concurrency=3).concurrency == 3


async def test_the_middleware_governor_defaults_to_the_derivation(monkeypatch):
    """Fail-first: the production path builds its governor with no explicit
    concurrency, so the gate width must come from default_tenant_concurrency()
    — the pool capacity — and never from a stale hard-coded number. A gate
    wider than the pool is exactly the §144 starvation bug this file exists
    to keep closed."""
    monkeypatch.setattr("app.core.config.get_settings", lambda: _PoolSettings())
    middleware = mw.RateLimitMiddleware(
        FastAPI(), client=FakeRedis(decode_responses=True), enabled=True
    )
    assert middleware._governor.concurrency == 22  # 12 + 10, the pool capacity
    assert middleware._governor.concurrency == default_tenant_concurrency()


async def test_the_derived_default_never_exceeds_the_declared_pool():
    """Guard against the settings drifting apart from the gate."""
    settings = get_settings()
    derived = default_tenant_concurrency()
    if settings.tenant_concurrency > 0:
        assert derived == settings.tenant_concurrency
    else:
        pool = settings.db_pool_size + settings.db_max_overflow
        assert derived == pool, "the gate default must track the pool capacity"


async def test_requests_up_to_the_limit_are_admitted_immediately():
    governor = TenantConcurrencyGovernor(concurrency=2, queue_depth=5)
    tenant = uuid.uuid4()

    await governor.acquire(tenant)
    await governor.acquire(tenant)
    assert governor.in_flight(tenant) == 2

    governor.release(tenant)
    governor.release(tenant)
    assert governor.in_flight(tenant) == 0


async def test_over_limit_request_waits_until_a_slot_frees():
    governor = TenantConcurrencyGovernor(concurrency=1, queue_depth=5)
    tenant = uuid.uuid4()
    await governor.acquire(tenant)

    admitted = asyncio.Event()

    async def waiter() -> None:
        await governor.acquire(tenant)
        admitted.set()
        governor.release(tenant)

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0)  # the waiter runs to its suspension on the condition
    assert not admitted.is_set()
    assert governor.waiting(tenant) == 1

    governor.release(tenant)
    await asyncio.wait_for(task, timeout=1)
    assert admitted.is_set()
    assert governor.in_flight(tenant) == 0
    assert governor.waiting(tenant) == 0


async def test_full_queue_refuses_immediately_with_tenant_busy():
    """Beyond the queue depth there is no point waiting: refuse (→ 429)."""
    governor = TenantConcurrencyGovernor(concurrency=1, queue_depth=1)
    tenant = uuid.uuid4()
    await governor.acquire(tenant)

    first = asyncio.create_task(_pass_through(governor, tenant))
    await asyncio.sleep(0)
    assert governor.waiting(tenant) == 1

    with pytest.raises(TenantBusyError):
        await asyncio.wait_for(governor.acquire(tenant), timeout=0.5)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    governor.release(tenant)
    assert governor.in_flight(tenant) == 0


async def test_cancelled_waiter_frees_its_queue_spot_for_the_next_one():
    governor = TenantConcurrencyGovernor(concurrency=1, queue_depth=1)
    tenant = uuid.uuid4()
    await governor.acquire(tenant)

    first = asyncio.create_task(_pass_through(governor, tenant))
    await asyncio.sleep(0)
    assert governor.waiting(tenant) == 1

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert governor.waiting(tenant) == 0

    # The queue spot came back: a new waiter queues instead of being refused,
    # and its cancellation must not eat the holder's release either.
    second = asyncio.create_task(_pass_through(governor, tenant))
    await asyncio.sleep(0)
    assert governor.waiting(tenant) == 1

    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second

    third = asyncio.create_task(_pass_through(governor, tenant))
    await asyncio.sleep(0)
    governor.release(tenant)
    await asyncio.wait_for(third, timeout=1)  # admitted — no lost wakeup
    assert governor.in_flight(tenant) == 0


async def _pass_through(governor: TenantConcurrencyGovernor, tenant: uuid.UUID) -> None:
    await governor.acquire(tenant)
    governor.release(tenant)


async def test_counters_are_per_tenant():
    governor = TenantConcurrencyGovernor(concurrency=1, queue_depth=0)
    a, b = uuid.uuid4(), uuid.uuid4()

    await governor.acquire(a)
    await governor.acquire(b)  # a's saturation must not touch b
    assert governor.in_flight(a) == 1 and governor.in_flight(b) == 1
    governor.release(a)
    governor.release(b)


# -------------------------------------------------------- middleware ----


def _concurrency_app(
    governor: TenantConcurrencyGovernor,
    *,
    gate: asyncio.Event,
    held: asyncio.Event,
    client=None,
) -> FastAPI:
    """/api/v1/orders blocks until ``gate`` is set, announcing entry via ``held``."""
    app = FastAPI()

    @app.get("/api/v1/orders")
    async def orders() -> dict[str, bool]:
        held.set()
        await gate.wait()
        return {"ok": True}

    app.add_middleware(
        mw.RateLimitMiddleware,
        client=client or FakeRedis(decode_responses=True),
        enabled=True,
        governor=governor,
    )
    return app


def _token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    return create_access_token(str(user_id), {"tenant_id": str(tenant_id), "role": "owner"})


async def _get(app: FastAPI, *, token: str | None, ip: str):
    headers = {"x-forwarded-for": f"10.0.0.1, {ip}"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/api/v1/orders", headers=headers)


async def test_tenant_at_capacity_with_full_queue_gets_429_concurrency_tier():
    gate = asyncio.Event()
    held = asyncio.Event()
    app = _concurrency_app(
        TenantConcurrencyGovernor(concurrency=1, queue_depth=1),
        gate=gate,
        held=held,
    )
    tenant = uuid.uuid4()

    holder = asyncio.create_task(_get(app, token=_token(uuid.uuid4(), tenant), ip="203.0.113.1"))
    await held.wait()  # request 1 now occupies the single slot

    waiter = asyncio.create_task(_get(app, token=_token(uuid.uuid4(), tenant), ip="203.0.113.2"))
    await asyncio.sleep(0.05)  # request 2 is queued in the governor
    assert not waiter.done()

    # Request 3: queue is full → refused with the contract 429 shape.
    refused = await asyncio.wait_for(
        _get(app, token=_token(uuid.uuid4(), tenant), ip="203.0.113.3"),
        timeout=1,
    )
    assert refused.status_code == 429
    assert refused.json()["tier"] == "concurrency"
    assert refused.headers["retry-after"]

    gate.set()
    first, second = await asyncio.wait_for(asyncio.gather(holder, waiter), timeout=2)
    assert first.status_code == 200
    assert second.status_code == 200, "the queued request was admitted on release"


async def test_unauthenticated_requests_are_not_governed():
    """No signature-verified tenant → no governor key (IP tiers own that path)."""
    gate = asyncio.Event()
    held = asyncio.Event()
    app = _concurrency_app(
        TenantConcurrencyGovernor(concurrency=1, queue_depth=0),
        gate=gate,
        held=held,
    )

    one = asyncio.create_task(_get(app, token=None, ip="198.51.100.1"))
    await held.wait()
    two = asyncio.create_task(_get(app, token=None, ip="198.51.100.2"))
    await asyncio.sleep(0.05)
    assert not two.done() and not one.done()  # both in-flight together

    gate.set()
    r1, r2 = await asyncio.wait_for(asyncio.gather(one, two), timeout=2)
    assert r1.status_code == 200 and r2.status_code == 200


async def test_slot_is_released_between_sequential_requests():
    """The try/finally release must not leak slots across requests."""
    gate = asyncio.Event()
    held = asyncio.Event()
    app = _concurrency_app(
        TenantConcurrencyGovernor(concurrency=1, queue_depth=0),
        gate=gate,
        held=held,
    )
    tenant = uuid.uuid4()

    gate.set()
    first = await _get(app, token=_token(uuid.uuid4(), tenant), ip="192.0.2.1")
    assert first.status_code == 200
    second = await _get(app, token=_token(uuid.uuid4(), tenant), ip="192.0.2.2")
    assert second.status_code == 200


class _ExplodingRedis:
    async def eval(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("redis down")


async def test_the_gate_still_fails_closed_when_redis_is_down():
    """Fail-first: the §144 governor is Redis-free precisely so an outage the
    rate limiter fails OPEN through cannot also switch the concurrency gate
    off. With Redis dead the rate tiers admit everything, but a tenant past
    its cap must STILL be refused with the 429 concurrency envelope — not a
    500 and not an open gate."""
    gate = asyncio.Event()
    held = asyncio.Event()
    app = _concurrency_app(
        TenantConcurrencyGovernor(concurrency=1, queue_depth=1),
        gate=gate,
        held=held,
        client=_ExplodingRedis(),
    )
    tenant = uuid.uuid4()

    holder = asyncio.create_task(_get(app, token=_token(uuid.uuid4(), tenant), ip="203.0.113.1"))
    await held.wait()  # request 1 occupies the single slot, Redis is dead

    waiter = asyncio.create_task(_get(app, token=_token(uuid.uuid4(), tenant), ip="203.0.113.2"))
    await asyncio.sleep(0.05)
    assert not waiter.done()  # queued, not denied — the gate still meters

    refused = await asyncio.wait_for(
        _get(app, token=_token(uuid.uuid4(), tenant), ip="203.0.113.3"),
        timeout=1,
    )
    assert refused.status_code == 429
    assert refused.json()["tier"] == "concurrency"
    assert refused.json()["error"]["code"] == "rate_limit_exceeded"
    assert refused.json()["error"]["retryable"] is True
    assert refused.headers["retry-after"]

    gate.set()
    first, second = await asyncio.wait_for(asyncio.gather(holder, waiter), timeout=2)
    assert first.status_code == 200
    assert second.status_code == 200
