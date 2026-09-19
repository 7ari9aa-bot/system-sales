"""Event bus: interface + Redis Streams implementation.

The bus is a TRANSPORT, not a source of truth. Events are first committed to
Postgres via the outbox table inside the business transaction; the relay then
forwards them here. Losing Redis means losing in-flight triggers only — we
replay from the outbox, never from Redis.

The EventBus protocol exists so the broker can later become Kafka/Redpanda
without touching the Domain.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

DLQ_SUFFIX = ".dlq"
ATTEMPTS_META_KEY = "attempts"


@dataclass
class Event:
    id: str
    stream: str
    payload: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    entry_id: str | None = None  # Redis Streams entry id, set on consume


class EventBus(Protocol):
    async def publish(
        self, stream: str, payload: dict[str, Any], meta: dict[str, Any] | None = None
    ) -> str:
        ...

    def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        block_ms: int | None = None,
    ) -> AsyncIterator[Event]:
        ...

    async def ack(self, stream: str, group: str, event: Event) -> None:
        ...


class RedisStreamsBus:
    def __init__(self, client: aioredis.Redis, maxlen: int = 100_000) -> None:
        self._client = client
        self._maxlen = maxlen

    async def publish(
        self, stream: str, payload: dict[str, Any], meta: dict[str, Any] | None = None
    ) -> str:
        entry_id = await self._client.xadd(
            stream,
            {
                "id": str(uuid.uuid4()),
                "ts": str(time.time()),
                "payload": json.dumps(payload, default=str),
                "meta": json.dumps(meta or {}, default=str),
            },
            maxlen=self._maxlen,
            approximate=True,
        )
        return entry_id

    async def _ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._client.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        block_ms: int | None = None,
    ) -> AsyncIterator[Event]:
        from app.core.config import get_settings

        block_ms = block_ms if block_ms is not None else get_settings().consumer_block_ms
        await self._ensure_group(stream, group)
        while True:
            resp = await self._client.xreadgroup(
                group,
                consumer,
                {stream: ">"},
                count=10,
                block=block_ms,
            )
            for stream_name, entries in resp or []:
                for entry_id, fields in entries:
                    yield Event(
                        id=fields.get("id", entry_id),
                        stream=stream_name,
                        payload=json.loads(fields.get("payload", "{}")),
                        meta=json.loads(fields.get("meta", "{}")),
                        entry_id=entry_id,
                    )

    async def ack(self, stream: str, group: str, event: Event) -> None:
        if event.entry_id is not None:
            await self._client.xack(stream, group, event.entry_id)

    async def reclaim_stale(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int = 60_000,
        count: int = 20,
    ) -> list[Event]:
        """XAUTOCLAIM: take over entries a crashed worker left in the PEL.

        XREADGROUP ">" only ever returns NEW entries, so an entry read by a
        worker that died before acking was stranded forever. Claiming moves
        idle entries to OUR PEL and returns them for processing; idempotent
        consumers make the possible double-processing safe.
        """
        await self._ensure_group(stream, group)
        try:
            _cursor, entries, _deleted = await self._client.xautoclaim(
                stream, group, consumer, min_idle_time=min_idle_ms, count=count
            )
        except ResponseError as exc:
            # XAUTOCLAIM needs Redis >= 6.2; degrade to "nothing to reclaim".
            if "unknown command" in str(exc).lower():
                return []
            raise
        events: list[Event] = []
        for entry_id, fields in entries or []:
            events.append(
                Event(
                    id=fields.get("id", entry_id),
                    stream=stream,
                    payload=json.loads(fields.get("payload", "{}")),
                    meta=json.loads(fields.get("meta", "{}")),
                    entry_id=entry_id,
                )
            )
        return events

    async def send_to_dlq(self, stream: str, event: Event, reason: str) -> None:
        """Dead-letter the event with its failure history attached."""
        meta = dict(event.meta)
        meta["dlq_reason"] = reason
        meta["source_stream"] = stream
        await self.publish(stream + DLQ_SUFFIX, event.payload, meta)
