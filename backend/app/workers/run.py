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
import signal

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


#: Seconds a draining worker gets to finish its in-flight event before the
#: task is cancelled. At-least-once redelivery covers whatever an overrun
#: leaves behind, so this bounds deploy/scale-down stalls, not correctness.
DRAIN_GRACE_SECONDS = 15.0


def install_signal_handlers(stop: asyncio.Event) -> None:
    """SIGTERM (platform deploys) and SIGINT (Ctrl+C) request a drain.

    Windows dev loops raise NotImplementedError for add_signal_handler —
    there the default KeyboardInterrupt path applies and tests skip.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            logger.warning("signal handler unavailable for %s", sig.name)


async def main(pools: list[str], *, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    from app.modules.ai.core.registry import discover_agents

    discover_agents()
    bus = RedisStreamsBus(get_redis())
    relay = OutboxRelay(bus)
    tasks = [asyncio.create_task(relay.run(), name="outbox-relay")]
    workers: list = []
    try:
        for pool in pools:
            worker_cls = POOLS.get(pool)
            if worker_cls is None:
                raise SystemExit(f"unknown pool: {pool} (available: {', '.join(POOLS)})")
            worker = worker_cls(bus)
            workers.append(worker)
            tasks.append(asyncio.create_task(worker.run(), name=pool))
        logger.info("workers.running pools=%s", pools)
        install_signal_handlers(stop)
        stop_task = asyncio.create_task(stop.wait(), name="shutdown-signal")
        # A crashed pool task fires FIRST_COMPLETED too: its exception is
        # re-raised below — crash-only supervision, the platform restarts.
        await asyncio.wait([*tasks, stop_task], return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set():
            logger.info("workers.draining pools=%s grace_seconds=%s", pools, DRAIN_GRACE_SECONDS)
            for worker in workers:
                worker.stop()
            relay.stop()
            stop_wait = asyncio.create_task(asyncio.sleep(DRAIN_GRACE_SECONDS))
            await asyncio.wait([*tasks, stop_wait], timeout=DRAIN_GRACE_SECONDS)
            stop_wait.cancel()
        for task in tasks:
            if task.done() and not task.cancelled() and task.exception() is not None:
                raise task.exception()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
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

    # P0-4 schema-skew gate: the workers service has NO pre-deploy (the api
    # service owns `alembic upgrade head`, and two concurrent runs would race
    # for the migration lock). A workers deploy that lands before the api's
    # pre-deploy used to boot new code against an old schema and crash every
    # pool on the first missing relation. Refusing here turns that skew into a
    # crash-loop with an actionable message instead. Kept in the process
    # entrypoint — not main() — because main() is the unit-tested orchestrator
    # that tests drive without a database.
    import sys

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings
    from app.core.schema_guard import SchemaSkewError, assert_schema_current

    async def _schema_gate() -> None:
        engine = create_async_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            connect_args={"statement_cache_size": 0},
        )
        try:
            await assert_schema_current(engine)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_schema_gate())
    except SchemaSkewError as exc:
        sys.exit(f"workers refusing to start: {exc}")

    args = parser.parse_args()
    asyncio.run(main(args.pools))
