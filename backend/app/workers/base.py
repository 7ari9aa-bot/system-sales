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
import uuid

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events.bus import ATTEMPTS_META_KEY, Event, EventBus
from app.modules.platform.models import OutboxEvent

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 60.0


class RetryableError(Exception):
    """Marker for transient failures — retried with backoff (the default path)."""


class PermanentError(Exception):
    """Marker for non-retryable failures — the event goes straight to the DLQ."""


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

    async def _process(self, event: Event) -> None:
        settings = get_settings()
        # Dedupe id: prefer the stable outbox row id (survives relay
        # crash-reclaim re-publishes); the bus-generated per-XADD uuid would
        # make every redelivery look new.
        dedupe_id = str(event.meta.get("outbox_id") or event.id)
        attempts = int(event.meta.get(ATTEMPTS_META_KEY, 0)) + 1
        try:
            await self.handle(event)
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
        await self._bus.ack(self.stream, self.group, event)

    async def _republish_after(self, event: Event, meta: dict, delay: float) -> None:
        """Durable retry: stage the event as an outbox row with not_before.

        The previous implementation slept in a fire-and-forget asyncio task —
        a SIGTERM during the backoff window lost the retry forever while the
        original entry was already acked. Staging through the outbox means
        only a Redis outage can delay a retry, never lose it.
        """
        from datetime import UTC, datetime, timedelta

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        aggregate_type = (
            event.stream.removesuffix(".events") if event.stream else "unknown"
        )
        async with SessionLocal() as session:
            async with session.begin():
                stmt = (
                    pg_insert(OutboxEvent)
                    .values(
                        aggregate_type=aggregate_type,
                        aggregate_id=uuid.UUID(str(event.meta.get("aggregate_id")))
                        if event.meta.get("aggregate_id")
                        else uuid.uuid4(),
                        stream=event.stream,
                        payload=event.payload,
                        meta=meta,
                        status="pending",
                        not_before=datetime.now(UTC) + timedelta(seconds=delay),
                    )
                    .on_conflict_do_nothing()
                )
                await session.execute(stmt)
