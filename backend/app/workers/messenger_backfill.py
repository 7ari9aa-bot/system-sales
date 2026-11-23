"""``messenger.backfill``: reads a Page's Messenger history from Meta and stores what is missing.

One run handles one page of threads (25) and, while Meta has more and the caps allow, queues the
next run, the way ``import.run`` chains batches. The job runner executes a handler in one
transaction, so a crash loses one page of work and the retry finds those messages already stored
(they are keyed by Meta's message id) instead of writing them twice.

The job table has no payload column and ``correlation_id`` holds 64 characters, while a Meta paging
cursor is a base64 blob well over that. So the job carries only the small options
(``<days>:<since_epoch|->``) and the run's state (cursor, threads done, last result) lives on the
Messenger integration's ``config["_backfill"]``, which is tenant-scoped JSON that needs no
migration. A manual run starts from the top; a chained run continues from the stored cursor.

Messenger only. Instagram history lives behind a different Meta edge and a different permission.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import Integration, Job
from app.workers.job_runner import register_job_handler

logger = logging.getLogger(__name__)

JOB_KIND = "messenger.backfill"
STATE_KEY = "_backfill"
#: Hard ceilings an owner request cannot exceed, whatever it asks for.
MAX_DAYS = 365
MAX_THREADS = 500


def encode_options(*, days: int, since: datetime | None, resume: bool = False) -> str:
    stamp = str(int(since.timestamp())) if since else "-"
    return f"{days}:{stamp}:{'r' if resume else 's'}"


def decode_options(raw: str | None) -> dict:
    """The options a job carries. Anything unreadable falls back to the safe defaults."""
    from app.modules.conversations.gateway.messenger_backfill import DEFAULT_DAYS

    try:
        days_s, stamp, mode = (raw or "").split(":", 2)
        days = max(1, min(int(days_s), MAX_DAYS))
        since = datetime.fromtimestamp(int(stamp), tz=UTC) if stamp != "-" else None
    except (ValueError, OverflowError, OSError):
        return {"days": DEFAULT_DAYS, "since": None, "resume": False}
    return {"days": days, "since": since, "resume": mode == "r"}


async def _integration(session: AsyncSession, tenant_id: uuid.UUID) -> Integration | None:
    return (
        await session.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.provider == "messenger",
                Integration.kind == "channel",
            )
        )
    ).scalar_one_or_none()


def _write_state(integration: Integration, state: dict | None) -> None:
    config = dict(integration.config) if isinstance(integration.config, dict) else {}
    if state is None:
        config.pop(STATE_KEY, None)
    else:
        config[STATE_KEY] = state
    integration.config = config  # a new dict, so the JSONB change is seen


def read_state(integration: Integration | None) -> dict:
    config = integration.config if integration is not None else None
    state = config.get(STATE_KEY) if isinstance(config, dict) else None
    return dict(state) if isinstance(state, dict) else {}


async def enqueue_backfill(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    days: int | None = None,
    since: datetime | None = None,
    resume: bool = False,
) -> Job:
    """Queue a backfill. ``since`` wins over ``days`` (it names the exact outage to recover)."""
    from app.modules.conversations.gateway.messenger_backfill import DEFAULT_DAYS
    from app.modules.platform.services.jobs import JobService

    return await JobService.create(
        session,
        tenant_id,
        kind=JOB_KIND,
        actor_user_id=user_id,
        correlation_id=encode_options(
            days=max(1, min(days or DEFAULT_DAYS, MAX_DAYS)), since=since, resume=resume
        ),
        max_attempts=3,
    )


async def _connection(integration: Integration, session: AsyncSession) -> tuple[str, str]:
    """``(page_id, page token)`` of the connected Messenger channel."""
    from app.modules.platform.services.channel_access import channel_credentials_config

    config = await channel_credentials_config(session, integration.tenant_id, "messenger")
    if not config:
        raise RuntimeError("Messenger is not connected")
    meta = config.get("_meta") if isinstance(config.get("_meta"), dict) else {}
    page_id = str(meta.get("page_id") or config.get("page_id") or config.get("account_id") or "")
    token = str(config.get("api_key") or config.get("page_access_token") or "")
    if not page_id or not token:
        raise RuntimeError("Messenger has no Page id or token on file")
    return page_id, token


@register_job_handler(JOB_KIND)
async def run_backfill(session: AsyncSession, job: Job) -> dict:
    """One page of threads; queues the next page when Meta has more and the caps allow."""
    from app.modules.conversations.gateway import messenger_backfill as mb
    from app.modules.platform.services.jobs import JobService

    integration = await _integration(session, job.tenant_id)
    if integration is None or integration.status not in ("active", "connected"):
        return {"skipped": True, "reason": "messenger is not connected"}
    options = decode_options(job.correlation_id)
    state = read_state(integration) if options["resume"] else {}
    since = options["since"] or (datetime.now(UTC) - timedelta(days=options["days"]))
    page_id, token = await _connection(integration, session)

    done_before = int(state.get("threads_done") or 0)
    result = await mb.run_page(
        session,
        job.tenant_id,
        page_id=page_id,
        token=token,
        since=since,
        cursor=state.get("cursor"),
        max_threads=MAX_THREADS,
        threads_done=done_before,
    )
    summary = result.as_dict()
    done = done_before + result.threads_seen
    summary["threads_total"] = done
    chain = bool(result.next_cursor) and result.stopped_reason is None
    # A throttled run is not queued again here: Meta asked for a pause, and a later run resumes
    # from the stored cursor instead of hammering a limit that was just hit.
    _write_state(
        integration,
        {
            "cursor": result.next_cursor,
            "threads_done": done,
            "finished": not result.next_cursor,
            "stopped_reason": result.stopped_reason,
            "last_run_at": datetime.now(UTC).isoformat(),
            "last_result": {
                k: summary[k]
                for k in (
                    "threads_seen",
                    "messages_written",
                    "messages_known",
                    "messages_unreadable",
                    "customers_created",
                )
            },
        },
    )
    if chain:
        await JobService.create(
            session,
            job.tenant_id,
            kind=JOB_KIND,
            actor_user_id=job.actor_user_id,
            correlation_id=encode_options(
                days=options["days"], since=options["since"], resume=True
            ),
        )
    summary["queued_next"] = chain
    await session.flush()
    if result.stopped_reason and result.stopped_reason.startswith("meta_error"):
        logger.warning("messenger.backfill tenant=%s %s", job.tenant_id, result.stopped_reason)
    return summary
