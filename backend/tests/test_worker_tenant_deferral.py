"""§48 worker deferral (review N-02, workers half).

The API path and the auth path were fixed first. Workers were still acting for
non-operational tenants: a suspended tenant's QUEUED outbound messages were
delivered, and outbound webhooks kept firing at their systems.

The important property is that a non-operational tenant's work is DEFERRED, not
failed. Dead-lettering it would destroy messages that should resume when the
tenant is reactivated, and consuming a retry attempt per poll would exhaust the
budget and dead-letter them anyway.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.events.bus import ATTEMPTS_META_KEY, Event
from app.modules.identity.models import Tenant
from app.workers.base import (
    DeferredError,
    PermanentError,
    RetryableError,
    StreamWorker,
    _is_permanent_failure,
    defer_unless_tenant_allows,
)


class _FakeBus:
    def __init__(self) -> None:
        self.acked: list[str] = []
        self.dlq: list[tuple[str, str]] = []

    async def ack(self, stream: str, group: str, event: Event) -> None:
        self.acked.append(event.id)

    async def send_to_dlq(self, stream: str, event: Event, reason: str) -> None:
        self.dlq.append((event.id, reason))


class _Worker(StreamWorker):
    """A worker whose handler raises whatever the test injects."""

    stream = "test.events"
    group = "test-workers"
    name = "test-worker"

    def __init__(self, bus, exc: BaseException) -> None:
        super().__init__(bus)
        self._exc = exc
        self.republished: list[tuple[dict, float]] = []

    async def handle(self, event: Event) -> None:
        raise self._exc

    async def _republish_after(self, event: Event, meta: dict, delay: float) -> None:
        # Overridden so the test does not need a database for the outbox row.
        self.republished.append((meta, delay))


def _event(**meta) -> Event:
    return Event(
        id="evt-1",
        stream="test.events",
        payload={"event_type": "test"},
        meta={"outbox_id": "outbox-1", **meta},
    )


# ------------------------------------------------------- DeferredError -----


def test_deferred_error_carries_an_explicit_delay() -> None:
    assert DeferredError("nope").delay_seconds == 900.0
    assert DeferredError("nope", delay_seconds=42).delay_seconds == 42


def test_a_deferred_error_is_not_a_permanent_failure() -> None:
    """If it were, a suspension would dead-letter the tenant's queued work."""
    assert not _is_permanent_failure(DeferredError("tenant is suspended"))
    # Sanity: the classifier does still catch the real permanent cases.
    assert _is_permanent_failure(PermanentError("boom"))
    assert _is_permanent_failure(ValidationError("bad input"))


async def test_a_deferred_event_does_not_consume_an_attempt() -> None:
    bus = _FakeBus()
    worker = _Worker(bus, DeferredError("tenant is suspended", delay_seconds=900))

    await worker._process(_event(**{ATTEMPTS_META_KEY: 2}))

    assert len(worker.republished) == 1
    meta, delay = worker.republished[0]
    # Attempts must be UNCHANGED: a long suspension cannot burn the budget.
    assert meta[ATTEMPTS_META_KEY] == 2
    assert delay == 900
    assert bus.acked == ["evt-1"]
    assert bus.dlq == []


async def test_a_retryable_event_still_increments_attempts() -> None:
    """The deferral path must not have broken ordinary retries."""
    bus = _FakeBus()
    worker = _Worker(bus, RetryableError("transient"))

    await worker._process(_event(**{ATTEMPTS_META_KEY: 1}))

    meta, delay = worker.republished[0]
    assert meta[ATTEMPTS_META_KEY] == 2
    assert 0 <= delay <= 60  # full jitter under MAX_BACKOFF_SECONDS
    assert bus.acked == ["evt-1"]
    assert bus.dlq == []


async def test_a_permanent_event_goes_to_the_dlq() -> None:
    bus = _FakeBus()
    worker = _Worker(bus, PermanentError("cannot ever succeed"))

    await worker._process(_event())

    assert worker.republished == []
    assert bus.dlq == [("evt-1", "permanent failure")]
    assert bus.acked == ["evt-1"]


# ------------------------------------------- defer_unless_tenant_allows -----


async def _set_state(db: AsyncSession, tenant_id, state: str) -> None:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one()
    tenant.lifecycle_state = state
    await db.flush()


async def test_an_active_tenant_is_not_deferred(db: AsyncSession, tenant_ctx):
    await defer_unless_tenant_allows(db, tenant_ctx.tenant_id, "allows_channels")
    await defer_unless_tenant_allows(db, tenant_ctx.tenant_id, "allows_automation")


@pytest.mark.parametrize("state", ["suspended", "offboarding", "deleted"])
async def test_a_non_operational_tenant_is_deferred(
    db: AsyncSession, tenant_ctx, state: str
):
    await _set_state(db, tenant_ctx.tenant_id, state)

    with pytest.raises(DeferredError) as exc:
        await defer_unless_tenant_allows(db, tenant_ctx.tenant_id, "allows_channels")
    assert state in str(exc.value)


async def test_an_unknown_state_is_deferred(db: AsyncSession, tenant_ctx):
    """Fail closed, matching the API gate."""
    await _set_state(db, tenant_ctx.tenant_id, "who-knows")

    with pytest.raises(DeferredError):
        await defer_unless_tenant_allows(db, tenant_ctx.tenant_id, "allows_channels")


async def test_the_capability_actually_selects_the_policy_field(
    db: AsyncSession, tenant_ctx
):
    """Offboarding keeps data access but not channels — the gate must respect it."""
    await _set_state(db, tenant_ctx.tenant_id, "offboarding")

    await defer_unless_tenant_allows(db, tenant_ctx.tenant_id, "allows_data_access")
    with pytest.raises(DeferredError):
        await defer_unless_tenant_allows(db, tenant_ctx.tenant_id, "allows_channels")


async def test_an_unknown_capability_name_defers(db: AsyncSession, tenant_ctx):
    """A typo in the capability must not silently allow the work."""
    with pytest.raises(DeferredError):
        await defer_unless_tenant_allows(db, tenant_ctx.tenant_id, "allows_everything")
