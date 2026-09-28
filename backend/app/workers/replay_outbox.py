"""Explicit operator command to recover Redis streams from the outbox.

Preview first (the default): ``python -m app.workers.replay_outbox --stream message.events``
Execute only after a fresh Redis instance is ready and the normal worker
consumers are stopped: ``python -m app.workers.replay_outbox --stream message.events --execute``
"""

from __future__ import annotations

import argparse
import asyncio

from app.core.events.bus import RedisStreamsBus
from app.core.events.replay import STREAM_CONSUMERS, replay_unprocessed_published
from app.core.redis import close_redis, get_redis


async def _run(stream: str, *, execute: bool, batch_size: int) -> None:
    bus = RedisStreamsBus(get_redis())
    try:
        result = await replay_unprocessed_published(
            bus, stream, execute=execute, batch_size=batch_size
        )
        action = "published" if execute else "eligible"
        print(
            f"stream={result.stream} consumer={STREAM_CONSUMERS[result.stream]} "
            f"eligible={result.eligible} published={result.published} mode="
            f"{'execute' if execute else 'preview'}"
        )
        if not execute:
            print(f"Preview only: {result.eligible} event(s) {action}; Redis was not changed.")
    finally:
        await close_redis()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or replay unprocessed published outbox events after Redis loss."
    )
    parser.add_argument("--stream", required=True, choices=sorted(STREAM_CONSUMERS))
    parser.add_argument(
        "--execute",
        action="store_true",
        help="publish eligible events to Redis; default is a read-only preview",
    )
    parser.add_argument("--batch-size", type=int, default=250)
    args = parser.parse_args()
    asyncio.run(_run(args.stream, execute=args.execute, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
