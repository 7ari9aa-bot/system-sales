"""Request-scoped tenant context.

The middleware (Stage 2) resolves the tenant from the JWT claim / header, stores
it here, and every session opened for the request binds it for RLS via
bind_tenant(). Application-layer authorization checks it independently — tenant
isolation is enforced twice by design.

§144: Tenant fairness — per-tenant concurrency budgets prevent a single noisy
tenant from starving others. The governor below is an IN-PROCESS cap (asyncio
semaphore per tenant, queued waiters up to the queue depth, refusal beyond):
deliberately Redis-free so it keeps enforcing during an outage the rate
limiter fails open through. Cross-process consumption is metered separately
by app.core.fairness daily budgets; this class owns only backpressure for the
requests this worker process is running.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from uuid import UUID, uuid4

_current_tenant: ContextVar[UUID | None] = ContextVar("current_tenant", default=None)

# §144: per-tenant concurrency budgets. A tenant can hold at most N concurrent
# in-flight requests; excess requests are rejected with 429. The default is
# generous; lower it for noisy tenants via the plan configuration.
DEFAULT_TENANT_CONCURRENCY = 50
DEFAULT_TENANT_QUEUE_DEPTH = 100


class TenantBusyError(Exception):
    """Tenant is at its concurrency cap with a full queue — refuse, don't pile up."""


class TenantConcurrencyGovernor:
    """Per-tenant in-flight request cap with a bounded queue (§144).

    A tenant's requests run up to ``concurrency`` at a time; the next
    ``queue_depth`` wait for a slot to free; anything beyond that raises
    ``TenantBusyError`` immediately (→ 429) because a request that would wait
    behind a full queue is better refused than stalled. State is per process —
    that is the right scope for request backpressure.
    """

    def __init__(
        self,
        *,
        concurrency: int | None = None,
        queue_depth: int | None = None,
    ) -> None:
        self.concurrency = (
            DEFAULT_TENANT_CONCURRENCY if concurrency is None else concurrency
        )
        self.queue_depth = (
            DEFAULT_TENANT_QUEUE_DEPTH if queue_depth is None else queue_depth
        )
        self._slots: dict[str, asyncio.Semaphore] = {}
        self._in_flight: dict[str, int] = {}
        self._waiting: dict[str, int] = {}

    def in_flight(self, tenant_id: UUID | str) -> int:
        return self._in_flight.get(str(tenant_id), 0)

    def waiting(self, tenant_id: UUID | str) -> int:
        return self._waiting.get(str(tenant_id), 0)

    async def acquire(self, tenant_id: UUID | str) -> None:
        key = str(tenant_id)
        slots = self._slots.get(key)
        if slots is None:
            slots = asyncio.Semaphore(self.concurrency)
            self._slots[key] = slots
        if slots.locked() and self._waiting.get(key, 0) >= self.queue_depth:
            raise TenantBusyError(
                f"tenant {key} is at its concurrency cap with a full queue"
            )
        self._waiting[key] = self._waiting.get(key, 0) + 1
        try:
            await slots.acquire()
        finally:
            self._waiting[key] -= 1
        self._in_flight[key] = self._in_flight.get(key, 0) + 1

    def release(self, tenant_id: UUID | str) -> None:
        key = str(tenant_id)
        self._in_flight[key] = self._in_flight.get(key, 0) - 1
        slots = self._slots.get(key)
        if slots is not None:
            slots.release()
        if self._in_flight.get(key, 0) <= 0 and self._waiting.get(key, 0) <= 0:
            # Every permit is back and nobody is queued: drop the bookkeeping
            # so idle tenants do not accumulate state. Safe to recreate lazily.
            self._in_flight.pop(key, None)
            self._waiting.pop(key, None)
            self._slots.pop(key, None)


def set_current_tenant(tenant_id: UUID | str) -> None:
    _current_tenant.set(UUID(str(tenant_id)))


def current_tenant() -> UUID:
    tenant_id = _current_tenant.get()
    if tenant_id is None:
        raise LookupError("No tenant in context — resolve the tenant before scoped work")
    return tenant_id


def try_current_tenant() -> UUID | None:
    return _current_tenant.get()


def reset_current_tenant() -> None:
    _current_tenant.set(None)


def new_tenant_id() -> UUID:
    return uuid4()


@asynccontextmanager
async def tenant_scope(session, tenant_id: UUID | str) -> AsyncIterator[UUID]:
    """Bind tenant on the session (RLS) and in the context (authz) for a block."""
    from app.core.db import bind_tenant

    tid = UUID(str(tenant_id))
    set_current_tenant(tid)
    try:
        await bind_tenant(session, tid)
        yield tid
    finally:
        reset_current_tenant()
