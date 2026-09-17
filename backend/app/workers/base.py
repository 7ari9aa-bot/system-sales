"""Worker runtime for Redis Streams consumers.

Retry semantics: on failure the event is republished to the same stream with an
incremented attempts counter after an exponential backoff with full jitter; the
original entry is acked so the consumer group keeps moving. After max_attempts
the event is routed to the DLQ stream (source stream + ".dlq").

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
from app.core.events.bus import ATTEMPTS_META_KEY, Event, EventBus

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 60.0


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
        consumer = f"{socket.gethostname()}:{os.getpid()}"
        self._running = True
        logger.info(
            "worker.started name=%s stream=%s group=%s consumer=%s",
            self.name,
            self.stream,
            self.group,
            consumer,
        )
        async for event in self._bus.consume(self.stream, self.group, consumer):
            if not self._running:
                break
            await self._process(event)

    def stop(self) -> None:
        self._running = False

    async def _process(self, event: Event) -> None:
        settings = get_settings()
        attempts = int(event.meta.get(ATTEMPTS_META_KEY, 0)) + 1
        try:
            await self.handle(event)
        except Exception:
            logger.exception(
                "worker.handle_failed stream=%s id=%s attempt=%s",
                self.stream,
                event.id,
                attempts,
            )
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
        async def _later() -> None:
            await asyncio.sleep(delay)
            await self._bus.publish(self.stream, event.payload, meta)

        asyncio.create_task(_later())
