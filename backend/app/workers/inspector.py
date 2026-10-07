"""DLQ inspection and repair tooling.

The worker runtime dead-letters exhausted events to ``<stream>.dlq`` (see
StreamWorker and RedisStreamsBus.send_to_dlq). This module lets an operator
list what is stuck and move entries back to their source stream:

    python -m app.workers.inspector list orders
    python -m app.workers.inspector list orders --count 50
    python -m app.workers.inspector requeue orders 1715000000000-0

Requeueing copies the dead entry (fields intact) back to its source stream —
meta ``source_stream`` when present, else the DLQ stream minus its suffix —
and deletes it from the DLQ. The consumer group will pick it up as a new
entry; keep in mind the original ``attempts`` counter travels with it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import redis.asyncio as aioredis

from app.core.errors import ValidationError
from app.core.events.bus import DLQ_SUFFIX
from app.core.events.schemas import deserialize
from app.core.redis import get_redis


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _loads(value: Any) -> dict[str, Any]:
    """Parse a stored JSON field; malformed content is preserved under _raw."""
    raw = _text(value, "{}") or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": raw}


def _describe_entry(entry_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """One DLQ entry, read through the §19 envelope's read half.

    A real entry is rebuilt with ``deserialize()``, so the inspector never
    re-derives the envelope's field names by hand — and ``id`` is the ENVELOPE
    id, not the per-XADD bus uuid ``fields["id"]`` happens to hold. A row
    written before the envelope existed (there are such rows in production
    ``outbox_events``) cannot be deserialized; it is reported from its raw
    fields rather than raising, so the inspector still shows what is stuck.
    ``envelope`` tells the operator which shape they are looking at.
    """
    payload = _loads(fields.get("payload"))
    meta = _loads(fields.get("meta"))
    item: dict[str, Any] = {
        "entry_id": entry_id,
        "id": _text(fields.get("id"), entry_id),
        "payload": payload,
        "meta": meta,
        "envelope": False,
    }
    try:
        envelope = deserialize({"payload": payload, "meta": meta})
    except (ValidationError, KeyError, TypeError, ValueError):
        return item
    item.update(
        {
            "id": envelope.id,
            "type": envelope.type,
            "tenant_id": str(envelope.tenant_id),
            "occurred_at": envelope.occurred_at.isoformat(),
            "aggregate_type": envelope.aggregate_type,
            "aggregate_id": str(envelope.aggregate_id),
            "payload": envelope.payload,
            "meta": envelope.meta,
            "envelope": True,
        }
    )
    return item


async def list_dlq(client: aioredis.Redis, stream: str, count: int = 20) -> list[dict[str, Any]]:
    """List the oldest DLQ entries with the §19 envelope parsed.

    Each item: entry_id (Redis Streams id), id (envelope id), type, tenant_id,
    occurred_at, aggregate_type, aggregate_id, payload, meta (including
    dlq_reason and source_stream when present), and ``envelope``. A legacy row
    the envelope cannot describe is listed from its raw fields with
    ``envelope=False`` rather than crashing the inspector.
    """
    entries = await client.xrange(stream, min="-", max="+", count=count)
    return [_describe_entry(entry_id, fields) for entry_id, fields in entries]


def _source_stream(stream: str, meta: dict[str, Any]) -> str:
    source = meta.get("source_stream")
    if isinstance(source, bytes):
        source = source.decode()
    if source:
        return str(source)
    if stream.endswith(DLQ_SUFFIX):
        return stream[: -len(DLQ_SUFFIX)]
    return stream


async def requeue(client: aioredis.Redis, stream: str, entry_id: str) -> bool:
    """Move one DLQ entry back to its source stream.

    Returns False when the entry does not exist in the DLQ; otherwise the
    entry is XADD'ed to the source stream and XDEL'ed from the DLQ.
    """
    entries = await client.xrange(stream, min=entry_id, max=entry_id, count=1)
    if not entries:
        return False
    found_id, fields = entries[0]
    source = _source_stream(stream, _loads(fields.get("meta")))
    await client.xadd(source, fields)
    await client.xdel(stream, found_id)
    return True


async def _run(args: argparse.Namespace) -> None:
    client = get_redis()
    try:
        if args.command == "list":
            entries = await list_dlq(client, args.stream, count=args.count)
            if not entries:
                print(f"no entries in {args.stream}")
            for entry in entries:
                print(json.dumps(entry, default=str, sort_keys=True))
        elif args.command == "requeue":
            moved = await requeue(client, args.stream, args.entry_id)
            if moved:
                print(f"requeued {args.entry_id} from {args.stream}")
            else:
                print(f"entry {args.entry_id} not found in {args.stream}")
        else:  # pragma: no cover - argparse enforces choices
            raise SystemExit(f"unknown command: {args.command}")
    finally:
        await client.aclose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="app.workers.inspector",
        description="Inspect and requeue dead-letter queue (DLQ) entries",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="list the oldest DLQ entries as JSON")
    list_parser.add_argument("stream", help="DLQ stream name, e.g. orders.dlq")
    list_parser.add_argument("--count", type=int, default=20, help="max entries to show")

    requeue_parser = sub.add_parser("requeue", help="move one DLQ entry back to its source stream")
    requeue_parser.add_argument("stream", help="DLQ stream name, e.g. orders.dlq")
    requeue_parser.add_argument("entry_id", help="Redis Streams entry id of the dead entry")

    asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    main()
