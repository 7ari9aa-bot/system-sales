"""Retention worker (spec §52): executes RetentionPolicy rows per tenant.

Cross-tenant pattern (§125): enumerate tenants, one transaction per tenant —
never a single global transaction. Runs as part of the maintenance pool.

Two entry points:

- ``RetentionWorker.run_once(session, tenant_id) -> dict`` — the agreed entry
  point. The CALLER owns the transaction and has ALREADY bound the tenant GUC
  (``bind_tenant``); this method never opens or commits a transaction itself,
  so the scheduler can run it inline from a ``job_type='retention.run'`` job.
- ``handle(event)`` — the legacy Redis-stream path (payload event_type
  ``retention.run``); kept working, delegates to ``run_once``.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.db import SessionLocal, bind_tenant
from app.workers.base import StreamWorker

logger = logging.getLogger(__name__)

# data_class -> (table, age timestamp column) for age-based cleanup.
#
# GUARD RAIL: a data_class that is NOT a key here is SKIPPED, never guessed at
# — a wrong table name means unrecoverable data loss. Only append a store
# whose PII-map row (docs/PII_DATA_MAP.md, §131) says the retention worker
# deletes it. Stores the map marks "legal retention" / "keep" — orders,
# payments, audit_logs, customers — MUST NOT be added here.
#
# Current entries, with their PII-map justification:
#   messages       — "policy (default 365d) ... retention worker"
#   ai_usage       — "metrics ... 13 months ... retention worker"
#   webhook_events — minimal inbound ingress payload; system table (§130)
#
# Table/column names come from this static allowlist, never from a policy row,
# so the f-string built in _delete_older_than cannot be influenced by data.
_RETENTABLE: dict[str, tuple[str, str]] = {
    "messages": ("messages", "created_at"),
    "ai_usage": ("ai_usage", "created_at"),
    "webhook_events": ("webhook_events", "received_at"),
}

# Rows deleted per statement. A sweep must not lock a hot table for minutes,
# so each DELETE touches at most this many rows and loops until drained.
_DELETE_BATCH_SIZE = 500


class RetentionWorker(StreamWorker):
    """Triggered by scheduled jobs (job_type='retention.run') or a beat."""

    stream = "platform.events"
    group = "retention-workers"
    name = "retention-worker"

    async def handle(self, event) -> None:  # noqa: ANN001
        payload = getattr(event, "payload", {}) or {}
        if payload.get("event_type") != "retention.run":
            return
        tenant_raw = (getattr(event, "meta", {}) or {}).get("tenant_id")
        if tenant_raw:
            async with SessionLocal() as session:
                async with session.begin():
                    await bind_tenant(session, tenant_raw)
                    summary = await RetentionWorker.run_once(session, tenant_raw)
                    logger.info("retention.run tenant=%s summary=%s", tenant_raw, summary)

    @staticmethod
    async def run_once(session, tenant_id) -> dict:
        """Apply every active RetentionPolicy for one tenant.

        Runs INSIDE the caller's already-open transaction, with the tenant GUC
        already bound by the caller. Loads ``status == "active"`` policies and,
        for each, deletes rows older than ``retention_days`` from the mapped
        table in bounded batches, then stamps ``last_run_at``.

        Returns e.g. ``{"policies": 2, "deleted": {"messages": 12, "ai_usage":
        0}, "skipped": [...]}``. ``skipped`` records every policy deliberately
        NOT run, with the reason.
        """
        from app.modules.privacy.models import RetentionPolicy

        now = datetime.now(UTC)
        deleted: dict[str, int] = {}
        skipped: list[dict] = []
        applied = 0

        policies = (
            await session.execute(
                select(RetentionPolicy).where(
                    RetentionPolicy.tenant_id == tenant_id,
                    RetentionPolicy.status == "active",
                )
            )
        ).scalars().all()

        for policy in policies:
            mapping = _RETENTABLE.get(policy.data_class)
            if mapping is None:
                # Unknown data_class: skip and report — never guess a table.
                skipped.append(
                    {"data_class": policy.data_class, "reason": "unknown_data_class"}
                )
                logger.warning(
                    "retention.skipped_unknown_class tenant=%s data_class=%s",
                    tenant_id,
                    policy.data_class,
                )
                continue
            if policy.retention_days is None or policy.retention_days <= 0:
                # 0 or negative would mean "delete everything" — unrecoverable.
                skipped.append(
                    {
                        "data_class": policy.data_class,
                        "reason": "non_positive_retention_days",
                    }
                )
                logger.warning(
                    "retention.skipped_non_positive_days tenant=%s data_class=%s days=%s",
                    tenant_id,
                    policy.data_class,
                    policy.retention_days,
                )
                continue

            table, ts_col = mapping
            cutoff = now - timedelta(days=policy.retention_days)
            total = await RetentionWorker._delete_older_than(
                session, table, ts_col, tenant_id, cutoff
            )
            deleted[policy.data_class] = deleted.get(policy.data_class, 0) + total
            policy.last_run_at = now
            applied += 1

        return {"policies": applied, "deleted": deleted, "skipped": skipped}

    @staticmethod
    async def _delete_older_than(
        session, table: str, ts_col: str, tenant_id, cutoff
    ) -> int:
        """Delete rows older than ``cutoff`` in bounded batches.

        ``table``/``ts_col`` are interpolated from the ``_RETENTABLE`` allowlist
        only — SQL identifiers cannot be bound as parameters, and no policy
        value ever reaches this string. Every retentable table has a UUID
        ``id`` primary key. The explicit ``tenant_id`` predicate is required
        for RLS-exempt tables such as ``webhook_events`` (belt-and-suspenders
        elsewhere). Returns the number of rows removed.
        """
        removed = 0
        while True:
            result = await session.execute(
                text(
                    f"DELETE FROM {table} WHERE id IN ("
                    f"SELECT id FROM {table} "
                    f"WHERE tenant_id = :tenant_id AND {ts_col} < :cutoff "
                    f"LIMIT {_DELETE_BATCH_SIZE})"
                ),
                {"tenant_id": tenant_id, "cutoff": cutoff},
            )
            batch = result.rowcount or 0
            removed += batch
            if batch < _DELETE_BATCH_SIZE:
                return removed
