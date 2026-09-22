"""Worker runtime for Redis Streams consumers.

Retry semantics: on failure the event is republished to the same stream with an
incremented attempts counter after an exponential backoff with full jitter; the
original entry is acked so the consumer group keeps moving. After max_attempts
the event is routed to the DLQ stream (source stream + ".dlq").

Failures are classified: PermanentError and the domain "expected failure"
errors (validation / permission / not found / conflict — see app.core.errors)
can never succeed on retry and go STRAIGHT to the DLQ with reason
"permanent failure"; everything else follows the backoff/retry path above.

Stage 3 hardens this with not_before scheduling through the outbox so a crash
between ack and republish can never lose an event.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import socket

from app.core.config import get_settings
from app.core.context import (
    actor_kind_contextvar,
    correlation_id_contextvar,
    credentials_audit_contextvar,
)
from app.core.db import SessionLocal
from app.core.errors import ValidationError
from app.core.events.bus import ATTEMPTS_META_KEY, Event, EventBus
from app.core.events.schemas import deserialize, deserialize_event

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 60.0


class RetryableError(Exception):
    """Marker for transient failures — retried with backoff (the default path)."""


class PermanentError(Exception):
    """Marker for non-retryable failures — the event goes straight to the DLQ."""


class DeferredError(Exception):
    """The event cannot run YET, but is not a failure (§48).

    Raised when the owning tenant is not operational: a suspended tenant's
    outbound messages must not be delivered, but must not be dead-lettered
    either — they have to resume if the tenant is reactivated.

    The runtime defers via the outbox with an explicit delay and, crucially,
    does NOT increment the attempts counter, so a long suspension cannot burn
    the retry budget and dead-letter a tenant's queued messages.
    """

    def __init__(self, reason: str, *, delay_seconds: float = 900.0) -> None:
        super().__init__(reason)
        self.delay_seconds = delay_seconds


async def defer_unless_tenant_allows(session, tenant_id, capability: str) -> None:
    """Raise DeferredError when the tenant's lifecycle state forbids `capability`.

    `capability` is a field on TenantCapabilityPolicy: allows_api, allows_ai,
    allows_channels, allows_automation, allows_data_access, allows_login.
    Fails CLOSED on an unknown state, matching the API gate in identity.deps.
    """
    from sqlalchemy import select

    from app.modules.identity.models import Tenant
    from app.modules.identity.service import STATE_POLICIES

    state = (
        await session.execute(
            select(Tenant.lifecycle_state).where(Tenant.id == tenant_id)
        )
    ).scalar_one_or_none()
    policy = STATE_POLICIES.get(state) if state else None
    if policy is None or not getattr(policy, capability, False):
        raise DeferredError(
            f"tenant is {state or 'unknown'} — {capability} is not available"
        )


def _is_permanent_failure(exc: BaseException) -> bool:
    """True when exc (or anything it wraps) must not be retried.

    PermanentError markers and the domain "expected failure" errors (validation,
    permission denied, not found, conflict) can never succeed on retry, so the
    worker dead-letters immediately instead of burning attempts. app.core.errors
    is imported lazily inside the call to avoid import cycles.
    """
    from app.core.errors import (
        ConflictError,
        NotFoundError,
        PermissionDeniedError,
        ValidationError,
    )

    permanent_types: tuple[type[BaseException], ...] = (
        PermanentError,
        ValidationError,
        PermissionDeniedError,
        NotFoundError,
        ConflictError,
    )
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, permanent_types):
            return True
        if current.__suppress_context__:
            current = current.__cause__
        else:
            current = current.__cause__ or current.__context__
    return False


class StreamWorker:
    """Base class for all worker pools (message / AI / analytics / ...)."""

    stream: str = ""
    group: str = ""
    name: str = "stream-worker"

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._running = False

    async def handle(self, event: Event) -> None:  # pragma: no cover - abstract by design
        raise NotImplementedError

    async def run(self) -> None:
        import time

        consumer = f"{socket.gethostname()}:{os.getpid()}"
        self._running = True
        last_reclaim = 0.0
        logger.info(
            "worker.started name=%s stream=%s group=%s consumer=%s",
            self.name,
            self.stream,
            self.group,
            consumer,
        )
        while self._running:
            try:
                # Reclaim entries stranded by crashed workers (§128-style PEL
                # takeover) at most once a minute. Idempotent handlers make a
                # possible double-processing safe.
                now = time.monotonic()
                if now - last_reclaim > 60:
                    last_reclaim = now
                    stale = await self._bus.reclaim_stale(
                        self.stream, self.group, consumer, min_idle_ms=60_000
                    )
                    for event in stale:
                        await self._process(event)
                        if not self._running:
                            break
                if not self._running:
                    break
                async for event in self._bus.consume(self.stream, self.group, consumer):
                    if not self._running:
                        break
                    await self._process(event)
            except TimeoutError as exc:
                # Blocked XREADGROUP idle timeout or a network hiccup —
                # reconnect and keep polling. Never kill the pool process.
                logger.warning("worker.stream_timeout stream=%s err=%s", self.stream, exc)
                await asyncio.sleep(1.0)
            except Exception:
                logger.exception("worker.loop_crashed stream=%s", self.stream)
                await asyncio.sleep(2.0)
                if not self._running:
                    break

    def stop(self) -> None:
        self._running = False

    def _envelope_meta(self, event: Event) -> dict:
        """User meta of the event's §19 envelope (dedupe key + retry counter).

        Read through the envelope's read half (finding 2) instead of
        hand-parsing the transport meta. The worker runtime must not crash on a
        malformed bus entry, so a non-envelope event falls back to the raw
        transport meta; the retry staging path rejects such an event explicitly.
        """
        try:
            return deserialize_event(event).meta
        except (ValidationError, KeyError, TypeError, ValueError):
            return dict(event.meta)

    async def _process(self, event: Event) -> None:
        """Handle one event, then pay for the time it took.

        §144: WORKER_SECONDS is charged to the envelope's tenant on EVERY
        handled event — success, failure, retry-later alike (a crashing
        handler burned real capacity). The charge is pure accounting here:
        the GATE lives on the throttled tiers (bulk/campaign defer on an
        exhausted budget), because the §144 priority order forbids human /
        AI / webhook work from being starved by a tenant's own meter.
        """
        import time

        started = time.monotonic()
        try:
            await self._process_event(event)
        finally:
            await self._charge_worker_seconds(event, started)

    async def _charge_worker_seconds(self, event: Event, started: float) -> None:
        import math
        import time

        try:
            envelope = deserialize_event(event)
        except (ValidationError, KeyError, TypeError, ValueError):
            return  # no tenant attribution → charge nobody
        units = max(1, math.ceil(time.monotonic() - started))
        try:
            from app.core.fairness import ResourceType, consume

            await consume(envelope.tenant_id, ResourceType.WORKER_SECONDS, units=units)
        except Exception:  # noqa: BLE001 — metering must never break handling
            logger.debug("worker.metering_failed id=%s", event.id, exc_info=True)

    async def _process_event(self, event: Event) -> None:
        settings = get_settings()
        envelope_meta = self._envelope_meta(event)
        # Dedupe id: prefer the stable outbox row id (survives relay
        # crash-reclaim re-publishes); the bus-generated per-XADD uuid would
        # make every redelivery look new.
        dedupe_id = str(envelope_meta.get("outbox_id") or event.id)
        attempts = int(envelope_meta.get(ATTEMPTS_META_KEY, 0)) + 1

        # §127: generic consumer idempotency. Every StreamWorker gets a
        # ProcessedEvent check — not just message_worker. A redelivered event
        # that was already processed hits the unique constraint and is skipped.
        # message_worker does its own finer-grained check (per delivery phase),
        # so it sets _skip_generic_idempotency = True.
        if not getattr(self, "_skip_generic_idempotency", False):
            from sqlalchemy import text as sa_text

            from app.core.db import SessionLocal

            # §127: read-only pre-check — was this event already processed?
            # The marker itself is written AFTER handle() succeeds (see below):
            # writing it before the effect (the old order) survived a transient
            # failure and permanently suppressed the redelivery — a LOST event.
            try:
                async with SessionLocal() as idem_session:
                    seen = (
                        await idem_session.execute(
                            sa_text(
                                "SELECT 1 FROM processed_events "
                                "WHERE consumer_name = :consumer AND event_id = :eid "
                                "LIMIT 1"
                            ),
                            {"consumer": self.name, "eid": dedupe_id},
                        )
                    ).first()
                if seen:
                    logger.info(
                        "worker.idempotent_skip stream=%s consumer=%s id=%s",
                        self.stream, self.name, dedupe_id,
                    )
                    await self._bus.ack(self.stream, self.group, event)
                    return
            except Exception:
                # If the idempotency table is unavailable, fail open —
                # the handler may have its own dedupe (message_worker does).
                logger.debug(
                    "worker.idempotency_check_failed stream=%s id=%s",
                    self.stream, dedupe_id, exc_info=True,
                )

        # §66: publish the envelope's lineage into request-scoped context for
        # the duration of the handler, so audit rows written while processing
        # carry source="system" and the correlation_id of the event that
        # caused them (NULL when the entry is not a §19 envelope). Also
        # installs a fresh §68 credential-audit batch set per event.
        try:
            event_correlation_id: str | None = deserialize_event(event).correlation_id
        except (ValidationError, KeyError, TypeError, ValueError):
            event_correlation_id = None
        _cor_token = correlation_id_contextvar.set(event_correlation_id)
        _kind_token = actor_kind_contextvar.set("system")
        _audit_token = credentials_audit_contextvar.set(set())
        try:
            try:
                await self.handle(event)
            finally:
                correlation_id_contextvar.reset(_cor_token)
                actor_kind_contextvar.reset(_kind_token)
                credentials_audit_contextvar.reset(_audit_token)
        except DeferredError as exc:
            # Not a failure: defer with an explicit delay and leave the attempts
            # counter untouched, so a long suspension cannot exhaust the retry
            # budget and dead-letter a tenant's queued work.
            logger.info(
                "worker.deferred stream=%s id=%s reason=%s delay=%ss",
                self.stream,
                dedupe_id,
                exc,
                exc.delay_seconds,
            )
            await self._republish_after(event, event.meta, exc.delay_seconds)
            await self._bus.ack(self.stream, self.group, event)
            return
        except Exception as exc:
            logger.exception(
                "worker.handle_failed stream=%s id=%s attempt=%s",
                self.stream,
                dedupe_id,
                attempts,
            )
            if _is_permanent_failure(exc):
                logger.warning(
                    "worker.permanent_failure stream=%s id=%s attempt=%s",
                    self.stream,
                    dedupe_id,
                    attempts,
                )
                await self._bus.send_to_dlq(self.stream, event, "permanent failure")
                await self._bus.ack(self.stream, self.group, event)
                return
            if attempts >= settings.worker_max_attempts:
                await self._bus.send_to_dlq(self.stream, event, "max attempts exceeded")
                await self._bus.ack(self.stream, self.group, event)
                return
            meta = {**event.meta, ATTEMPTS_META_KEY: attempts}
            base = min(
                settings.worker_backoff_base_seconds * (2 ** (attempts - 1)),
                MAX_BACKOFF_SECONDS,
            )
            delay = random.uniform(0, base)  # full jitter
            await self._republish_after(event, meta, delay)
            await self._bus.ack(self.stream, self.group, event)
            return
        # §127: record the processed marker only after the effect committed.
        # A crash between the effect and this write replays handle() on
        # redelivery — handlers are status-guarded and idempotent — whereas a
        # pre-written marker turned any transient failure into a lost event.
        # Deferred/permanent-failure paths above return BEFORE this write, so
        # retries and DLQ replays stay reprocessable.
        if not getattr(self, "_skip_generic_idempotency", False):
            from sqlalchemy import text as sa_text

            from app.core.db import SessionLocal

            try:
                async with SessionLocal() as idem_session:
                    async with idem_session.begin():
                        await idem_session.execute(
                            sa_text(
                                "INSERT INTO processed_events "
                                "(id, consumer_name, event_id, status) "
                                "VALUES (gen_random_uuid(), :consumer, :eid, 'done') "
                                "ON CONFLICT (consumer_name, event_id) DO NOTHING"
                            ),
                            {"consumer": self.name, "eid": dedupe_id},
                        )
            except Exception:
                logger.debug(
                    "worker.idempotency_write_failed stream=%s id=%s",
                    self.stream, dedupe_id, exc_info=True,
                )
        await self._bus.ack(self.stream, self.group, event)

    async def _republish_after(self, event: Event, meta: dict, delay: float) -> None:
        """Durable retry: stage the event as an outbox row with not_before.

        The previous implementation slept in a fire-and-forget asyncio task —
        a SIGTERM during the backoff window lost the retry forever while the
        original entry was already acked. Staging through the outbox means
        only a Redis outage can delay a retry, never lose it.

        The row is staged through ``add_outbox_event`` — the ONLY way domain
        code stages events — so the retry carries a real §19 envelope instead
        of a hand-inserted row that merely copied one (finding 3). The
        consumer-inbox dedupe key (``meta["outbox_id"]``) is preserved from the
        original event ON PURPOSE: a retry must dedupe against the attempt it
        is retrying, not look like a brand-new event (that would double-send).
        """
        from datetime import UTC, datetime, timedelta

        from app.core.events.writer import add_outbox_event

        try:
            envelope = deserialize({"payload": event.payload, "meta": meta})
        except (ValidationError, KeyError, TypeError, ValueError):
            # Not a §19 envelope, so the canonical writer cannot stage it.
            # Unreachable for relay-published rows — log loudly, never guess.
            logger.error(
                "worker.retry_not_an_envelope stream=%s id=%s", self.stream, event.id
            )
            return

        original_outbox_id = envelope.meta.get("outbox_id")
        async with SessionLocal() as session:
            async with session.begin():
                # §125: bind tenant GUC so the outbox insert is tenant-scoped.
                from app.core.db import bind_tenant

                await bind_tenant(session, envelope.tenant_id)
                retry = await add_outbox_event(
                    session,
                    aggregate_type=envelope.aggregate_type,
                    aggregate_id=envelope.aggregate_id,
                    event_type=envelope.type,
                    tenant_id=envelope.tenant_id,
                    payload=envelope.payload,
                    meta=envelope.meta,
                    correlation_id=envelope.correlation_id,
                    causation_id=envelope.causation_id,
                    producer=envelope.producer,
                    schema_version=envelope.schema_version,
                    aggregate_version=envelope.aggregate_version,
                )
                retry.not_before = datetime.now(UTC) + timedelta(seconds=delay)
                if original_outbox_id:
                    retry.meta = {**retry.meta, "outbox_id": original_outbox_id}
