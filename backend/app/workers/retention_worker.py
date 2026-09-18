"""Retention worker (spec §52): executes RetentionPolicy rows per tenant.

Cross-tenant pattern (§125): enumerate tenants, one transaction per tenant —
never a single global transaction. Runs as part of the maintenance pool.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.db import SessionLocal, bind_tenant
from app.workers.base import StreamWorker

logger = logging.getLogger(__name__)

# Data class → (table, timestamp column) with simple age-based cleanup.
# Tombstoned/audit rows are archived later (§57), never hard-deleted here.
_RETENTABLE = {
    "messages": "created_at",
    "ai_usage": "created_at",
    "webhook_events": "received_at",
}


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
                    deleted = await self._run_tenant(session, tenant_raw)
                    logger.info("retention.run tenant=%s deleted=%s", tenant_raw, deleted)

    async def _run_tenant(self, session, tenant_id) -> dict:
        """Apply each active policy for one tenant, one transaction."""
        from app.modules.privacy.models import RetentionPolicy

        now = datetime.now(UTC)
        deleted: dict[str, int] = {}
        policies = (
            await session.execute(
                select(RetentionPolicy).where(
                    RetentionPolicy.tenant_id == tenant_id,
                    RetentionPolicy.status == "active",
                )
            )
        ).scalars().all()
        for policy in policies:
            table, ts_col = _RETENTABLE.get(policy.data_class, (None, None))
            if table is None:
                continue
            cutoff = now - timedelta(days=policy.retention_days)
            result = await session.execute(
                text(
                    f"DELETE FROM {table} WHERE tenant_id = :t "
                    f"AND {ts_col} < :cutoff"
                ),
                {"t": tenant_id, "cutoff": cutoff.isoformat()},
            )
            deleted[policy.data_class] = deleted.get(policy.data_class, 0) + (
                result.rowcount or 0
            )
            policy.last_run_at = now
        return deleted
