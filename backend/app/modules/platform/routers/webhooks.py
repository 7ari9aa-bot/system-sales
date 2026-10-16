"""Platform webhook DLQ surface (§24) — inspect, retry, ignore, resolve."""

import uuid

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.errors import NotFoundError, ValidationError
from app.modules.platform import schemas
from app.modules.platform.models import (
    WEBHOOK_EVENT_STATUSES,
    AuditLog,
    WebhookEvent,
)
from app.modules.platform.routers._deps import (
    PageLimit,
    PageOffset,
    TenantContext,
    TenantCtxDep,
    _require_platform_admin,
)

router = APIRouter(prefix="/platform", tags=["platform"])

# Which statuses each close-out accepts — the law against silent drift.
_WEBHOOK_IGNORE_FROM: frozenset[str] = frozenset({"pending", "processing", "failed", "dead"})
_WEBHOOK_RESOLVE_FROM: frozenset[str] = frozenset({"failed", "dead", "ignored"})


async def _load_webhook_event(ctx: TenantContext, event_id: uuid.UUID) -> WebhookEvent:
    row = (
        await ctx.session.execute(select(WebhookEvent).where(WebhookEvent.id == event_id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("webhook event not found")
    return row


def _audit_webhook_dlq_op(
    ctx: TenantContext,
    row: WebhookEvent,
    *,
    action: str,
    before: dict | None,
    after: dict | None,
) -> None:
    """§66/§67: every DLQ decision leaves a paper trail (who, which row,
    from what to what, and the operator's reason)."""
    ctx.session.add(
        AuditLog(
            tenant_id=row.tenant_id or ctx.tenant_id,
            actor_user_id=ctx.user.id,
            action=action,
            resource_type="webhook_event",
            resource_id=str(row.id),
            before=before,
            after=after,
        )
    )


def _webhook_event_summary(row: WebhookEvent) -> dict:
    return {
        "id": str(row.id),
        "provider": row.provider,
        "external_event_id": row.external_event_id,
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "signature_valid": row.signature_valid,
        "processing_status": row.processing_status,
        "attempts": row.attempts,
        "last_error": row.last_error,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
    }


@router.post("/webhook-events/{event_id}/retry", response_model=schemas.WebhookRetryOut)
async def admin_retry_webhook_event(ctx: TenantCtxDep, event_id: uuid.UUID):
    """§24: replay a failed or dead-lettered inbound webhook ingress row.

    Stages a ``webhook.event.retry`` event on the webhook.events stream; the
    WebhookWorker then re-runs the EXACT ingest block the channel webhook
    router runs (``IngestService.process_webhook_event``) under the row's
    tenant — the per-message idempotency keys make the replay safe.

    webhook_events is FORCE-RLS, so the row is loaded under the request's
    tenant context: the admin operates on the ACTIVE tenant's rows (X-Tenant-Id
    selects the tenant). FAILED rows (budget left) and DEAD rows (budget spent
    — the DLQ: replay is exactly what it exists for) can be retried; the row
    must have resolved a tenant — an un-attributed ingress has nothing to
    re-ingest and no tenant scope to run it under. The replay re-runs the
    ingest block WITHOUT re-verifying a provider signature, so only rows whose
    signature was verified at ingress are ever replayed (fail-closed, §22).
    """
    _require_platform_admin(ctx)
    from app.core.events.writer import add_outbox_event

    row = await _load_webhook_event(ctx, event_id)
    if not row.signature_valid:
        # Fail-closed: the retry path bypasses the signature check (the raw
        # provider headers are not stored), so the row's recorded
        # ``signature_valid`` flag is the ONLY proof this payload was
        # provider-signed. The ingress router stamps True exactly when
        # ``adapter.check_signature`` passed; a row without that proof must
        # never be turned back into messages by an authenticated surface.
        raise ValidationError(
            "webhook event was never signature-verified — refusing to replay",
            details={"event_id": str(event_id)},
        )
    if row.tenant_id is None:
        raise ValidationError(
            "webhook event has no resolved tenant — nothing to re-ingest",
            details={"event_id": str(event_id)},
        )
    if row.processing_status not in ("failed", "dead"):
        raise ValidationError(
            "only failed or dead-lettered webhook events can be retried",
            details={"event_id": str(event_id), "status": row.processing_status},
        )
    await add_outbox_event(
        ctx.session,
        aggregate_type="webhook",
        aggregate_id=row.id,
        event_type="webhook.event.retry",
        tenant_id=row.tenant_id,
        payload={"webhook_event_id": str(row.id)},
    )
    _audit_webhook_dlq_op(
        ctx,
        row,
        action="webhook_event.retry_scheduled",
        before={"processing_status": row.processing_status},
        after={"retry": "scheduled"},
    )
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "status": row.processing_status,
        "retry": "scheduled",
    }


@router.get("/webhook-events", response_model=schemas.WebhookEventListOut)
async def admin_list_webhook_events(
    ctx: TenantCtxDep,
    status: str | None = None,
    provider: str | None = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§24 Inspect: the active tenant's ingress ledger — newest first, with
    the full DLQ vocabulary (dead/ignored/resolved included). The raw payload
    body is deliberately NOT listed; fetch a row for that.

    The reference paging route of this module: a bounded page, a ``total`` so a
    caller can tell a full page from the whole list, and an
    ``(received_at, id)`` DESC sort. ``received_at`` alone is not a total order —
    a burst of deliveries lands inside one clock tick — so ``id`` is the
    tie-break that keeps page 2 from repeating page 1.
    """
    _require_platform_admin(ctx)
    if status is not None and status not in WEBHOOK_EVENT_STATUSES:
        raise ValidationError(
            "unknown webhook event status",
            details={"status": status, "allowed": sorted(WEBHOOK_EVENT_STATUSES)},
        )
    conditions = []
    if status is not None:
        conditions.append(WebhookEvent.processing_status == status)
    if provider is not None:
        conditions.append(WebhookEvent.provider == provider)
    total = (
        await ctx.session.execute(select(func.count(WebhookEvent.id)).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await ctx.session.execute(
                select(WebhookEvent)
                .where(*conditions)
                .order_by(WebhookEvent.received_at.desc(), WebhookEvent.id.desc())
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
        "items": [_webhook_event_summary(row) for row in rows],
    }


@router.get("/webhook-events/{event_id}", response_model=schemas.WebhookEventDetailOut)
async def admin_inspect_webhook_event(ctx: TenantCtxDep, event_id: uuid.UUID):
    """§24 Inspect: the full ingress row — envelope, attempts trail AND the
    raw payload, the evidence a replay/ignore/resolve decision is made on."""
    _require_platform_admin(ctx)
    row = await _load_webhook_event(ctx, event_id)
    return {**_webhook_event_summary(row), "payload": row.payload}


@router.post("/webhook-events/{event_id}/ignore", response_model=schemas.WebhookCloseOut)
async def admin_ignore_webhook_event(
    ctx: TenantCtxDep, event_id: uuid.UUID, reason: str | None = None
):
    """§24 Ignore: close a DLQ case as not-worth-processing. The row stays
    (nothing disappears) with status → ignored, and the decision is audited."""
    _require_platform_admin(ctx)
    row = await _load_webhook_event(ctx, event_id)
    if row.processing_status not in _WEBHOOK_IGNORE_FROM:
        raise ValidationError(
            "cannot ignore a webhook event in this state",
            details={
                "event_id": str(event_id),
                "status": row.processing_status,
                "allowed_from": sorted(_WEBHOOK_IGNORE_FROM),
            },
        )
    before = row.processing_status
    row.processing_status = "ignored"
    _audit_webhook_dlq_op(
        ctx,
        row,
        action="webhook_event.ignored",
        before={"processing_status": before, "reason": reason},
        after={"processing_status": "ignored"},
    )
    return {"id": str(row.id), "status": "ignored"}


@router.post("/webhook-events/{event_id}/resolve", response_model=schemas.WebhookCloseOut)
async def admin_resolve_webhook_event(
    ctx: TenantCtxDep, event_id: uuid.UUID, reason: str | None = None
):
    """§24 Mark resolved: the underlying issue was fixed out-of-band (or the
    effect was applied manually) — close the case as resolved. Audited."""
    _require_platform_admin(ctx)
    row = await _load_webhook_event(ctx, event_id)
    if row.processing_status not in _WEBHOOK_RESOLVE_FROM:
        raise ValidationError(
            "cannot resolve a webhook event in this state",
            details={
                "event_id": str(event_id),
                "status": row.processing_status,
                "allowed_from": sorted(_WEBHOOK_RESOLVE_FROM),
            },
        )
    before = row.processing_status
    row.processing_status = "resolved"
    _audit_webhook_dlq_op(
        ctx,
        row,
        action="webhook_event.resolved",
        before={"processing_status": before, "reason": reason},
        after={"processing_status": "resolved"},
    )
    return {"id": str(row.id), "status": "resolved"}
