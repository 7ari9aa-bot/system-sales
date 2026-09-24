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

Because 'published' is committed with the publish itself, at-least-once
delivery still exists (the bus may ack and then the process die before the
commit), and the consumer's dedupe key — the stable outbox row id in
``meta["outbox_id"]`` — makes a *sequential* redelivery harmless. A concurrent
redelivery would not (the consumer's dedupe is a read-then-act), which is
precisely the hole the single-transaction claim closes.

Rows stranded in 'publishing' by something other than a live relay (an older
deployment mid-roll, ops SQL) are re-queued after ``settings.outbox_lease_seconds``
(§128); that scan runs FOR UPDATE SKIP LOCKED, so it can never steal from a
live relay. Every successfully published event is also appended to event_log
(§152), the durable replay history: the outbox is only a publication buffer.
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

# §128 backstop: a row durably committed in 'publishing' whose lease expired.
# FOR UPDATE SKIP LOCKED is the part that makes the reclaim safe: a LIVE relay
# holds its claimed row locked for the whole publish (see the module docstring),
# so this scan walks past it at any age instead of re-queueing work that is
# already being done — which is what used to double-publish a backlog.
_RECLAIM_PUBLISHING_SQL = sa.text(
    """
    UPDATE outbox_events
       SET status = 'pending'
     WHERE id IN (
        SELECT id FROM outbox_events
         WHERE status = 'publishing'
           AND created_at < now() - make_interval(secs => :lease_seconds)
         FOR UPDATE SKIP LOCKED
     )
    """
)

# A `failed` row means the BUS was unreachable at publish time (an
# environmental failure — poison events dead-letter at the worker, not here).
# Re-queue them after a cool-down instead of stranding them forever, and
# reset attempts: the retry budget applies to processing, not to Redis outages.
_RECLAIM_FAILED_SQL = sa.text(
    """
    UPDATE outbox_events
       SET status = 'pending', attempts = 0
     WHERE id IN (
        SELECT id FROM outbox_events
         WHERE status = 'failed'
           AND COALESCE(published_at, created_at)
               < now() - make_interval(secs => :failed_requeue_seconds)
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

_MARK_FAILED_SQL = sa.text(
    "UPDATE outbox_events SET status = 'failed', last_error = :err WHERE id = :id"
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
        workspace_id, location_id
    ) VALUES (
        :id, :event_id, :event_type, :aggregate_type, :aggregate_id,
        :aggregate_version, :schema_version, :occurred_at, :producer,
        :correlation_id, :causation_id, CAST(:payload AS jsonb), :tenant_id,
        :workspace_id, :location_id
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

    async def _reclaim_stranded(self, session: AsyncSession) -> None:
        """Re-queue rows no live relay can be working on (§128).

        Both scans carry their duration from settings — never a literal baked
        into the SQL — and both run FOR UPDATE SKIP LOCKED, so a row another
        relay holds locked for its in-flight publish is walked past rather than
        re-queued out from under it.
        """
        settings = get_settings()
        await session.execute(
            _RECLAIM_PUBLISHING_SQL, {"lease_seconds": settings.outbox_lease_seconds}
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
        # The reclaims get their own short transaction: a reclaim lock held
        # across the publish of the rows it just freed would be exactly the
        # contention this function exists to remove.
        async with SessionLocal() as session:
            await self._reclaim_stranded(session)
            await session.commit()
        # At most `batch` rows per drain, so a sustained backlog cannot starve
        # the poll loop of its sleep.
        for _ in range(batch):
            async with SessionLocal() as session:
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
                        _MARK_FAILED_SQL, {"id": row["id"], "err": str(exc)[:500]}
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
                # Claim + publish + mark commit together: a crash before here
                # rolls the claim back, so the row is re-published rather than
                # stranded. A crash after here has published it for good.
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
                "location_id": str(envelope.location_id) if envelope.location_id else None,
            },
        )


def _loads(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)
