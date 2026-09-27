"""Outbox relay: publishes events committed in Postgres to the event bus.

Flow (the core of "order created / event never lost"):

    BEGIN;
      ...business writes...
      INSERT INTO outbox_events (...);
    COMMIT;
      --> this relay picks the row up and publishes it.

The outbox_events table is created by the Stage-1 migrations; this module is
the runtime that drains it.

CLAIM SEMANTICS (G-08). One row is claimed, published and marked in a SINGLE
transaction, so the row's Postgres lock IS the lease: while a relay works a row
no other relay can even see it as claimable, and a relay that dies mid-publish
rolls its claim back — the row goes straight back to 'pending' and another
relay takes it at once. That ordering is what makes the failure mode safe:
the publish to the stream and the 'published' mark commit together or not at
all, so a crash can only ever mean "re-publish", never "lost" and never
"two relays publishing the same row at the same time".

Because 'published' is committed with the publish itself, delivery is still
at-least-once (the XADD can reach Redis and the process die before the commit
lands), and the consumer's dedupe key — the stable outbox row id in
``meta["outbox_id"]`` — makes a *sequential* redelivery harmless. A concurrent
redelivery is not (the consumer's dedupe is a read-then-act), which is
precisely the hole the single-transaction claim closes.

Rows stranded in 'publishing' by something other than a live relay (an older
deployment mid-roll, ops SQL) are re-queued after ``settings.outbox_lease_seconds``
(§128); that scan runs FOR UPDATE SKIP LOCKED, so it can never steal from a
live relay. Re-queueing resets ``attempts`` (P-01): the claim only takes
``attempts < worker_max_attempts``, so a reclaim that reset the status and kept
the burnt counter would hand a row back to 'pending' where nothing can ever see
it again — five relay deaths would read as a lost event, silently, which the
"never lost" promise above forbids. A lease expiry is environmental, so it costs
the event nothing; the row is logged at WARNING instead. Every successfully
published event is also appended to event_log (§152), the durable replay
history: the outbox is only a publication buffer.

The cool-down that keeps a failed row from hammering an unreachable bus is
carried by ``not_before`` (P-02), not by the attempt budget. ``_MARK_FAILED_SQL``
stamps a future ``not_before`` off the row's own attempt count, bounded by a
ceiling; ``_RECLAIM_FAILED_SQL`` then wakes the row on that durable schedule
(rather than the immutable staging clock, whose cool-down evaporated after the
first re-queue and left a poisoned row retried once per drain). The two intents
are deliberately separate: ``attempts`` is a per-processing-failure budget that
every re-queue resets (P-01), while ``not_before`` is the retry pace the row
earns and keeps — a Redis outage must not burn the former, and a down bus must
still be backed off.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal, bind_tenant
from app.core.errors import ValidationError
from app.core.events.bus import EventBus
from app.core.events.schemas import EventEnvelope, deserialize

logger = logging.getLogger(__name__)

# P-02: the failed-row cool-down is a bounded exponential in ``attempts``,
# stamped into ``not_before`` when a row fails and read back by the claim. The
# base is the operator-configurable re-queue interval
# (``settings.outbox_failed_requeue_seconds``, threaded per-drain so an operator
# owns the pace); the ceiling below is the hard bound that keeps the ladder from
# parking a row for unbounded time across a long outage no matter how the base is
# set. Expressing the schedule in SQL (see ``_MARK_FAILED_SQL``) off the
# transaction's ``now()`` is what makes it durable across a relay death and
# readable under the connection pooler — a Python-side timestamp would not be,
# and the claim's ``not_before <= now()`` reads the SAME DB clock, so the two
# must agree.
OUTBOX_BACKOFF_CEILING_SECONDS = 3600.0  # one hour: a row never waits past this

# §128 backstop: a committed row no live relay can be working on, in either of
# the two shapes that strand it —
#   * 'publishing' past its lease: the relay that claimed it died before its
#     claim transaction could commit (pod restart mid-deploy, OOM, the process
#     recycled while a publish blocked), or an older deployment / ops SQL
#     committed the claim outright;
#   * 'pending' with its attempt budget already spent. `_CLAIM_ONE_SQL` below
#     refuses those (attempts < :max_attempts) and `_RECLAIM_FAILED_SQL` refuses
#     them (wrong status), so without this arm the row sits there forever:
#     never published, never 'failed', never logged. That is precisely what the
#     pre-fix reclaim did — it reset the STATUS but not the counter, so each
#     lease expiry cost a live event one attempt and five relay deaths silently
#     destroyed it. A mixed-version deploy still produces the state while an old
#     relay is draining, and rows stranded before this shipped stay stranded,
#     so the reclaim revives them too.
# Both arms reset attempts to 0 for the reason `_RECLAIM_FAILED_SQL` documents:
# the retry budget applies to PROCESSING, not to the relay being restarted out
# from under the row — a lease expiry is environmental, and the module's
# contract is that a crash can only ever mean "re-publish", never "lost".
# Resetting the budget means a payload that kills the relay on every try loops
# instead of dying quietly — that is the deliberate trade, and it is why every
# row freed here is logged at WARNING with its id (see `_reclaim_stranded`): the
# loop stays loud and countable rather than silent either way.
# P-02: both arms ALSO clear `not_before`. A row stranded in 'publishing' was
# never marked failed, so it earned no cool-down and a stale schedule must not
# block its prompt fresh-budget retry; a row stranded 'pending' at the cap is
# revived for the same reason. The cool-down a row DOES earn is stamped by
# `_MARK_FAILED_SQL` and preserved by `_RECLAIM_FAILED_SQL` — the two intents
# stay separate.
# The created_at bound is shared by both arms and keeps the scan on
# ix_outbox_status_created and off the hot path.
# FOR UPDATE SKIP LOCKED is the part that makes the reclaim safe: a LIVE relay
# holds its claimed row locked for the whole publish (see the module docstring),
# so this scan walks past it at any age instead of re-queueing work that is
# already being done — which is what used to double-publish a backlog.
_RECLAIM_STRANDED_SQL = sa.text(
    """
    UPDATE outbox_events
       SET status = 'pending', attempts = 0, not_before = NULL
     WHERE id IN (
        SELECT id FROM outbox_events
         WHERE created_at < now() - make_interval(secs => :lease_seconds)
           AND (
                 status = 'publishing'
              OR (status = 'pending' AND attempts >= :max_attempts)
               )
         FOR UPDATE SKIP LOCKED
     )
    RETURNING id
    """
)

# A `failed` row means the BUS was unreachable at publish time (an
# environmental failure — poison events dead-letter at the worker, not here).
# P-02: the cool-down is a DURABLE schedule now. `_MARK_FAILED_SQL` stamps a
# future `not_before` on every failure, and this reclaim WAKES on it
# (`not_before <= now()`), so a not-yet-due failed row is left alone — no retry
# storm, and no `ORDER BY created_at` starvation of the rows behind it. The
# `not_before` the row just earned is PRESERVED by the re-queue below (only
# status + attempts reset), so the next claim honours it and the retry stays
# paced; `_MARK_FAILED_SQL` re-stamps the schedule on the next failure.
# The `not_before IS NULL` arm is the STAGING-time floor for rows this shipped
# on top of — `failed` rows written by the pre-P-02 code (and rows a P-01 test
# stages) carry no schedule, so they wake on `created_at`. A legacy row self-
# heals after one retry: the mark gives it a real `not_before`, so it can never
# be hammered once per drain the way the pure-staging-clock reclaim was.
# Resetting attempts here is load-bearing, not tidiness (P-01): any statement
# that writes 'pending' WITHOUT zeroing attempts strands the row for good,
# because the claim refuses attempts >= :max_attempts and nothing else — and no
# alert — ever looks at it again. `tests/test_outbox_claim.py` and
# `tests/test_outbox_backoff.py` pin that for both reclaim statements.
# NOTE (P-02, resolved here): the cool-down and the attempt budget are separate
# intents and this statement honours both without conflating them — attempts is
# reset (897fb6f: a Redis outage must not burn the PROCESSING budget) while
# `not_before` is PRESERVED (the row keeps the pace it just earned).
_RECLAIM_FAILED_SQL = sa.text(
    """
    UPDATE outbox_events
       SET status = 'pending', attempts = 0
     WHERE id IN (
        SELECT id FROM outbox_events
         WHERE status = 'failed'
           AND (
                 not_before <= now()
              OR (not_before IS NULL
                  AND COALESCE(published_at, created_at)
                      < now() - make_interval(secs => :failed_requeue_seconds))
               )
         FOR UPDATE SKIP LOCKED
     )
    """
)

# ONE row per statement, and the claim runs in the same transaction as the
# publish and the mark — so the row lock is the lease and no claim can outlive
# the relay that took it. `LIMIT 1` is deliberate: a multi-row claim would hold
# locks across every other row's publish, and if it committed early (as the old
# batch claim did at its first per-row commit) the remaining rows became
# durably 'publishing' yet UNLOCKED, i.e. stealable by a second relay.
# The `attempts < :max_attempts` guard is only safe because the counter is a
# per-processing-failure budget: this statement increments it inside a
# transaction that normally commits as 'published' or 'failed', and both
# reclaims zero it when they re-queue a row (P-01). A row left 'pending' at
# this cap is invisible to this statement, to the failed reclaim and to every
# alert — no path may strand one there, which is what the pre-fix publishing
# reclaim did to a committed claim whose relay then died.
_CLAIM_ONE_SQL = sa.text(
    """
    UPDATE outbox_events
       SET status = 'publishing', attempts = attempts + 1
     WHERE id IN (
        SELECT id FROM outbox_events
         WHERE status = 'pending'
           AND attempts < :max_attempts
           AND (not_before IS NULL OR not_before <= now())
         ORDER BY created_at
         FOR UPDATE SKIP LOCKED
         LIMIT 1
     )
    RETURNING id, stream, payload, meta, aggregate_type, aggregate_id, created_at
    """
)

# The claim and this mark share one transaction, which is why 'publishing' is
# never observable to another relay and why no lock_owner column is needed:
# the transaction is the owner.
_MARK_PUBLISHED_SQL = sa.text(
    "UPDATE outbox_events SET status = 'published', published_at = now() WHERE id = :id"
)

# P-02: marking a row failed must SCHEDULE its next try, not merely flag it, or
# the claim (which honours `not_before`) will re-take the row on the very next
# drain — a hot loop against a down bus that also starves the `ORDER BY
# created_at` queue behind it. The cool-down is computed entirely in SQL off the
# transaction's `now()` — durable across a relay death and readable under the
# connection pooler, never a client-side timestamp — from the row's own
# `attempts` (already incremented by the claim in this transaction) as a base
# doubled per prior attempt, clamped by `LEAST(..., :backoff_max_seconds)`.
# The two intents stay distinct (P-01 vs P-02): because every re-queue resets
# `attempts` (897fb6f), a clean row re-marks at attempts = 1 and settles to the
# bounded base every cycle — which is exactly the durable cool-down that stops
# the once-per-drain hammering. The exponential term bites for a row that
# arrives with attempts already spent (a pre-P-01 / mixed-version stranded row
# the claim lifts above 0), so a row that HAS burned budget backs off further,
# and the ceiling bounds it however the count arrived. GREATEST(attempts - 1, 0)
# keeps the exponent non-negative for the (theoretical) attempts = 0 mark.
# Both durations are CAST to double precision on purpose: `GREATEST(:base, 0)`
# lets Postgres infer int4 from the integer sibling, and the driver then refuses
# the float the settings field holds — inside the relay's own failure handler.
# `:base::double precision` is not an alternative spelling: SQLAlchemy's text()
# reads that parameter as `bas` and leaves the rest as SQL.
_MARK_FAILED_SQL = sa.text(
    """
    UPDATE outbox_events
       SET status = 'failed',
           last_error = :err,
           not_before = now() + make_interval(
               secs => LEAST(
                   GREATEST(CAST(:backoff_base_seconds AS double precision), 0)
                       * power(2, GREATEST(attempts - 1, 0)),
                   CAST(:backoff_max_seconds AS double precision)))
     WHERE id = :id
    """
)

# §152: durable replay history — written in the same transaction that marks
# the outbox row published. ON CONFLICT keeps a reclaimed-and-republished row
# from double-landing in the history.
_EVENT_LOG_SQL = sa.text(
    """
    INSERT INTO event_log (
        id, event_id, event_type, aggregate_type, aggregate_id,
        aggregate_version, schema_version, occurred_at, producer,
        correlation_id, causation_id, payload, tenant_id,
        workspace_id, location_id, decision_id, effect_id
    ) VALUES (
        :id, :event_id, :event_type, :aggregate_type, :aggregate_id,
        :aggregate_version, :schema_version, :occurred_at, :producer,
        :correlation_id, :causation_id, CAST(:payload AS jsonb), :tenant_id,
        :workspace_id, :location_id, :decision_id, :effect_id
    )
    ON CONFLICT (event_id) DO NOTHING
    """
)

# §153 ordering probe: the durable log must reveal a same-aggregate event that
# lands BELOW the highest version already recorded (multi-relay publishes, or a
# replay out of order). Detection is loud but never blocks — event_log stays
# append-only.
_AGGREGATE_MAX_VERSION_SQL = sa.text(
    """
    SELECT max(aggregate_version)
      FROM event_log
     WHERE tenant_id = :tenant_id
       AND aggregate_type = :aggregate_type
       AND aggregate_id = :aggregate_id
       AND aggregate_version IS NOT NULL
    """
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

    async def _reclaim_stranded(self, session: AsyncSession, max_attempts: int) -> None:
        """Re-queue rows no live relay can be working on (§128, P-01).

        Every duration carries in from settings, and the attempt cap is the
        SAME value the caller hands `_claim_one` — never a re-read of settings,
        because two sources that disagree reopen the stranding: a row at the
        claim's cap but under the reclaim's is 'pending' and invisible. Both
        scans run FOR UPDATE SKIP LOCKED, so a row another relay holds locked
        for its in-flight publish is walked past rather than re-queued out from
        under it.

        Re-queueing RESETS the attempt budget (see `_RECLAIM_STRANDED_SQL`),
        which is why this logs: a row freed here was not refused by the bus, it
        lost the relay that was publishing it, and a payload that kills every
        relay it touches would otherwise retry forever in total silence. One
        warning line per row id is what makes that loop countable.
        """
        settings = get_settings()
        reclaimed = (
            (
                await session.execute(
                    _RECLAIM_STRANDED_SQL,
                    {
                        "lease_seconds": settings.outbox_lease_seconds,
                        "max_attempts": max_attempts,
                    },
                )
            )
            .scalars()
            .all()
        )
        for row_id in reclaimed:
            logger.warning(
                "outbox.relay.stranded_row_requeued id=%s lease_expired_or_"
                "attempt_budget_spent attempts_reset=0",
                row_id,
            )
        await session.execute(
            _RECLAIM_FAILED_SQL,
            {"failed_requeue_seconds": settings.outbox_failed_requeue_seconds},
        )

    async def _claim_one(self, session: AsyncSession, max_attempts: int) -> Any | None:
        """Take the next publishable row, or None when there is none.

        The claim locks exactly one row and the caller's transaction stays open
        across the publish, so the lock is held for precisely the work it
        protects and released — with the 'published' mark — in one commit.
        """
        return (
            (await session.execute(_CLAIM_ONE_SQL, {"max_attempts": max_attempts}))
            .mappings()
            .first()
        )

    async def _drain_once(self, batch: int, max_attempts: int) -> int:
        published = 0
        settings = get_settings()
        # A failed row's cool-down is a bounded exponential: the base is the
        # operator-configurable re-queue interval, the ceiling keeps the ladder
        # from parking a row for unbounded time across a long outage.
        backoff_base = settings.outbox_failed_requeue_seconds
        backoff_max = OUTBOX_BACKOFF_CEILING_SECONDS
        async with SessionLocal() as session:
            # The reclaim commits before any claim runs: locks it took to free
            # stranded rows must not be held across the publishes that follow,
            # and every claim below opens its OWN transaction (committed at the
            # bottom of the loop), so a single connection is enough.
            await self._reclaim_stranded(session, max_attempts)
            await session.commit()
            # One row per claim, at most `batch` rows per drain so a sustained
            # backlog cannot starve the poll loop of its sleep.
            for _ in range(batch):
                row = await self._claim_one(session, max_attempts)
                if row is None:
                    await session.rollback()
                    break
                payload = _loads(row["payload"])
                meta = _loads(row["meta"])
                try:
                    await self._bus.publish(row["stream"], payload, meta)
                except Exception as exc:  # noqa: BLE001 — one bad event must not stop the relay
                    logger.exception("outbox.relay.publish_failed id=%s", row["id"])
                    await session.execute(
                        _MARK_FAILED_SQL,
                        {
                            "id": row["id"],
                            "err": str(exc)[:500],
                            "backoff_base_seconds": backoff_base,
                            "backoff_max_seconds": backoff_max,
                        },
                    )
                    await session.commit()
                    continue
                await session.execute(_MARK_PUBLISHED_SQL, {"id": row["id"]})
                # §152 history is written with the publish mark; a history
                # failure must not flip a published row back to pending.
                try:
                    await self._write_event_log(session, row, payload, meta)
                except Exception:  # noqa: BLE001 — relay survives, ops replays
                    logger.exception(
                        "outbox.relay.event_log_failed id=%s", row["id"]
                    )
                # Claim + publish + mark commit together, per row: this single
                # commit is why no relay can see this row as anything but
                # 'pending' (locked) while it is being published, and why a
                # crash anywhere above rolls the claim back with the publish
                # instead of stranding the row in 'publishing'.
                await session.commit()
                published += 1
        return published

    def _envelope_for_log(
        self, row: Any, payload: dict, meta: dict
    ) -> EventEnvelope | None:
        """Rebuild the row's §19 envelope, completing a legacy row from columns.

        The writer stamps every routing key, so a normal row deserializes
        directly. A legacy / hand-injected row (which the writer cannot produce)
        is completed from the outbox row's own columns and re-read through the
        SAME mapping, so there is exactly one field mapping and a malformed row
        never silently loses its replay history. A tenant is still REQUIRED —
        event_log is RLS-guarded.
        """
        try:
            return deserialize({"payload": payload, "meta": meta})
        except (ValidationError, KeyError, TypeError, ValueError):
            pass
        if not meta.get("tenant_id"):
            return None
        created_at = row.get("created_at")
        completed = {
            **meta,
            "type": meta.get("type")
            or payload.get("event_type")
            or f"{row['aggregate_type']}.changed",
            "aggregate_type": meta.get("aggregate_type") or row["aggregate_type"],
            "aggregate_id": meta.get("aggregate_id") or str(row["aggregate_id"]),
            "occurred_at": meta.get("occurred_at")
            or (created_at.isoformat() if created_at else None),
        }
        try:
            return deserialize({"payload": payload, "meta": completed})
        except (ValidationError, KeyError, TypeError, ValueError):
            return None

    async def _write_event_log(
        self, session: AsyncSession, row: Any, payload: dict, meta: dict
    ) -> None:
        """§152: append the published event to event_log (durable replay).

        The outbox row's payload/meta ARE the §19 envelope, so the read half
        rebuilds them through ``deserialize()`` instead of re-deriving the field
        names by hand: the contract is exercised here, and ``occurred_at`` is the
        event's OWN instant (``meta["occurred_at"]``) rather than the outbox
        row's DB ``created_at``. event_log is RLS-guarded, so the tenant GUC is
        bound from the envelope's tenant before the insert.
        """
        envelope = self._envelope_for_log(row, payload, meta)
        if envelope is None:
            logger.warning(
                "outbox.relay.event_log_skipped_invalid_envelope id=%s", row["id"]
            )
            return

        await bind_tenant(session, str(envelope.tenant_id))
        # §153: same aggregate → ordered. A version landing below the max
        # already in the durable log means the stream was consumed out of
        # order — surface it for ops; never drop or reorder history here.
        if envelope.aggregate_version is not None:
            current_max = (
                await session.execute(
                    _AGGREGATE_MAX_VERSION_SQL,
                    {
                        "tenant_id": str(envelope.tenant_id),
                        "aggregate_type": envelope.aggregate_type,
                        "aggregate_id": str(envelope.aggregate_id),
                    },
                )
            ).scalar()
            if current_max is not None and envelope.aggregate_version < current_max:
                logger.error(
                    "event_log.aggregate_version_regression tenant=%s aggregate=%s/%s "
                    "incoming_version=%s already_logged_max=%s event_id=%s",
                    envelope.tenant_id,
                    envelope.aggregate_type,
                    envelope.aggregate_id,
                    envelope.aggregate_version,
                    current_max,
                    row["id"],
                )
        await session.execute(
            _EVENT_LOG_SQL,
            {
                "id": uuid.uuid4(),
                "event_id": row["id"],
                "event_type": envelope.type,
                "aggregate_type": envelope.aggregate_type,
                "aggregate_id": envelope.aggregate_id,
                "aggregate_version": envelope.aggregate_version,
                "schema_version": envelope.schema_version,
                "occurred_at": envelope.occurred_at,
                "producer": envelope.producer,
                "correlation_id": envelope.correlation_id,
                "causation_id": envelope.causation_id,
                "payload": json.dumps(payload, default=str),
                "tenant_id": str(envelope.tenant_id),
                "workspace_id": str(envelope.workspace_id) if envelope.workspace_id else None,
                "decision_id": (
                    str(envelope.decision_id)
                    if getattr(envelope, "decision_id", None)
                    else (str(meta["decision_id"]) if meta.get("decision_id") else None)
                ),
                "effect_id": (
                    str(envelope.effect_id)
                    if getattr(envelope, "effect_id", None)
                    else (str(meta["effect_id"]) if meta.get("effect_id") else None)
                ),
            },
        )


def _loads(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)
