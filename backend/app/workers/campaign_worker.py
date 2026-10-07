"""§175/§144 — campaign worker: the batch pump that fairness throttles.

Campaign execution was half-wired: ``start_campaign`` staged a
``campaign.run.started`` envelope and NOTHING consumed it — the run sat
RUNNING forever with its first batch unsent. This worker is the other half,
and it is where §144's promise is kept: "Campaign كبيرة من Tenant A لا يجوز
أن تجوع Tenant B".

The mechanics:

- ONE event = ONE batch. The handler never loops over recipients on the
  stream; it processes at most ``batch`` messages and returns, so a 100k
  campaign cannot monopolize a worker slot.
- The batch is capped at the tenant's remaining MESSAGES_OUTBOUND budget
  (checked at the point of consumption, not at the API edge), and the
  messages actually SENT are charged back to the budget.
- When the budget is exhausted the event is DEFERRED (``DeferredError`` →
  base worker re-stages it through the outbox without burning an attempt) —
  the run resumes on its own once the window frees units.
- Continuation is a paced ``campaign.run.batch`` outbox event
  (``not_before``), never an in-worker loop: the pacing survives a crash,
  and the campaign stream shares its pool with nothing interactive.

Priority (§144): campaign work is the BULK tier — MessageWorker never
paces, this worker always does.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.core.errors import ValidationError
from app.core.events.bus import Event
from app.core.events.schemas import deserialize_event
from app.core.events.writer import add_outbox_event
from app.core.fairness import ResourceType, check_budget, consume
from app.workers.base import DeferredError, StreamWorker, defer_unless_tenant_allows

logger = logging.getLogger(__name__)

# Minimum spacing between two batches of one run. The budget check caps HOW
# MUCH may go out; this caps HOW OFTEN, so one tenant's queue depth cannot
# crowd the campaign stream for everyone else.
CAMPAIGN_BATCH_PACING_SECONDS = 10.0

# How long to sit out when the outbound budget reads exhausted. The budget
# is a 24h sliding window, so exhaustion is rare and transient; re-checking
# in 15 minutes is plenty and avoids a defer hot-loop.
_BUDGET_RETRY_DELAY_SECONDS = 900.0

_BATCHED = "batched"
_COMPLETED = "completed"
_NOT_RUNNING = "not_running"


async def process_campaign_run_event(
    session,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    pacing_seconds: float = CAMPAIGN_BATCH_PACING_SECONDS,
) -> str:
    """Pump ONE batch of a campaign run, budget-capped. Returns a word:

    ``not_running``  — run gone / paused / finished (no-op, event is ACKed);
    ``batched``      — a batch went out and a paced continuation was staged;
    ``completed``    — the audience is exhausted and the run completed
                       (``process_batch`` staged the completion event).

    Raises ``DeferredError`` when the tenant's MESSAGES_OUTBOUND or
    WORKER_SECONDS budget is exhausted — the base worker re-stages the
    event without burning an attempt, so the run resumes when units free
    up. Runs in the CALLER's transaction (services never commit).
    """
    from app.modules.marketing.campaign import (
        CampaignExecutionService,
        CampaignRun,
        CampaignRunStatus,
    )

    run = (
        await session.execute(
            select(CampaignRun).where(CampaignRun.tenant_id == tenant_id, CampaignRun.id == run_id)
        )
    ).scalar_one_or_none()
    if run is None or run.status != CampaignRunStatus.RUNNING.value:
        return _NOT_RUNNING

    budget = await check_budget(tenant_id, ResourceType.MESSAGES_OUTBOUND)
    if not budget.allowed:
        raise DeferredError(
            "outbound message budget exhausted",
            delay_seconds=_BUDGET_RETRY_DELAY_SECONDS,
        )
    # §144 tiering: the BULK tier is the one that may be throttled by the
    # worker-time meter (every StreamWorker handler charges WORKER_SECONDS to
    # its tenant); interactive tiers are never gated here.
    worker_time = await check_budget(tenant_id, ResourceType.WORKER_SECONDS)
    if not worker_time.allowed:
        raise DeferredError(
            "tenant worker-time budget exhausted",
            delay_seconds=_BUDGET_RETRY_DELAY_SECONDS,
        )
    batch_size = min(CampaignExecutionService.DEFAULT_BATCH_SIZE, int(budget.remaining))

    previous_sent = run.sent_count
    run = await CampaignExecutionService.process_batch(
        session, tenant_id, run_id, batch_size=batch_size
    )
    sent = run.sent_count - previous_sent
    if sent > 0:
        # Charge ACTUAL consumption, not intent: refused recipients
        # (consent / channel policy) never spent the tenant's queue budget.
        await consume(tenant_id, ResourceType.MESSAGES_OUTBOUND, units=sent)

    if run.status == CampaignRunStatus.RUNNING.value:
        staged = await add_outbox_event(
            session,
            aggregate_type="campaign_run",
            aggregate_id=run.id,
            event_type="campaign.run.batch",
            tenant_id=tenant_id,
            payload={"campaign_id": str(run.campaign_id)},
        )
        staged.not_before = datetime.now(UTC) + timedelta(seconds=pacing_seconds)
        return _BATCHED
    return _COMPLETED


class CampaignWorker(StreamWorker):
    stream = "campaign_run.events"
    group = "campaign-workers"
    name = "campaign-worker"

    async def handle(self, event: Event) -> None:
        # Fail CLOSED on a non-envelope entry: no tenant, no business run.
        try:
            envelope = deserialize_event(event)
        except (ValidationError, KeyError, TypeError, ValueError):
            logger.warning("campaign.event_without_envelope id=%s", event.id)
            return
        if envelope.type not in ("campaign.run.started", "campaign.run.batch"):
            return
        tenant_id = envelope.tenant_id
        async with SessionLocal() as session:
            async with session.begin():
                await bind_tenant(session, tenant_id)
                # §48: a non-operational tenant's campaign work defers — the
                # run row and its paced events resume on reactivation. A
                # DeferredError raised inside (budget or lifecycle) reaches
                # the base worker's defer path with the transaction rolled
                # back and nothing consumed.
                await defer_unless_tenant_allows(session, tenant_id, "allows_automation")
                outcome = await process_campaign_run_event(
                    session, tenant_id, envelope.aggregate_id
                )
                logger.info(
                    "campaign.pumped run=%s tenant=%s outcome=%s",
                    envelope.aggregate_id,
                    tenant_id,
                    outcome,
                )
