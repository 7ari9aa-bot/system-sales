"""Worker pool entrypoint: `python -m app.workers.run [pools...]`.

Runs the outbox relay plus the selected worker pools in one process. In
production each pool gets its own deployment so AI load can never squeeze the
messaging hot path.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.core.events.bus import RedisStreamsBus
from app.core.events.outbox import OutboxRelay
from app.core.redis import close_redis, get_redis
from app.workers.base import StreamWorker
from app.workers.message_worker import MessageWorker
from app.workers.platform_workers import NotificationWorker, WebhookWorker
from app.workers.retention_worker import RetentionWorker
from app.workers.scheduler_worker import SchedulerWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

POOLS: dict[str, type[StreamWorker]] = {
    "messages": MessageWorker,
    "notifications": NotificationWorker,
    "webhooks": WebhookWorker,
    "scheduler": SchedulerWorker,
    "retention": RetentionWorker,
}


async def main(pools: list[str]) -> None:
    bus = RedisStreamsBus(get_redis())
    tasks = [asyncio.create_task(OutboxRelay(bus).run(), name="outbox-relay")]
    try:
        for pool in pools:
            worker_cls = POOLS.get(pool)
            if worker_cls is None:
                raise SystemExit(f"unknown pool: {pool} (available: {', '.join(POOLS)})")
            tasks.append(asyncio.create_task(worker_cls(bus).run(), name=pool))
        logger.info("workers.running pools=%s", pools)
        await asyncio.gather(*tasks)
    finally:
        await close_redis()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run worker pools")
    parser.add_argument(
        "pools",
        nargs="*",
        default=list(POOLS),
        help=f"pools to run (default: all of {', '.join(POOLS)})",
    )
    asyncio.run(main(parser.parse_args().pools))
