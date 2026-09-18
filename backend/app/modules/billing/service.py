"""BILLING service — plans, subscriptions, entitlements, usage metering.

Gating rule: features with entitlements are enforced at the API/service layer
(require_entitlement); Stripe integration activates once keys exist — until
then subscriptions run in trial/manual mode without blocking the core.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, RateLimitExceededError, ValidationError
from app.modules.billing.models import (
    Entitlement,
    Plan,
    Subscription,
    UsageRecord,
)


class BillingService:
    @staticmethod
    async def start_trial(
        session: AsyncSession, tenant_id: uuid.UUID, *, plan_code: str = "starter", days: int = 14
    ) -> Subscription:
        plan = (
            await session.execute(select(Plan).where(Plan.code == plan_code))
        ).scalar_one_or_none()
        if plan is None:
            raise NotFoundError(f"unknown plan: {plan_code}")
        existing = (
            await session.execute(
                select(Subscription).where(
                    Subscription.tenant_id == tenant_id,
                    Subscription.status.in_(["trialing", "active", "past_due"]),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ValidationError("tenant already has an active subscription")
        subscription = Subscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            status="trialing",
            current_period_start=datetime.now(UTC),
            current_period_end=datetime.now(UTC) + timedelta(days=days),
        )
        session.add(subscription)
        await session.flush()
        # copy plan features as entitlements (None limit = unlimited flag off)
        features = plan.features or {}
        for feature, limit in features.items():
            if feature in ("channels", "custom"):
                continue
            session.add(
                Entitlement(
                    tenant_id=tenant_id,
                    subscription_id=subscription.id,
                    feature=feature,
                    limit_value=int(limit) if isinstance(limit, int) else None,
                    is_unlimited=limit is None,
                )
            )
        await session.flush()
        return subscription

    @staticmethod
    async def get_subscription(session: AsyncSession, tenant_id: uuid.UUID) -> Subscription | None:
        return (
            await session.execute(
                select(Subscription)
                .where(
                    Subscription.tenant_id == tenant_id,
                    Subscription.status.in_(["trialing", "active", "past_due"]),
                )
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def check_entitlement(
        session: AsyncSession, tenant_id: uuid.UUID, feature: str, *, requested: int = 1
    ) -> bool:
        """True when usage within limit; raises RateLimitExceededError otherwise.
        Features without an entitlement row are unrestricted by default."""
        subscription = await BillingService.get_subscription(session, tenant_id)
        if subscription is None:
            return True
        entitlement = (
            await session.execute(
                select(Entitlement).where(
                    Entitlement.tenant_id == tenant_id,
                    Entitlement.subscription_id == subscription.id,
                    Entitlement.feature == feature,
                )
            )
        ).scalar_one_or_none()
        if entitlement is None or entitlement.is_unlimited or entitlement.limit_value is None:
            return True
        used = await BillingService.used_this_period(session, tenant_id, feature)
        if used + requested > entitlement.limit_value:
            raise RateLimitExceededError(
                f"plan limit reached for {feature}",
                details={"used": used, "limit": entitlement.limit_value},
            )
        return True

    @staticmethod
    async def used_this_period(session: AsyncSession, tenant_id: uuid.UUID, feature: str) -> int:
        subscription = await BillingService.get_subscription(session, tenant_id)
        start = subscription.current_period_start if subscription else None
        stmt = select(UsageRecord.quantity).where(
            UsageRecord.tenant_id == tenant_id, UsageRecord.feature == feature
        )
        if start is not None:
            stmt = stmt.where(UsageRecord.period_date >= start.date())
        rows = (await session.execute(stmt)).scalars().all()
        return int(sum(rows))

    @staticmethod
    async def record_usage(
        session: AsyncSession, tenant_id: uuid.UUID, *, feature: str, quantity: float
    ) -> None:
        session.add(
            UsageRecord(
                tenant_id=tenant_id,
                feature=feature,
                quantity=quantity,
                period_date=datetime.now(UTC).date(),
            )
        )
        await session.flush()


class EntitlementService:
    """Spec §165: centralized CanX enforcement — one place, not per-module.

    Flow: Auth → Tenant → Permission → Entitlement → Domain rule.
    """

    @staticmethod
    async def can(session: AsyncSession, tenant_id: uuid.UUID, capability: str) -> bool:
        """Canonical capability checks. Unknown capabilities are allowed by
        default; known ones consult plan entitlements + tenant status."""
        from app.modules.identity.models import Tenant

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None or not tenant.is_active:
            return False

        if capability in ("CanUseAI", "CanSendCampaign", "CanUseVoice", "CanUseAPI"):
            allowed = await BillingService.check_entitlement(
                session, tenant_id, capability, requested=1
            )
            return allowed
        if capability in ("CanCreateChannel", "CanAddUser"):
            return await BillingService.check_entitlement(
                session, tenant_id, capability, requested=1
            )
        return True

    @staticmethod
    async def ensure(session: AsyncSession, tenant_id: uuid.UUID, capability: str) -> None:
        from app.core.errors import RateLimitExceededError

        if not await EntitlementService.can(session, tenant_id, capability):
            raise RateLimitExceededError(
                f"plan does not allow: {capability}",
                details={"capability": capability},
            )
