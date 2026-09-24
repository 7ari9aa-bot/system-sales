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
import hashlib
import logging
import os
import random
import socket
from contextlib import suppress
from typing import Any

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

# Outcomes of StreamWorker._claim_inbox (ADR-058).
_INBOX_CLAIMED = "claimed"  # lock held, no marker: we own the effect
_INBOX_SEEN = "seen"  # marker committed by an earlier run: ack and skip
_INBOX_CONTESTED = "contested"  # a live worker holds the claim: stand down
_INBOX_UNAVAILABLE = "unavailable"  # inbox unreachable: fail open, as before


def _inbox_lock_key(consumer_name: str, event_id: str) -> int:
    """Advisory-lock key for one (consumer, event id) pair.

    Same idiom as app.core.lease — a value that fits Postgres' signed bigint
    advisory-lock space — but hashed over the PAIR, because the dedupe unit is
    (consumer_name, event_id): the same event handled by two different pools
    must not serialize against one key, and two events of one pool must not
    share a key either.
    """
    digest = hashlib.sha256(f"{consumer_name}\x1f{event_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % (2**63 - 1)


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
                # takeover) at most once a minute. A reclaim that hands a
                # still-running entry to a second worker is absorbed by the
                # exclusive inbox claim in _process_event (ADR-058): the
                # second claimer stands down without acking.
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
        envelope_meta = self._envelope_meta(event)
        # Dedupe id: prefer the stable outbox row id (survives relay
        # crash-reclaim re-publishes); the bus-generated per-XADD uuid would
        # make every redelivery look new.
        dedupe_id = str(envelope_meta.get("outbox_id") or event.id)
        attempts = int(envelope_meta.get(ATTEMPTS_META_KEY, 0)) + 1

        # §127, hardened per ADR-058: the consumer inbox is a CLAIM, not a
        # read-then-act. One transaction takes a pg_try_advisory_xact_lock on
        # (consumer, event id) — the house idiom from app.core.lease — checks
        # the processed_events marker INSIDE the lock, stays open across
        # handle(), and writes the marker at the end, so COMMIT publishes
        # "done" atomically with the lock release. For one event id at most
        # one worker can be inside the effect: a concurrent redelivery (an
        # XAUTOCLAIM reclaim racing a slow handler) either finds the lock held
        # — it stands down WITHOUT acking, leaving the entry in the PEL — or
        # finds the committed marker and acks past it. A crash or a failed
        # effect rolls the claim transaction back, so a claim never outlives
        # its effect and no window loses an event (the old marker-after-effect
        # order kept that property; it is preserved deliberately).
        #
        # Postgres' default READ COMMITTED is load-bearing: a claimer that
        # arrives after the winner commits sees the marker on its very first
        # statement. If the inbox itself is unreachable we fail open exactly
        # as before — handlers may carry their own dedupe (message_worker
        # does; it sets _skip_generic_idempotency and is excluded here).
        claim: tuple[Any, Any] | None = None
        if not getattr(self, "_skip_generic_idempotency", False):
            state, session, tx = await self._claim_inbox(dedupe_id)
            if state == _INBOX_CONTESTED:
                logger.info(
                    "worker.inbox_contended stream=%s consumer=%s id=%s",
                    self.stream, self.name, dedupe_id,
                )
                return
            if state == _INBOX_SEEN:
                logger.info(
                    "worker.idempotent_skip stream=%s consumer=%s id=%s",
                    self.stream, self.name, dedupe_id,
                )
                await self._bus.ack(self.stream, self.group, event)
                return
            if state == _INBOX_CLAIMED:
                claim = (session, tx)

        effect_ran = False
        try:
            effect_ran = await self._run_with_lineage(event, dedupe_id, attempts)
        finally:
            if claim is not None:
                await self._close_inbox(*claim, dedupe_id, marker=effect_ran)
        if effect_ran:
            await self._bus.ack(self.stream, self.group, event)

    async def _claim_inbox(self, dedupe_id: str) -> tuple[str, Any, Any]:
        """Open the transaction that OWNS this event's inbox claim.

        Returns ``(state, session, tx)``; on _INBOX_CLAIMED the caller owns an
        open transaction and MUST finish it via _close_inbox(). Every other
        state leaves nothing open. Exceptions from the inbox itself are
        swallowed here (fail open, _INBOX_UNAVAILABLE) — a broken dedupe table
        must not stop the pool, matching the pre-ADR-058 policy.
        """
        from sqlalchemy import text as sa_text

        try:
            session = SessionLocal()
            tx = await session.begin()
            locked = (
                await session.execute(
                    sa_text("SELECT pg_try_advisory_xact_lock(:key)"),
                    {"key": _inbox_lock_key(self.name, dedupe_id)},
                )
            ).scalar()
            if not locked:
                await self._abandon_inbox(session, tx)
                return _INBOX_CONTESTED, None, None
            seen = (
                await session.execute(
                    sa_text(
                        "SELECT 1 FROM processed_events "
                        "WHERE consumer_name = :consumer AND event_id = :eid "
                        "LIMIT 1"
                    ),
                    {"consumer": self.name, "eid": dedupe_id},
                )
            ).first()
            if seen:
                await self._abandon_inbox(session, tx)
                return _INBOX_SEEN, None, None
            return _INBOX_CLAIMED, session, tx
        except Exception:
            logger.debug(
                "worker.idempotency_check_failed stream=%s id=%s",
                self.stream, dedupe_id, exc_info=True,
            )
            with suppress(Exception):
                await session.close()  # type: ignore[possibly-undefined]
            return _INBOX_UNAVAILABLE, None, None

    @staticmethod
    async def _abandon_inbox(session: Any, tx: Any) -> None:
        """Close a claim transaction that will not carry an effect."""
        with suppress(Exception):
            await tx.rollback()
        with suppress(Exception):
            await session.close()

    async def _close_inbox(
        self, session: Any, tx: Any, dedupe_id: str, *, marker: bool
    ) -> None:
        """End the claim transaction, atomically with the marker when asked.

        marker=True writes the processed_events row INSIDE the claim
        transaction, so the COMMIT that releases the lock is the same commit
        that makes "done" visible — there is no window between the two.
        marker=False (the effect failed or deferred) commits nothing: the
        transaction holds no writes, and ending it releases the lock so the
        staged retry — or a PEL reclaim — can claim the event again.
        """
        from sqlalchemy import text as sa_text

        try:
            if marker:
                await session.execute(
                    sa_text(
                        "INSERT INTO processed_events "
                        "(id, consumer_name, event_id, status) "
                        "VALUES (gen_random_uuid(), :consumer, :eid, 'done') "
                        "ON CONFLICT (consumer_name, event_id) DO NOTHING"
                    ),
                    {"consumer": self.name, "eid": dedupe_id},
                )
            await tx.commit()
        except Exception:
            logger.debug(
                "worker.idempotency_write_failed stream=%s id=%s",
                self.stream, dedupe_id, exc_info=True,
            )
            with suppress(Exception):
                await tx.rollback()
        finally:
            with suppress(Exception):
                await session.close()

    async def _run_with_lineage(self, event: Event, dedupe_id: str, attempts: int) -> bool:
        """Run handle() under the §66/§68 lineage context.

        Returns True when the effect succeeded — only then may the caller mark
        the event processed and ack it. Every failure path (defer / retry /
        DLQ) acks inside and returns False WITHOUT a marker, so retries and
        DLQ replays stay reprocessable.
        """
        settings = get_settings()
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
            return False
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
                return False
            if attempts >= settings.worker_max_attempts:
                await self._bus.send_to_dlq(self.stream, event, "max attempts exceeded")
                await self._bus.ack(self.stream, self.group, event)
                return False
            meta = {**event.meta, ATTEMPTS_META_KEY: attempts}
            base = min(
                settings.worker_backoff_base_seconds * (2 ** (attempts - 1)),
                MAX_BACKOFF_SECONDS,
            )
            delay = random.uniform(0, base)  # full jitter
            await self._republish_after(event, meta, delay)
            await self._bus.ack(self.stream, self.group, event)
            return False
        return True

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
