"""Spec §165 - entitlements are enforced centrally, and fail OPEN by default.

The enforcement was wired into four real flows (AI auto-reply, channel
creation, invitations, campaigns). These tests pin the property that makes that
safe to ship: a tenant with no plan limits is unrestricted, so switching
enforcement on cannot break an existing tenant. Only an explicit limit is
enforced.

Database-backed (a subscription + entitlement row are needed), so they skip
locally and run in CI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import RateLimitExceededError
from app.modules.billing.models import Entitlement, Plan, Subscription
from app.modules.billing.service import EntitlementService


async def _subscription(db, tenant_id) -> Subscription:
    plan = Plan(
        code=f"plan-{uuid.uuid4().hex[:8]}",
        name="Test Plan",
        price="0",
        interval="month",
    )
    db.add(plan)
    await db.flush()
    subscription = Subscription(
        tenant_id=tenant_id,
        plan_id=plan.id,
        status="active",
        current_period_start=datetime.now(UTC),
        current_period_end=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(subscription)
    await db.flush()
    return subscription


async def test_no_subscription_is_unrestricted(db, tenant_ctx):
    """The fail-open default. Without it, turning enforcement on would have
    silently blocked every tenant that has not been put on a plan yet."""
    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanUseAI") is True
    assert (
        await EntitlementService.can(db, tenant_ctx.tenant_id, "CanSendCampaign") is True
    )
    # ensure() must not raise either
    await EntitlementService.ensure(db, tenant_ctx.tenant_id, "CanAddUser")


async def test_unknown_capability_is_allowed(db, tenant_ctx):
    """A capability the service does not model must not become an outage."""
    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanDoSomethingNew")


async def test_an_explicit_limit_is_enforced(db, tenant_ctx):
    subscription = await _subscription(db, tenant_ctx.tenant_id)
    db.add(
        Entitlement(
            tenant_id=tenant_ctx.tenant_id,
            subscription_id=subscription.id,
            feature="CanSendCampaign",
            limit_value=0,
        )
    )
    await db.flush()

    assert (
        await EntitlementService.can(db, tenant_ctx.tenant_id, "CanSendCampaign") is False
    )
    with pytest.raises(RateLimitExceededError):
        await EntitlementService.ensure(
            db, tenant_ctx.tenant_id, "CanSendCampaign"
        )


async def test_an_unlimited_entitlement_is_not_limited(db, tenant_ctx):
    subscription = await _subscription(db, tenant_ctx.tenant_id)
    db.add(
        Entitlement(
            tenant_id=tenant_ctx.tenant_id,
            subscription_id=subscription.id,
            feature="CanUseAI",
            is_unlimited=True,
        )
    )
    await db.flush()
    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanUseAI") is True


async def test_a_deactivated_tenant_loses_every_capability(db, tenant_ctx):
    """Tenant status is checked before any plan logic."""
    from app.modules.identity.models import Tenant

    tenant = (
        await db.execute(
            __import__("sqlalchemy").select(Tenant).where(Tenant.id == tenant_ctx.tenant_id)
        )
    ).scalar_one()
    tenant.is_active = False
    await db.flush()

    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanUseAI") is False
