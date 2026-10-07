"""Controlled recovery for published outbox events after Redis data loss.

The normal relay retries rows that were never published (pending/failed). A
Redis region move can also lose rows already marked ``published``. This module
replays only those published outbox rows whose consumer has no durable inbox
marker, preserving the original stable dedupe key. It is intentionally an
explicit operator action; it never runs as part of application startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from app.core.db import get_sessionmaker
from app.core.events.bus import EventBus

# These are the worker pools that consume outbox-backed streams. Scheduler and
# JobRunner poll durable Postgres tables directly and do not need Redis replay.
STREAM_CONSUMERS: dict[str, str] = {
    "message.events": "message-worker",
    "notification.events": "notification-worker",
    "webhook.events": "webhook-worker",
    "campaign_run.events": "campaign-worker",
}

_EVENT_KEY = "COALESCE(e.meta->>'outbox_id', e.meta->>'id', e.id::text)"
_ELIGIBLE = f"""
    e.status = 'published'
    AND e.stream = :stream
    AND (
        COALESCE(e.meta->>'outbox_id', e.meta->>'id') IS NOT NULL
        OR (e.stream = 'message.events' AND e.payload->>'event_type' = 'message.outbound')
    )
    AND NOT EXISTS (
        SELECT 1
          FROM processed_events p
         WHERE p.consumer_name = :consumer
           AND p.event_id::text = {_EVENT_KEY}
    )
    -- Retries preserve the original outbox_id. Select only the oldest copy of
    -- a logical event so recovery does not refill the stream with retry rows.
    AND NOT EXISTS (
        SELECT 1
          FROM outbox_events prior
         WHERE prior.status = 'published'
           AND prior.stream = e.stream
           AND COALESCE(prior.meta->>'outbox_id', prior.meta->>'id', prior.id::text)
               = {_EVENT_KEY}
           AND (prior.created_at, prior.id) < (e.created_at, e.id)
    )
"""

_COUNT_SQL = sa.text(f"SELECT count(*) FROM outbox_events e WHERE {_ELIGIBLE}")


@dataclass(frozen=True)
class ReplayResult:
    stream: str
    eligible: int
    published: int


def _consumer_for(stream: str) -> str:
    try:
        return STREAM_CONSUMERS[stream]
    except KeyError as exc:
        supported = ", ".join(sorted(STREAM_CONSUMERS))
        raise ValueError(f"unsupported recovery stream {stream!r}; choose: {supported}") from exc


async def replay_unprocessed_published(
    bus: EventBus,
    stream: str,
    *,
    execute: bool = False,
    batch_size: int = 250,
) -> ReplayResult:
    """Preview or republish eligible published rows for one known consumer.

    The default is a read-only preview. The caller must pass ``execute=True``
    for Redis writes. ``payload`` and ``meta`` are never logged or returned.
    """
    if batch_size < 1 or batch_size > 5_000:
        raise ValueError("batch_size must be between 1 and 5000")
    consumer = _consumer_for(stream)

    async with get_sessionmaker()() as session:
        eligible = int(
            (
                await session.execute(_COUNT_SQL, {"stream": stream, "consumer": consumer})
            ).scalar_one()
        )
        if not execute or eligible == 0:
            return ReplayResult(stream=stream, eligible=eligible, published=0)

        published = 0
        cursor_created_at: datetime | None = None
        cursor_id: UUID | None = None
        while True:
            cursor_clause = ""
            params: dict[str, Any] = {
                "stream": stream,
                "consumer": consumer,
                "limit": batch_size,
            }
            if cursor_created_at is not None and cursor_id is not None:
                cursor_clause = "AND (e.created_at, e.id) > (:cursor_created_at, :cursor_id)"
                params["cursor_created_at"] = cursor_created_at
                params["cursor_id"] = cursor_id

            rows = (
                (
                    await session.execute(
                        sa.text(
                            f"""
                        SELECT e.id, e.created_at, e.stream, e.payload, e.meta
                          FROM outbox_events e
                         WHERE {_ELIGIBLE}
                           {cursor_clause}
                         ORDER BY e.created_at, e.id
                         LIMIT :limit
                        """
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
            if not rows:
                break

            for row in rows:
                payload = dict(row["payload"] or {})
                meta = dict(row["meta"] or {})
                # Preserve legacy envelope ids and current outbox ids exactly;
                # consumers use these values as their idempotency key.
                if not meta.get("outbox_id") and not meta.get("id"):
                    # A small legacy class predates stable envelope ids. Only
                    # outbound-message events are eligible above: the message
                    # worker checks durable message state before sending, and
                    # this row id gives recovery a stable key.
                    meta["outbox_id"] = str(row["id"])
                await bus.publish(row["stream"], payload, meta)
                published += 1
            cursor_created_at = rows[-1]["created_at"]
            cursor_id = rows[-1]["id"]

    return ReplayResult(stream=stream, eligible=eligible, published=published)
