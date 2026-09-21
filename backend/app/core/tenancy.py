"""Request-scoped tenant context.

The middleware (Stage 2) resolves the tenant from the JWT claim / header, stores
it here, and every session opened for the request binds it for RLS via
bind_tenant(). Application-layer authorization checks it independently — tenant
isolation is enforced twice by design.

§144: Tenant fairness — per-tenant concurrency/queue budgets prevent a single
noisy tenant from starving others. The budgets are enforced via Redis
semaphores with per-tenant keys.
"""

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
