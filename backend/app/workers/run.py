"""Worker pool entrypoint: `python -m app.workers.run [pools...]`.

Runs the outbox relay plus the selected worker pools in one process. POOLS here
is the single declaration of what this codebase ships — every concrete
StreamWorker in `app/workers/` must appear in it exactly once, or be dispatched
by a scheduler job handler instead (see
`tests/test_worker_deployment_declaration.py`).

Per-pool deployments are an option, not the current state: passing pool names
runs a subset (`python -m app.workers.run messages webhooks`), which is how a
busy tier gets its own process. Nothing deploys it that way yet — the compose
`worker` service starts this entrypoint with no arguments, i.e. every pool in
one process, so an AI campaign today can still occupy a messaging worker slot.
The Railway topology carries only the API service, which is the gap recorded as
`TOPOLOGY_START_GAPS["railway"]` in the guard test.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.core.events.bus import RedisStreamsBus
from app.core.events.outbox import OutboxRelay
from app.core.redis import close_redis, get_redis
from app.workers.base import StreamWorker
from app.workers.campaign_worker import CampaignWorker
from app.workers.correlation import install_log_correlation
from app.workers.job_runner import JobRunner
from app.workers.message_worker import MessageWorker
from app.workers.platform_workers import NotificationWorker, WebhookWorker
from app.workers.scheduler_worker import SchedulerWorker

#: The worker process's log format. The `correlation_id=` field is the point
#: (O10): a worker line that names no message cannot be tied to the request
#: that caused it, which is what made the pools undebuggable in a fleet.
#: ``app.workers.correlation.install_log_correlation`` stamps the attribute on
#: every record, so this format never raises KeyError for it.
#: Pinned by tests/test_worker_correlation_logging.py — do not rename.
WORKER_LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s correlation_id=%(correlation_id)s %(message)s"
)

install_log_correlation()
logging.basicConfig(level=logging.INFO, format=WORKER_LOG_FORMAT)
logger = logging.getLogger(__name__)

POOLS: dict[str, type[StreamWorker]] = {
    "messages": MessageWorker,
    "notifications": NotificationWorker,
    "webhooks": WebhookWorker,
    # §144: bulk/campaign tier gets its OWN pool — a 100k-audience campaign
    # churns through campaign workers and can never occupy the message or
    # webhook pools that carry interactive traffic.
    "campaigns": CampaignWorker,
    "scheduler": SchedulerWorker,
    "jobs": JobRunner,
    # `RetentionWorker` is deliberately absent. It is not a pool: nothing can
    # wake it. Its `handle()` only acts on a payload whose event_type is
    # `retention.run`, and a stream name is derived from the aggregate type
    # (`core/events/writer.py:105` → `{aggregate_type}.events`), so no producer
    # can route such an event to the `platform.events` stream this class
    # subscribes to — `app/core/secrets.py:650` is the only publisher there and
    # it emits `platform.secret_rotated`. The live trigger is the durable
    # `retention.run` sweep the scheduler dispatches per active tenant
    # (`scheduler_worker.py`, `RECURRING_JOBS`), which re-uses
    # `RetentionWorker.run_once` — the agreed entry point. Leaving the pool in
    # would mean two declared triggers for one data-destroying sweep, with the
    # second one unable ever to fire.
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
