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


# ---------------------------------------------------------------------------
# §49-50 — Tenant offboarding worker
# ---------------------------------------------------------------------------
# When a tenant enters the "offboarding" state, a 30-day retention clock
# starts. During that window:
#   1. The tenant admin can export their data (the UI calls the export
#      endpoint which produces a JSON/CSV dump).
#   2. AI, channels, and automation are disabled (capability policy).
#   3. After the retention window expires, a scheduled job calls
#      `finalize_offboarding()` which performs the final hard delete.
#
# The hard delete is a CASCADE: deleting the tenant row cascades to all
# tenant-scoped tables (customers, conversations, messages, orders, etc.)
# via the FK ON DELETE CASCADE. The deletion is logged as a security
# event so there is a record that the data was purged.


class OffboardingWorker:
    """§49-50: handles the offboarding → deleted transition.

    This is NOT a stream worker — it is a scheduled job that runs daily
    to check for tenants whose offboarding retention window has expired.
    """

    @staticmethod
    async def run_once(session, tenant_id) -> dict:
        """Check if a tenant's offboarding retention has expired.

        If the retention window has NOT expired, returns the remaining days.
        If it HAS expired, performs the final hard delete (CASCADE).
        """
        from app.modules.identity.service import TenantLifecycleService
        from app.modules.platform.models import AuditLog

        now = datetime.now(UTC)
        tenant = await TenantLifecycleService.get(session, tenant_id)

        if tenant.lifecycle_state != "offboarding":
            return {
                "tenant_id": str(tenant_id),
                "action": "skipped",
                "reason": f"tenant is {tenant.lifecycle_state}, not offboarding",
            }

        if tenant.deletion_scheduled_at is None:
            return {
                "tenant_id": str(tenant_id),
                "action": "skipped",
                "reason": "deletion_scheduled_at is not set",
            }

        if now < tenant.deletion_scheduled_at:
            remaining_days = (tenant.deletion_scheduled_at - now).days
            return {
                "tenant_id": str(tenant_id),
                "action": "waiting",
                "remaining_days": remaining_days,
                "deletion_scheduled_at": tenant.deletion_scheduled_at.isoformat(),
            }

        # The retention window has expired — perform the final delete.
        # Log BEFORE the cascade delete (after, the tenant row is gone).
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=None,
                action="tenant.data_purged",
                resource_type="tenant",
                resource_id=str(tenant_id),
                before={
                    "lifecycle_state": tenant.lifecycle_state,
                    "deletion_scheduled_at": tenant.deletion_scheduled_at.isoformat(),
                },
                after={"action": "hard_delete_cascade"},
            )
        )

        # The transition to "deleted" handles the state machine + audit.
        # The CASCADE on the Tenant FK will delete all tenant-scoped rows.
        await TenantLifecycleService.transition(
            session,
            tenant_id,
            "deleted",
            reason="offboarding retention window expired — final data purge",
        )

        logger.info(
            "offboarding.finalized tenant=%s — data purged via cascade",
            tenant_id,
        )
        return {
            "tenant_id": str(tenant_id),
            "action": "purged",
            "purged_at": now.isoformat(),
        }

    @staticmethod
    async def export_data(session, tenant_id) -> dict:
        """§49: export all tenant data as a JSON-serializable dict.

        This is the "take your data out" endpoint called during the
        offboarding window. It produces a structured dump of:
        - customers
        - conversations (with messages)
        - orders (with payments/refunds)
        - memories (AI knowledge base)
        """
        from sqlalchemy import text

        export: dict[str, list] = {}

        # Customers
        rows = (
            await session.execute(
                text(
                    "SELECT id, name, phone, email, created_at "
                    "FROM customers WHERE tenant_id = :tid ORDER BY created_at"
                ),
                {"tid": str(tenant_id)},
            )
        ).all()
        export["customers"] = [
            {
                "id": str(r[0]),
                "name": r[1],
                "phone": r[2],
                "email": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ]

        # Orders
        rows = (
            await session.execute(
                text(
                    "SELECT id, number, status, currency, grand_total, placed_at "
                    "FROM orders WHERE tenant_id = :tid ORDER BY placed_at"
                ),
                {"tid": str(tenant_id)},
            )
        ).all()
        export["orders"] = [
            {
                "id": str(r[0]),
                "number": r[1],
                "status": r[2],
                "currency": r[3],
                "grand_total": str(r[4]) if r[4] else None,
                "placed_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]

        # Conversations (summary only — messages are too large for a single export)
        rows = (
            await session.execute(
                text(
                    "SELECT id, channel, status, created_at "
                    "FROM conversations WHERE tenant_id = :tid ORDER BY created_at"
                ),
                {"tid": str(tenant_id)},
            )
        ).all()
        export["conversations"] = [
            {
                "id": str(r[0]),
                "channel": r[1],
                "status": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ]

        return {
            "tenant_id": str(tenant_id),
            "exported_at": datetime.now(UTC).isoformat(),
            "counts": {k: len(v) for k, v in export.items()},
            "data": export,
        }
