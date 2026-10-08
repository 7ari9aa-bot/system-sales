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

from sqlalchemy.ext.asyncio import AsyncSession

_current_tenant: ContextVar[UUID | None] = ContextVar("current_tenant", default=None)

# §151 Q4: the request-scoped hierarchy below the tenant. get_tenant_ctx sets
# it AFTER resolve_scope() has validated the scope fail-closed; INSERTs of
# WorkspaceScopeMixin rows and outbox envelopes read it, so every mutation in
# a scoped request stamps its scope without threading two ids per call site.
# Default (None, None) = tenant-wide, the pre-§151 semantics — an unscoped
# writer (worker, scheduled job) never inherits someone else's scope.
_current_scope: ContextVar[tuple[UUID | None, UUID | None]] = ContextVar(
    "current_scope", default=(None, None)
)

# §144: per-tenant concurrency budgets. A tenant can hold at most N concurrent
# in-flight requests; excess requests are rejected with 429. The default is
# DERIVED from the DB pool (never above it): the gate sits in front of the
# pool, and the old flat 50 exceeded the 12+10 pool — a tenant admitted past
# the gate still starved on pool timeouts that looked like another tenant's
# fault. TENANT_CONCURRENCY overrides the derivation for operators who sized
# their pool independently (0 = derive, the default).
DEFAULT_TENANT_QUEUE_DEPTH = 100


def default_tenant_concurrency() -> int:
    """The §144 gate default: the DB pool capacity itself.

    Each API/worker process owns one engine pool (db_pool_size +
    db_max_overflow) and one in-process governor, so per-tenant in-flight
    requests above the pool capacity cannot all be served — they would only
    queue against the pool's own acquire timeout and surface as 30-second
    TimeoutErrors. The gate therefore defaults to the pool capacity, and an
    explicit TENANT_CONCURRENCY=0 (or unset) keeps that derivation.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if settings.tenant_concurrency > 0:
        return settings.tenant_concurrency
    return settings.db_pool_size + settings.db_max_overflow


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
        self.concurrency = default_tenant_concurrency() if concurrency is None else concurrency
        self.queue_depth = DEFAULT_TENANT_QUEUE_DEPTH if queue_depth is None else queue_depth
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
            raise TenantBusyError(f"tenant {key} is at its concurrency cap with a full queue")
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


# --------------------------------------------------------------------- money --
#
# §47: a tenant trades in ONE currency, stored on its own row. A request that is
# already authenticated reads it off `TenantContext` for free (identity/deps.py
# selects it beside the lifecycle state); this is the path for the callers that
# have no request — the AI tool runtime, a worker, a script.
#
# It reaches for the Tenant row with a function-scope import for the same reason
# `app.core.mfa` does: the alternative is every commerce module importing
# `identity` to ask one question, and `tests/test_module_boundaries.py` counts
# each of those.

#: The currency the schema's server_defaults backfill, and the one every row
#: written before §47 was implemented asserted.
DEFAULT_CURRENCY = "EGP"


async def resolve_tenant_currency(session: AsyncSession, tenant_id: UUID) -> str:
    """The currency this tenant trades in (``DEFAULT_CURRENCY`` if unset)."""
    from sqlalchemy import select

    from app.modules.identity.models import Tenant

    code = (
        await session.execute(select(Tenant.currency).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    return (code or DEFAULT_CURRENCY).upper()


def set_current_scope(workspace_id: UUID | str | None, location_id: UUID | str | None):
    """Bind the §151 scope for this context; returns a reset token."""

    def _uuid(value: UUID | str | None) -> UUID | None:
        return None if value is None else UUID(str(value))

    return _current_scope.set((_uuid(workspace_id), _uuid(location_id)))


def current_scope() -> tuple[UUID | None, UUID | None]:
    return _current_scope.get()


def reset_current_scope(token) -> None:
    _current_scope.reset(token)


@asynccontextmanager
async def tenant_scope(session, tenant_id: UUID | str) -> AsyncIterator[UUID]:
    """Bind tenant on the session (RLS) and in the context (authz) for a block.

    The PREVIOUS context value is restored on exit (a ContextVar reset
    token), not flattened to None: the old `reset_current_tenant()` punched a
    hole through nesting — after an inner scope exited, the outer block's
    remaining code ran tenant-less, which an RLS-bound query fails closed on
    but any code that still needs the outer tenant (event envelopes, audit
    rows) silently lost. Fail-closed semantics are unchanged: entering with
    no prior binding still restores None, never a foreign tenant.
    """
    from app.core.db import bind_tenant

    tid = UUID(str(tenant_id))
    token = _current_tenant.set(tid)
    try:
        await bind_tenant(session, tid)
        yield tid
    finally:
        _current_tenant.reset(token)


# Tenant creation lifecycle hooks: decoupled registration without cross-module cycles.
_tenant_created_hooks: list = []


def register_tenant_created_hook(hook) -> None:
    if hook not in _tenant_created_hooks:
        _tenant_created_hooks.append(hook)


async def dispatch_tenant_created_hooks(session: AsyncSession, tenant_id: UUID) -> None:
    for hook in list(_tenant_created_hooks):
        await hook(session, tenant_id)
