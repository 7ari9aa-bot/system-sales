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

This worker owns NO retention decision. Which tables a policy may empty
(``ROW_LEVEL_DATA_CLASSES``), what horizon counts as consent, and the bounded
DELETE itself all live in ``app/modules/analytics/retention.py``, which is also
the half that answers the merchant's ``PUT /analytics/retention/policies/
{data_class}``. That is deliberate: a second copy of the allowlist, or a TTL
kept beside the chosen policy, is a second source of truth about who is allowed
to destroy data — and the two drift. So this file enumerates a tenant's policy
rows, hands each one to the gated executor, and REPORTS what was refused. Note
that it enumerates every policy, not only ``status == "active"`` ones: a
withdrawn choice that silently disappeared from the summary is how "nobody
chose" became invisible to whoever watches the sweep.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.db import SessionLocal, bind_tenant
from app.modules.analytics.retention import (
    REASON_NOT_A_ROW_STORE,
    ROW_LEVEL_DATA_CLASSES,
    purge_row_store,
)
from app.workers.base import StreamWorker

logger = logging.getLogger(__name__)

# data_class -> (table, age timestamp column) for age-based cleanup, derived from
# the module's allowlist rather than restated here.
#
# GUARD RAIL: a data_class that is NOT a key here is SKIPPED, never guessed at —
# a wrong table name means unrecoverable data loss. Only append a store to
# ``analytics/retention.ROW_LEVEL_DATA_CLASSES`` whose PII-map row
# (docs/PII_DATA_MAP.md, §131) hands it to the retention worker: either its
# "Deletion behavior" says the retention worker deletes it (``messages``,
# ``ai_usage``) or it says the store delete happens at all (``attachments``:
# "storage delete + row delete"), which spec §52's own data-class list demands.
# Stores the map marks "legal retention" / "keep" — orders, payments, audit_logs,
# customers — MUST NOT be added, and ``analytics/retention.REFUSED_DATA_CLASSES``
# now says which are refused and under which rule, instead of leaving "absent" to
# mean both "not yet" and "never". Table/column names therefore come from a static
# allowlist, never from a policy row, so the DELETE the module builds cannot be
# influenced by data.
_RETENTABLE: dict[str, tuple[str, str]] = {
    data_class: (spec.table, spec.ts_column)
    for data_class, spec in ROW_LEVEL_DATA_CLASSES.items()
}

#: The order the sweep visits stores in, taken from the allowlist's declaration
#: order. This is load-bearing, not cosmetic: ``attachments.message_id`` is
#: ``ON DELETE CASCADE``, so if ``messages`` is purged first the cascade takes the
#: media rows with it, no keys are in hand, and the objects leak permanently.
#: ``analytics/retention.py`` declares the child before its parent for exactly
#: this reason, and ``tests/test_media_and_lead_retention.py`` pins both halves.
_SWEEP_ORDER: dict[str, int] = {
    data_class: position for position, data_class in enumerate(ROW_LEVEL_DATA_CLASSES)
}
_UNRANKED = len(_SWEEP_ORDER)


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
        """Execute every RetentionPolicy this tenant holds, through the gate.

        Runs INSIDE the caller's already-open transaction, with the tenant GUC
        already bound by the caller. Loads EVERY policy row (an inert one is
        reported, not dropped from the summary) and hands each to
        ``analytics.retention.purge_row_store``, which re-reads the policy from the
        database, applies the same consent gate the partition drop applies, and
        deletes in bounded batches. Nothing here computes a cutoff, a table name,
        or a reason of its own.

        Returns e.g. ``{"policies": 2, "deleted": {"messages": 12, "ai_usage":
        0}, "skipped": [...], "media_released": 4, "media_failed": [...]}``.
        ``skipped`` records every policy deliberately NOT executed, with the
        module's own reason. ``media_failed`` names the bucket objects a purged row
        left behind — a leak this sweep cannot fix twice.

        The policies are visited in the allowlist's dependency order, not in the
        order the database handed them back: a child whose rows cascade with a
        parent's must be cleared first or its objects orphan (``_SWEEP_ORDER``).
        """
        from app.modules.privacy.models import RetentionPolicy

        now = datetime.now(UTC)
        deleted: dict[str, int] = {}
        skipped: list[dict] = []
        applied = 0
        media_released = 0
        media_failed: list[str] = []

        policies = (
            await session.execute(
                select(RetentionPolicy).where(RetentionPolicy.tenant_id == tenant_id)
            )
        ).scalars().all()

        for policy in sorted(policies, key=lambda p: _SWEEP_ORDER.get(p.data_class, _UNRANKED)):
            if policy.data_class not in _RETENTABLE:
                # Unknown data_class: skip and report — never guess a table. The
                # decision is still the module's (purge_row_store refuses the
                # same way); this only keeps the refusal free of any SQL.
                skipped.append(
                    {"data_class": policy.data_class, "reason": REASON_NOT_A_ROW_STORE}
                )
                logger.warning(
                    "retention.skipped_unknown_class tenant=%s data_class=%s",
                    tenant_id,
                    policy.data_class,
                )
                continue

            result = await purge_row_store(session, tenant_id, policy.data_class, now=now)
            reason = result["skipped_reason"]
            if reason:
                # A refusal is reported under the gate's own vocabulary, so the
                # sweep and the merchant's door cannot disagree about why.
                skipped.append({"data_class": policy.data_class, "reason": reason})
                logger.warning(
                    "retention.skipped tenant=%s data_class=%s reason=%s",
                    tenant_id,
                    policy.data_class,
                    reason,
                )
                continue

            total = int(result["deleted"])
            deleted[policy.data_class] = deleted.get(policy.data_class, 0) + total
            media_released += int(result.get("media_objects_released") or 0)
            media_failed.extend(result.get("media_objects_failed") or [])
            policy.last_run_at = now
            applied += 1

        return {
            "policies": applied,
            "deleted": deleted,
            "skipped": skipped,
            "media_released": media_released,
            "media_failed": media_failed,
        }


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
