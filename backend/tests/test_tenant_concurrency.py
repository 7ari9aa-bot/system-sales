"""§144 P5 — per-tenant concurrency cap (the last dead fairness constant).

``tenancy.py`` declared DEFAULT_TENANT_CONCURRENCY / DEFAULT_TENANT_QUEUE_DEPTH
with the promise "excess requests are rejected with 429" — and nothing ever
enforced it. One tenant hammering the API with slow requests could occupy every
worker slot while other tenants waited behind them.

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
from app.core.security import create_access_token
from app.core.tenancy import (
    DEFAULT_TENANT_CONCURRENCY,
    DEFAULT_TENANT_QUEUE_DEPTH,
    TenantBusyError,
    TenantConcurrencyGovernor,
)

# ------------------------------------------------------------ governor ----


async def test_defaults_come_from_the_budget_constants():
    """The §144 constants are the governor's configuration source of truth."""
    governor = TenantConcurrencyGovernor()
    assert governor.concurrency == DEFAULT_TENANT_CONCURRENCY
    assert governor.queue_depth == DEFAULT_TENANT_QUEUE_DEPTH


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
        client=FakeRedis(decode_responses=True),
        enabled=True,
        governor=governor,
    )
    return app


def _token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    return create_access_token(
        str(user_id), {"tenant_id": str(tenant_id), "role": "owner"}
    )


async def _get(app: FastAPI, *, token: str | None, ip: str):
    headers = {"x-forwarded-for": f"10.0.0.1, {ip}"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
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

    holder = asyncio.create_task(
        _get(app, token=_token(uuid.uuid4(), tenant), ip="203.0.113.1")
    )
    await held.wait()  # request 1 now occupies the single slot

    waiter = asyncio.create_task(
        _get(app, token=_token(uuid.uuid4(), tenant), ip="203.0.113.2")
    )
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
    first, second = await asyncio.wait_for(
        asyncio.gather(holder, waiter), timeout=2
    )
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
