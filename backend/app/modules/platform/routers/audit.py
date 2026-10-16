"""Platform read surfaces — security trail (§67), outbox ledger (§19), and audit logs (§66)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.core.errors import NotFoundError, ValidationError
from app.modules.platform import schemas
from app.modules.platform.models import AuditLog, OutboxEvent, SecurityEvent
from app.modules.platform.routers._deps import (
    PageLimit,
    PageOffset,
    TenantContext,
    require_permission,
)

router = APIRouter(prefix="/platform", tags=["platform"])

# ---------------------------------------------------------------------------
# §67: the security-event read surface
#
# `security_events` had nine production writers and ZERO readers — the Wave C
# lesson ("built, tested in isolation, never called") in its purest form. This
# is the operator-visible half. Deliberations:
#
# * Gated by `settings:read` — the code every other admin-facing read uses;
#   no new permission strings are invented here.
# * Tenant isolation is EXPLICIT (`tenant_id == ctx.tenant_id`) on top of the
#   table's FORCE RLS. Pre-auth NULL-tenant rows (login failures recorded
#   before any tenant is known) are NOT returned: RLS makes them visible to
#   every tenant, so a tenant endpoint that passed them through would leak
#   one tenant's probing patterns to another. They belong to a future
#   platform-admin plane, which must make that exposure decision openly.
# * `details` is redacted through app.core.field_auth (§146): PII keys are
#   nulled without `pii:read`, secret keys (`vault_key`, tokens) ALWAYS.
# ---------------------------------------------------------------------------


@router.get("/security-events", response_model=schemas.SecurityEventListOut)
async def list_security_events(
    ctx: TenantContext = Depends(require_permission("settings:read")),
    event_type: str | None = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§67: this tenant's security trail, newest first. Read-only.

    It already sorted on ``(created_at, id)`` DESC — the tie-break the comment
    below explains — but had a ``limit`` and no ``offset``, so the trail was
    unreadable past its first page: a caller asking for ``offset=50`` was not
    refused, it was handed page 1 again and had no way to know. It also had no
    ``total``, so "the tenant has 4 000 login failures" and "the tenant has 50"
    were the same answer.
    """
    from app.core.field_auth import redact_fields

    conditions = [SecurityEvent.tenant_id == ctx.tenant_id]
    if event_type:
        conditions.append(SecurityEvent.event_type == event_type)
    total = (
        await ctx.session.execute(select(func.count(SecurityEvent.id)).where(*conditions))
    ).scalar_one()
    stmt = (
        select(SecurityEvent)
        .where(*conditions)
        # created_at alone is not a total order: security events written in one
        # transaction share now(), so an un-tied ORDER BY lets `limit` drop an
        # arbitrary row and lets equal-timestamp pages reorder. id (a uuid4) is
        # the deterministic tie-break — the same contract the notifications list
        # surface already uses, so the two reads do not disagree.
        .order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await ctx.session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
                "ip": event.ip,
                "details": redact_fields(
                    dict(event.details or {}), permission_codes=ctx.permission_codes
                ),
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# §19: the outbox read surface (package 2.2)
#
# ``add_outbox_event`` has writers in every module and the relay drains the
# table, but nothing could LOOK at what was staged: diagnostics counts backlog
# depth and nothing more, so "no event was lost" (this package's goal) was an
# unobservable claim. This is the operator-visible ledger.
#
# * outbox_events is a SYSTEM table with no tenant column: §19 puts tenancy
#   inside the envelope (``meta["tenant_id"]`` — the key the relay refuses to
#   publish without). The read filters on exactly that key, and because the
#   table has NO RLS backstop, the explicit predicate IS the isolation — the
#   tests pin that another tenant's row is a 404, not a 403.
# * Gated by `settings:read`, the code every other admin-facing read in this
#   module uses; no new permission strings.
# * DELIBERATELY no manual retry endpoint here: a re-staged event gets a NEW
#   outbox id, so consumers' ``processed_events`` dedupe (keyed on
#   ``meta["outbox_id"]``) would miss it and the effect would run twice.
#   Retries belong to the relay's durable backoff (``not_before``); a row
#   stranded mid-publish is reclaimed by POST /platform/diagnostics/remediate
#   under its own audit trail.
# ---------------------------------------------------------------------------

_OUTBOX_STATUSES: frozenset[str] = frozenset({"pending", "publishing", "published", "failed"})


def _outbox_event_summary(row: OutboxEvent) -> dict:
    return {
        "id": str(row.id),
        "aggregate_type": row.aggregate_type,
        "aggregate_id": str(row.aggregate_id),
        "stream": row.stream,
        "status": row.status,
        "attempts": int(row.attempts or 0),
        "last_error": row.last_error,
        "not_before": row.not_before.isoformat() if row.not_before else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }


@router.get("/outbox-events", response_model=schemas.OutboxEventListOut)
async def list_outbox_events(
    ctx: TenantContext = Depends(require_permission("settings:read")),
    status: str | None = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§19: this tenant's staged relay events, newest first. Read-only.

    A bounded page with a ``total``, and a ``(created_at, id)`` DESC sort —
    events staged in one transaction share ``now()``, so ``id`` is the
    tie-break that keeps page 2 from repeating page 1. The payload body is
    deliberately NOT listed; fetch a row for that.
    """
    if status is not None and status not in _OUTBOX_STATUSES:
        raise ValidationError(
            "unknown outbox event status",
            details={"status": status, "allowed": sorted(_OUTBOX_STATUSES)},
        )
    conditions = [OutboxEvent.meta["tenant_id"].as_string() == str(ctx.tenant_id)]
    if status is not None:
        conditions.append(OutboxEvent.status == status)
    total = (
        await ctx.session.execute(select(func.count(OutboxEvent.id)).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await ctx.session.execute(
                select(OutboxEvent)
                .where(*conditions)
                .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [_outbox_event_summary(row) for row in rows],
    }


@router.get("/outbox-events/{event_id}", response_model=schemas.OutboxEventDetailOut)
async def inspect_outbox_event(
    event_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    """§19: the full relay row — envelope, attempts AND the payload/meta the
    relay carried, the evidence a lost/duplicated event is investigated with.

    Tenant isolation rides the same ``meta["tenant_id"]`` predicate as the
    list: another tenant's event id answers 404.
    """
    row = (
        await ctx.session.execute(
            select(OutboxEvent).where(
                OutboxEvent.id == event_id,
                OutboxEvent.meta["tenant_id"].as_string() == str(ctx.tenant_id),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("outbox event not found")
    return {
        **_outbox_event_summary(row),
        "payload": dict(row.payload or {}),
        "meta": dict(row.meta or {}),
    }


# ---------------------------------------------------------------------------
# §66: the audit-log read surface (package 2.2)
#
# ``AuditService.write`` has callers across the app (every DLQ decision, tenant
# status change, secret rotation, retention write...) and ZERO readers — the
# Wave C lesson ("built, tested in isolation, never called") again. Deliberations
# mirror the §67 surface above:
#
# * Tenant isolation is EXPLICIT (``tenant_id == ctx.tenant_id``). Platform-
#   level rows with a NULL tenant are NOT returned: they carry actions taken
#   outside any tenant, and exposing them through a tenant endpoint is an
#   exposure decision that belongs to the platform-admin plane.
# * Gated by `settings:read`; no new permission strings.
# * The filters stay narrow: ``action``/``resource_type``/``source`` are exact
#   matches (no wildcards to widen the read), ``source`` is bounded to the
#   §66 vocabulary, and the period is a validated ``since``/``until`` pair.
# * The §66 lineage fields (``source`` / ``request_id`` / ``correlation_id``)
#   are part of the response. A row written outside a request scope has NULL
#   ids — they render as JSON null, never as a string "null".
# ---------------------------------------------------------------------------

_AUDIT_SOURCES: frozenset[str] = frozenset({"human", "ai", "automation", "system", "integration"})


@router.get("/audit-logs", response_model=schemas.AuditLogListOut)
async def list_audit_logs(
    ctx: TenantContext = Depends(require_permission("settings:read")),
    action: Annotated[str | None, Query(max_length=127)] = None,
    resource_type: Annotated[str | None, Query(max_length=63)] = None,
    source: str | None = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§66: this tenant's audited actions, newest first, with lineage.

    A bounded page with a ``total`` and a ``(created_at, id)`` DESC sort —
    rows written in one request share the transaction clock, so ``id`` is the
    tie-break. The period is inclusive/exclusive at the bounds the caller
    names (``since <= created_at < until``); a reversed range is a 400, not a
    silently empty page.
    """
    if source is not None and source not in _AUDIT_SOURCES:
        raise ValidationError(
            "unknown audit source",
            details={"source": source, "allowed": sorted(_AUDIT_SOURCES)},
        )
    if since is not None and until is not None and since > until:
        raise ValidationError(
            "audit period is reversed — since must not be after until",
            details={"since": since.isoformat(), "until": until.isoformat()},
        )
    conditions = [AuditLog.tenant_id == ctx.tenant_id]
    if action:
        conditions.append(AuditLog.action == action)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if source is not None:
        conditions.append(AuditLog.source == source)
    if since is not None:
        conditions.append(AuditLog.created_at >= since)
    if until is not None:
        conditions.append(AuditLog.created_at < until)
    total = (
        await ctx.session.execute(select(func.count(AuditLog.id)).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await ctx.session.execute(
                select(AuditLog)
                .where(*conditions)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": str(entry.id),
                "actor_user_id": str(entry.actor_user_id) if entry.actor_user_id else None,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "before": entry.before,
                "after": entry.after,
                "source": entry.source,
                "request_id": entry.request_id,
                "correlation_id": entry.correlation_id,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry in rows
        ],
    }
