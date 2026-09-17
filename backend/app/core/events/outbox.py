"""Outbox relay: publishes events committed in Postgres to the event bus.

Flow (the core of "order created / event never lost"):

    BEGIN;
      ...business writes...
      INSERT INTO outbox_events (...);
    COMMIT;
      --> this relay picks the row up and publishes it.

The outbox_events table is created by the Stage-1 migrations; this module is
the runtime that drains it. Rows are claimed with FOR UPDATE SKIP LOCKED so
multiple relay instances can run concurrently.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import sqlalchemy as sa

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events.bus import EventBus

logger = logging.getLogger(__name__)

_CLAIM_SQL = sa.text(
    """
    UPDATE outbox_events
       SET status = 'publishing', attempts = attempts + 1
     WHERE id IN (
        SELECT id FROM outbox_events
         WHERE status = 'pending'
           AND attempts < :max_attempts
         ORDER BY created_at
         FOR UPDATE SKIP LOCKED
         LIMIT :batch
     )
    RETURNING id, stream, payload, meta
    """
)

_MARK_PUBLISHED_SQL = sa.text(
    "UPDATE outbox_events SET status = 'published', published_at = now() WHERE id = :id"
)

_MARK_FAILED_SQL = sa.text(
    "UPDATE outbox_events SET status = 'failed', last_error = :err WHERE id = :id"
)


class OutboxRelay:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._running = False

    async def run(self) -> None:
        settings = get_settings()
        self._running = True
        logger.info("outbox.relay.started")
        while self._running:
            try:
                drained = await self._drain_once(
                    batch=settings.outbox_batch_size,
                    max_attempts=settings.worker_max_attempts,
                )
            except Exception:
                # The relay must survive anything — including the DB being down.
                logger.exception("outbox.relay.drain_failed")
                drained = 0
            if not drained:
                await asyncio.sleep(settings.outbox_poll_interval_seconds)

    def stop(self) -> None:
        self._running = False

    async def _drain_once(self, batch: int, max_attempts: int) -> int:
        published = 0
        async with SessionLocal() as session:
            rows = (
                (
                    await session.execute(
                        _CLAIM_SQL, {"batch": batch, "max_attempts": max_attempts}
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                try:
                    await self._bus.publish(
                        row["stream"],
                        _loads(row["payload"]),
                        _loads(row["meta"]),
                    )
                    await session.execute(_MARK_PUBLISHED_SQL, {"id": row["id"]})
                    published += 1
                except Exception as exc:  # noqa: BLE001 — one bad event must not stop the relay
                    logger.exception("outbox.relay.publish_failed id=%s", row["id"])
                    await session.execute(
                        _MARK_FAILED_SQL, {"id": row["id"], "err": str(exc)[:500]}
                    )
            await session.commit()
        return published


def _loads(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)
