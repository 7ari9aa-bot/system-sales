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

from app.modules.billing.service import BillingService, BillingSnapshotService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform.service import WebhookService

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
        "secret": endpoint.secret,  # shown once at creation
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


@webhooks_router.post(
    "/{endpoint_id}/rotate", response_model=WebhookEndpointRotated
)
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
        "secret": endpoint.secret,
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
    subscription = await BillingService.get_subscription(ctx.session, ctx.tenant_id)
    if subscription is None:
        return {"status": "none"}
    return {
        "id": str(subscription.id),
        "status": subscription.status,
        "current_period_end": (
            subscription.current_period_end.isoformat()
            if subscription.current_period_end
            else None
        ),
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

