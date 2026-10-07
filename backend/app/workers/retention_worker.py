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

import base64
import json
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

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
#   3. After the retention window expires, SchedulerWorker's global hourly
#      sweep calls `run_once()` in a tenant-bound transaction for hard delete.
#
# The hard delete is a CASCADE: deleting the tenant row cascades to all
# tenant-scoped tables (customers, conversations, messages, orders, etc.)
# via the FK ON DELETE CASCADE. The tenant.data_purged audit row commits
# INSIDE the delete transaction; the independent `tenant_data_purged`
# security event is emitted by OffboardingWorker.sweep_expired AFTER that
# commit succeeds — an audit row inside the transaction, an event after it.


class OffboardingWorker:
    """§49-50: handles the offboarding → deleted transition.

    This is NOT a stream worker or tenant-scoped scheduled job. The global
    scheduler queries only matured offboarding tenants once per hour.
    """

    @staticmethod
    async def run_once(session, tenant_id, *, now: datetime | None = None) -> dict:
        """Check if a tenant's offboarding retention has expired.

        If the retention window has NOT expired, returns the remaining days.
        If it HAS expired, performs the final hard delete (CASCADE).
        """
        from app.modules.identity.models import Tenant
        from app.modules.platform.models import AuditLog

        now = now or datetime.now(UTC)
        tenant = (
            await session.execute(
                select(Tenant)
                .where(Tenant.id == tenant_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if tenant is None:
            return {
                "tenant_id": str(tenant_id),
                "action": "skipped",
                "reason": "tenant is missing or already being processed",
            }

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

        # The retention window has expired — preserve a minimal global audit
        # row, then hard-delete the tenant. Its business tables cascade from
        # tenants.id; audit_logs.tenant_id is ON DELETE SET NULL, so the purge
        # record survives without retaining the deleted tenant's data.
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
        await session.delete(tenant)
        await session.flush()

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
        """§49: export tenant-owned records, including messages and ledgers.

        Every registered tenant-scoped table is selected through the bound
        tenant id. Credential material and operational queues are explicitly
        omitted; binary object contents remain in storage and are represented
        by their non-secret metadata rows.
        """
        from sqlalchemy import select

        from app.core.model_registry import Base
        from app.modules.identity.models import Role, Tenant, TenantUser, User

        def json_value(value):
            if isinstance(value, (UUID, uuid.UUID)):
                return str(value)
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            if isinstance(value, Decimal):
                return format(value, "f")
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, bytes | bytearray | memoryview):
                return base64.b64encode(bytes(value)).decode("ascii")
            if isinstance(value, dict):
                return {str(k): json_value(v) for k, v in value.items()}
            if isinstance(value, list | tuple):
                return [json_value(v) for v in value]
            try:
                json.dumps(value)
                return value
            except TypeError:
                return str(value)

        excluded_tables = {
            "audit_logs",
            "idempotency_keys",
            "outbox_events",
            "password_reset_tokens",
            "refresh_tokens",
            "scheduled_jobs",
            "security_events",
            "webhook_events",
            "webhook_deliveries",
        }
        protected_fragments = (
            "password",
            "secret",
            "token",
            "credential",
            "ciphertext",
            "private_key",
            "api_key",
            "signing_key",
        )

        tenant = (
            await session.execute(
                select(
                    Tenant.id,
                    Tenant.slug,
                    Tenant.name,
                    Tenant.currency,
                    Tenant.timezone,
                    Tenant.created_at,
                ).where(Tenant.id == tenant_id)
            )
        ).one()
        members = (
            await session.execute(
                select(
                    TenantUser.user_id,
                    User.email,
                    User.full_name,
                    Role.code.label("role_code"),
                    TenantUser.is_default,
                )
                .join(User, User.id == TenantUser.user_id)
                .outerjoin(Role, Role.id == TenantUser.role_id)
                .where(TenantUser.tenant_id == tenant_id)
                .order_by(User.email)
            )
        ).mappings().all()

        tables = Base.metadata.sorted_tables
        export: dict[str, list[dict]] = {}
        redacted: dict[str, list[str]] = {}
        for table in tables:
            if "tenant_id" not in table.c or table.name in excluded_tables:
                continue
            allowed_columns = [
                column
                for column in table.c
                if not any(fragment in column.name.lower() for fragment in protected_fragments)
            ]
            removed_columns = sorted(set(table.c.keys()) - {c.name for c in allowed_columns})
            statement = select(*allowed_columns).where(table.c.tenant_id == tenant_id)
            rows = (await session.execute(statement)).mappings().all()
            export[table.name] = [
                {column: json_value(value) for column, value in row.items()}
                for row in rows
            ]
            if removed_columns:
                redacted[table.name] = removed_columns

        data = {
            "tenant": {
                "id": str(tenant.id),
                "slug": tenant.slug,
                "name": tenant.name,
                "currency": tenant.currency,
                "timezone": tenant.timezone,
                "created_at": json_value(tenant.created_at),
            },
            "members": [
                {
                    "user_id": str(row["user_id"]),
                    "email": row["email"],
                    "full_name": row["full_name"],
                    "role_code": row["role_code"],
                    "is_default": row["is_default"],
                }
                for row in members
            ],
            **export,
        }
        return {
            "schema_version": "1.0",
            "tenant_id": str(tenant_id),
            "exported_at": datetime.now(UTC).isoformat(),
            "counts": {
                key: len(rows) if isinstance(rows, list) else 1
                for key, rows in data.items()
            },
            "redacted_fields": redacted,
            "omitted_tables": sorted(excluded_tables),
            "media_content": "metadata_only; binary objects remain in configured object storage",
            "data": data,
        }

    @staticmethod
    async def sweep_expired(*, batch_size: int = 100) -> int:
        """Hard-delete matured offboarding tenants from the global scheduler.

        The tenant lifecycle table is global and safe to enumerate. Each
        destructive cascade runs in its own tenant-bound transaction, and its
        audit record commits before the independent security event is emitted.
        """
        from app.modules.identity.models import Tenant
        from app.modules.identity.service import _record_security_event

        now = datetime.now(UTC)
        async with SessionLocal() as session:
            tenant_ids = (
                await session.execute(
                    select(Tenant.id)
                    .where(
                        Tenant.lifecycle_state == "offboarding",
                        Tenant.deletion_scheduled_at.is_not(None),
                        Tenant.deletion_scheduled_at <= now,
                    )
                    .order_by(Tenant.deletion_scheduled_at)
                    .limit(max(1, min(batch_size, 500)))
                )
            ).scalars().all()

        purged = 0
        for tenant_id in tenant_ids:
            try:
                async with SessionLocal() as session:
                    async with session.begin():
                        await bind_tenant(session, tenant_id)
                        result = await OffboardingWorker.run_once(
                            session, tenant_id, now=now
                        )
                if result["action"] == "purged":
                    purged += 1
                    await _record_security_event(
                        "tenant_data_purged",
                        details={"tenant_id": str(tenant_id), "action": "hard_delete_cascade"},
                    )
            except Exception:  # noqa: BLE001 — one blocked tenant must not starve the batch
                logger.exception("offboarding.purge_failed tenant=%s", tenant_id)
        return purged
