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

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.modules.billing.service import BillingService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform.service import WebhookService

webhooks_router = APIRouter(prefix="/webhook-endpoints", tags=["webhooks"])
billing_router = APIRouter(prefix="/billing", tags=["billing"])


class WebhookEndpointRequest(BaseModel):
    url: str = Field(min_length=8)
    events: list[str] = Field(default_factory=list)


@webhooks_router.post("", status_code=201)
async def register_webhook(
    body: WebhookEndpointRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    endpoint = await WebhookService.register_endpoint(
        ctx.session,
        ctx.tenant_id,
        url=body.url,
        events=body.events,
    )
    return {
        "id": str(endpoint.id),
        "url": endpoint.url,
        "secret": endpoint.secret,  # shown once at creation
        "events": endpoint.events,
    }


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
    quantity: float = Field(gt=0)


@billing_router.post("/usage", status_code=201)
async def record_usage(ctx: TenantCtxDep, body: UsageRequest):
    await BillingService.record_usage(
        ctx.session, ctx.tenant_id, feature=body.feature, quantity=body.quantity
    )
    used = await BillingService.used_this_period(ctx.session, ctx.tenant_id, body.feature)
    return {"feature": body.feature, "used_this_period": used}

