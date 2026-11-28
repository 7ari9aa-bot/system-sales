"""PLATFORM + BILLING routes — webhooks, subscription, usage.

Outbound-notification delivery used to live here as a second `platform_router`
with a `/notifications` prefix that duplicated the live user-facing routes in
`modules/notifications/router.py`. It was never mounted (main.py imports only
`billing_router` and `webhooks_router` from this module), so it was unreachable
dead code that would have shadowed the notifications centre the moment anyone
did mount it. `platform.service.NotificationService.queue` still exists for a
future outbound-delivery surface.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.platform.billing.service import BillingService, BillingSnapshotService
from app.modules.errors import ValidationError
from app.platform.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.platform.platform.service import WebhookService

webhooks_router = APIRouter(prefix="/webhook-endpoints", tags=["webhooks"])
billing_router = APIRouter(prefix="/billing", tags=["billing"])


class WebhookEndpointRequest(BaseModel):
    url: str = Field(min_length=8)
    events: list[str] = Field(default_factory=list)


class WebhookEndpointCreated(BaseModel):
    """The register/rotate response — the ONLY response that ever carries a
    signing secret. No list or detail model includes ``secret``."""

    id: uuid.UUID
    url: str
    # Shown once at creation (register) or rotation: the server cannot re-show
    # it later, so a caller that loses this response must rotate again.
    secret: str
    events: list[str]
    active: bool = True


class WebhookEndpointOut(BaseModel):
    """A registry row WITHOUT its secret — the list surface is secret-free."""

    id: uuid.UUID
    url: str
    events: list[str]
    active: bool
    created_at: datetime | None = None


class WebhookEndpointRotated(BaseModel):
    id: uuid.UUID
    secret: str  # the NEW secret, shown exactly once (see WebhookEndpointCreated)
    rotated: bool = True
    active: bool = True


class WebhookEndpointDeleted(BaseModel):
    id: uuid.UUID
    active: bool = False


@webhooks_router.post("", status_code=201, response_model=WebhookEndpointCreated)
async def register_webhook(
    body: WebhookEndpointRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    endpoint = await WebhookService.register_endpoint(
        ctx.session,
        ctx.tenant_id,
        url=body.url,
        events=body.events,
        actor_user_id=ctx.user.id,
    )
    return {
        "id": str(endpoint.id),
        "url": endpoint.url,
        "secret": endpoint.plaintext_secret,  # shown once at creation
        "events": endpoint.events,
        "active": bool(endpoint.is_active),
    }


@webhooks_router.get("", response_model=list[WebhookEndpointOut])
async def list_webhook_endpoints(ctx: TenantContext = Depends(require_permission("settings:read"))):
    """This tenant's registered outbound webhook endpoints — never their secrets.

    Unpaginated on the same grounds as ``GET /platform/flags``: endpoints are
    tenant configuration, not a growing user dataset, so the row count is
    bounded by what an operator can name. Ordered ``(created_at, id)`` —
    ``created_at`` alone is not a total order for rows created in one
    transaction, and ``id`` is the tie-break that keeps the list stable.
    """
    rows = await WebhookService.list_endpoints(ctx.session, ctx.tenant_id)
    return [
        {
            "id": str(row.id),
            "url": row.url,
            "events": list(row.events or []),
            "active": bool(row.is_active),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


_DELIVERY_STATUSES = frozenset({"queued", "delivered", "failed", "dead"})


@webhooks_router.get("/deliveries")
async def list_webhook_deliveries(
    ctx: TenantContext = Depends(require_permission("settings:read")),
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
):
    """What this tenant's endpoints actually received, newest first.

    Declared before the parameterised routes on purpose. Today they differ by method, so
    nothing shadows anything — but FastAPI matches in declaration order, and the day someone
    adds ``GET /webhook-endpoints/{endpoint_id}`` a static ``/deliveries`` declared after it
    would be read as an id. The payload is never returned: it is the event body the caller's
    own systems produced, and echoing it would put customer data on a settings page.
    """
    if status is not None and status not in _DELIVERY_STATUSES:
        raise ValidationError(
            "unknown delivery status",
            details={"status": status, "allowed": sorted(_DELIVERY_STATUSES)},
        )
    if limit < 1 or limit > 100:
        raise ValidationError("limit must be between 1 and 100", details={"limit": limit})
    if offset < 0:
        raise ValidationError("offset must not be negative", details={"offset": offset})
    rows = await WebhookService.list_deliveries(
        ctx.session, ctx.tenant_id, limit=limit, offset=offset, status=status
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "webhook_id": str(row.webhook_id),
                "event_name": row.event_name,
                "status": row.status,
                "attempts": row.attempts,
                "response_code": row.response_code,
                "last_error": row.last_error,
                "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
                "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@webhooks_router.post("/{endpoint_id}/rotate", response_model=WebhookEndpointRotated)
async def rotate_webhook_secret(
    endpoint_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Rotate an endpoint's signing secret after a suspected leak.

    The NEW secret rides this response and nowhere else; the old one stops
    verifying from the next delivery (see ``WebhookService.rotate_endpoint_
    secret``). Audited as ``webhook_endpoint.secret_rotated``.
    """
    endpoint = await WebhookService.rotate_endpoint_secret(
        ctx.session,
        ctx.tenant_id,
        endpoint_id,
        actor_user_id=ctx.user.id,
    )
    return {
        "id": str(endpoint.id),
        "secret": endpoint.plaintext_secret,
        "rotated": True,
        "active": bool(endpoint.is_active),
    }


@webhooks_router.delete("/{endpoint_id}", response_model=WebhookEndpointDeleted)
async def delete_webhook_endpoint(
    endpoint_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Soft delete: the endpoint stops receiving deliveries (``is_active=False``),
    its delivery history stays, and the decision is audited. Idempotent."""
    endpoint = await WebhookService.deactivate_endpoint(
        ctx.session,
        ctx.tenant_id,
        endpoint_id,
        actor_user_id=ctx.user.id,
    )
    return {"id": str(endpoint.id), "active": bool(endpoint.is_active)}


@billing_router.get("/subscription")
async def get_subscription(ctx: TenantCtxDep):
    """The subscription, and the plan behind it.

    The Settings Center's "current plan" page has to name the plan and what it costs, so the
    row carries its plan instead of leaving the page to fetch a catalog it has no endpoint
    for. Money is returned as a string, like every other amount in the API: a float would
    round a Numeric(12,2) price on the way to JSON.
    """
    subscription = await BillingService.get_subscription(ctx.session, ctx.tenant_id)
    if subscription is None:
        return {"status": "none"}
    plan = await BillingService.plan_for(ctx.session, subscription)
    return {
        "id": str(subscription.id),
        "status": subscription.status,
        "current_period_start": (
            subscription.current_period_start.isoformat()
            if subscription.current_period_start
            else None
        ),
        "current_period_end": (
            subscription.current_period_end.isoformat() if subscription.current_period_end else None
        ),
        "cancel_at_period_end": bool(subscription.cancel_at_period_end),
        "plan": (
            {
                "code": plan.code,
                "name": plan.name,
                "price": str(plan.price),
                "currency": plan.currency,
                "interval": plan.interval,
            }
            if plan is not None
            else None
        ),
    }


@billing_router.get("/usage/summary")
async def get_usage_summary(ctx: TenantCtxDep):
    """What this tenant has used this period, feature by feature, against its limits.

    Reads the same numbers the entitlement gate reads, so the page and the refusal can
    never disagree. A feature with no entitlement row is absent rather than zero: an empty
    limit means "unrestricted", and printing it as 0 would say the opposite.
    """
    return {"items": await BillingService.usage_summary(ctx.session, ctx.tenant_id)}


@billing_router.get("/invoices")
async def list_invoices(
    ctx: TenantCtxDep,
    limit: int = 25,
    offset: int = 0,
):
    """This tenant's invoices, newest first, bounded.

    A closed period's frozen snapshot and an ordinary invoice are both documents the shop
    owes or has paid, so both are listed. The totals are strings for the same reason the
    price is: never a float on the way out.
    """
    if limit < 1 or limit > 100:
        raise ValidationError("limit must be between 1 and 100", details={"limit": limit})
    if offset < 0:
        raise ValidationError("offset must not be negative", details={"offset": offset})
    rows = await BillingService.list_invoices(
        ctx.session, ctx.tenant_id, limit=limit, offset=offset
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "number": row.number,
                "status": row.status,
                "total": str(row.total),
                "subtotal": str(row.subtotal),
                "tax": str(row.tax),
                "currency": row.currency,
                "issued_at": row.issued_at.isoformat() if row.issued_at else None,
                "due_at": row.due_at.isoformat() if row.due_at else None,
                "paid_at": row.paid_at.isoformat() if row.paid_at else None,
                "period_start": row.period_start.isoformat() if row.period_start else None,
                "period_end": row.period_end.isoformat() if row.period_end else None,
            }
            for row in rows
        ]
    }


@billing_router.post("/start-trial", status_code=201)
async def start_trial(ctx: TenantContext = Depends(require_permission("billing:write"))):
    subscription = await BillingService.start_trial(ctx.session, ctx.tenant_id)
    return {"id": str(subscription.id), "status": subscription.status}


class UsageRequest(BaseModel):
    feature: str = Field(max_length=63)
    # Decimal, not float: `usage_records.quantity` is Numeric(14,2).
    quantity: Decimal = Field(gt=0)


@billing_router.post("/usage", status_code=201)
async def record_usage(
    body: UsageRequest,
    ctx: TenantContext = Depends(require_permission("billing:write")),
):
    """Append one metering row — a billing write, so a `staff` account (which the
    seeded role matrix gives no `billing:*` code) cannot mint usage against its
    own invoice. Internal callers use `BillingService.record_usage` directly."""
    await BillingService.record_usage(
        ctx.session, ctx.tenant_id, feature=body.feature, quantity=body.quantity
    )
    used = await BillingService.used_this_period(ctx.session, ctx.tenant_id, body.feature)
    return {"feature": body.feature, "used_this_period": used}


class ClosePeriodRequest(BaseModel):
    period_start: date
    period_end: date


@billing_router.post("/periods/close", status_code=201)
async def close_billing_period(
    body: ClosePeriodRequest,
    ctx: TenantContext = Depends(require_permission("billing:write")),
):
    """Freeze a period into an immutable snapshot. 409 if already closed."""
    invoice = await BillingSnapshotService.close_period(
        ctx.session,
        ctx.tenant_id,
        period_start=body.period_start,
        period_end=body.period_end,
    )
    return BillingSnapshotService.snapshot_view(invoice)


@billing_router.get("/periods/snapshot")
async def get_billing_snapshot(
    ctx: TenantCtxDep,
    period_start: date,
    period_end: date,
):
    """Read a closed period's frozen totals — never a live re-aggregation."""
    invoice = await BillingSnapshotService.get_snapshot(
        ctx.session,
        ctx.tenant_id,
        period_start=period_start,
        period_end=period_end,
    )
    return BillingSnapshotService.snapshot_view(invoice)
