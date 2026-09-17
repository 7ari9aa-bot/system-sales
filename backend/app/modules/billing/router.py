"""PLATFORM + BILLING routes — notifications, webhooks, subscription, usage."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.modules.billing.service import BillingService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform.service import NotificationService, WebhookService

platform_router = APIRouter(prefix="/notifications", tags=["notifications"])
webhooks_router = APIRouter(prefix="/webhook-endpoints", tags=["webhooks"])
billing_router = APIRouter(prefix="/billing", tags=["billing"])


class NotifyRequest(BaseModel):
    channel: str = Field(pattern="^(email|sms|push|inapp)$")
    body: str = Field(min_length=1, max_length=4096)
    subject: str | None = Field(default=None, max_length=512)


@platform_router.post("", status_code=201)
async def queue_notification(ctx: TenantCtxDep, body: NotifyRequest):
    notification = await NotificationService.queue(
        ctx.session,
        ctx.tenant_id,
        channel=body.channel,
        body=body.body,
        subject=body.subject,
        user_id=ctx.user.id,
    )
    return {"id": str(notification.id), "status": notification.status}


@platform_router.get("")
async def list_notifications(ctx: TenantCtxDep, limit: int = 50):
    rows = await NotificationService.list(ctx.session, ctx.tenant_id, limit=limit)
    return [
        {
            "id": str(n.id),
            "channel": n.channel,
            "subject": n.subject,
            "body": n.body,
            "status": n.status,
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
        }
        for n in rows
    ]


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

