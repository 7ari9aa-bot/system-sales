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

# Capability (what a caller asks for) -> plan feature (what the plan stores).
#
# These are DIFFERENT namespaces and must be mapped explicitly. `can()` used to
# pass the capability straight through as the feature name, so a lookup for
# `Entitlement.feature == "CanAddUser"` never matched a plan row that stores
# `max_users` — every capability check silently returned True. Adding a seat
# limit to a plan had no effect at all.
#
# Only the features the seeded plans actually define are mapped. A capability
# with no mapping is intentionally unrestricted (the documented
# "unknown capabilities are allowed by default" rule).
_CAPABILITY_FEATURE: dict[str, str] = {
    "CanAddUser": "max_users",
    "CanUseAI": "ai_agents",
    # `channels` is an ALLOWLIST of channel names, not a numeric limit, so it
    # cannot go through check_entitlement (which compares a limit against a
    # usage counter). Use EntitlementService.ensure_channel_allowed instead.
    "CanCreateChannel": "channels",
}

# Features whose "usage" is a live row count, not a period accumulator.
#
# Nothing writes a UsageRecord for seats: seats are a state, not something you
# consume per period. Reading the counter reported 0 forever, so a plan limit of
# 3 users could never be reached. Count the memberships instead.
_DERIVED_USAGE: dict[str, str] = {
    "max_users": "tenant_users",
    "seats": "tenant_users",
}


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
        derived = _DERIVED_USAGE.get(feature)
        if derived == "tenant_users":
            # Lazy import: identity.models is imported by the same routers that
            # import this module.
            from sqlalchemy import func

            from app.modules.identity.models import TenantUser

            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(TenantUser)
                        .where(TenantUser.tenant_id == tenant_id)
                    )
                ).scalar_one()
                or 0
            )

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
    async def plan_channels(session: AsyncSession, tenant_id: uuid.UUID):
        """The plan's `channels` value: a list of allowed names, or "*".

        Returns None when there is no active subscription or the plan does not
        mention channels — meaning "unrestricted".
        """
        subscription = await BillingService.get_subscription(session, tenant_id)
        if subscription is None:
            return None
        plan = (
            await session.execute(select(Plan).where(Plan.id == subscription.plan_id))
        ).scalar_one_or_none()
        if plan is None:
            return None
        return (plan.features or {}).get("channels")

    @staticmethod
    async def channel_allowed(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str | None
    ) -> bool:
        """Whether the plan includes `channel` (None = "any channel at all").

        `channels` is stored as an allowlist of names (starter: whatsapp +
        webchat, pro: five channels, enterprise: "*"), so it cannot be expressed
        as the numeric limit `check_entitlement` compares against a usage
        counter — which is why it was skipped entirely and the channel gate was
        decorative.
        """
        allowed = await EntitlementService.plan_channels(session, tenant_id)
        if allowed is None or allowed == "*":
            return True
        if not isinstance(allowed, list):
            # Unrecognised shape: do not block on a value we cannot read.
            return True
        if channel is None:
            return len(allowed) > 0
        return channel in allowed

    @staticmethod
    async def ensure_channel_allowed(
        session: AsyncSession, tenant_id: uuid.UUID, channel: str | None
    ) -> None:
        if not await EntitlementService.channel_allowed(session, tenant_id, channel):
            raise RateLimitExceededError(
                "plan does not include this channel",
                details={"channel": channel},
            )

    @staticmethod
    async def can(session: AsyncSession, tenant_id: uuid.UUID, capability: str) -> bool:
        """Canonical capability checks. Unknown capabilities are allowed by
        default; known ones consult plan entitlements + tenant status.

        This is a PREDICATE and must never raise. BillingService.check_entitlement
        raises RateLimitExceededError when a limit is exceeded, so it is caught
        here: a caller writing `if not await can(...)` would otherwise crash
        instead of taking the "not allowed" branch. Use ensure() when the error
        is what you want.
        """
        from app.core.errors import RateLimitExceededError
        from app.modules.identity.models import Tenant

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None or not tenant.is_active:
            return False

        if capability in (
            "CanUseAI",
            "CanSendCampaign",
            "CanUseVoice",
            "CanUseAPI",
            "CanCreateChannel",
            "CanAddUser",
        ):
            feature = _CAPABILITY_FEATURE.get(capability)
            if feature is None:
                # Unmapped capability -> unrestricted. Documented default, but
                # note this is also how the seat limit silently passed for so
                # long: the capability was never in the map at all, so
                # `Entitlement.feature == "CanAddUser"` matched nothing.
                return True
            if feature == "channels":
                # An allowlist, not a numeric limit. "Can this tenant add a
                # channel" = does the plan list any channel.
                return await EntitlementService.channel_allowed(session, tenant_id, None)
            try:
                return await BillingService.check_entitlement(
                    session, tenant_id, feature, requested=1
                )
            except RateLimitExceededError:
                return False
        return True

    @staticmethod
    async def ensure(session: AsyncSession, tenant_id: uuid.UUID, capability: str) -> None:
        from app.core.errors import RateLimitExceededError

        if not await EntitlementService.can(session, tenant_id, capability):
            raise RateLimitExceededError(
                f"plan does not allow: {capability}",
                details={"capability": capability},
            )


class BillingSnapshotService:
    """Spec §54: immutable period snapshot — never live-recalculate invoices."""

    @staticmethod
    async def close_period(
        session: AsyncSession, tenant_id: uuid.UUID, *, period_start, period_end
    ) -> dict:
        from datetime import datetime

        from sqlalchemy import select

        from app.modules.billing.models import Invoice, UsageRecord

        rows = (
            await session.execute(
                select(
                    UsageRecord.feature,
                    UsageRecord.quantity,
                ).where(
                    UsageRecord.tenant_id == tenant_id,
                    UsageRecord.period_date >= period_start,
                    UsageRecord.period_date < period_end,
                )
            )
        ).all()
        by_feature: dict[str, float] = {}
        for feature, quantity in rows:
            by_feature[feature] = by_feature.get(feature, 0) + float(quantity or 0)

        lines = [
            {"feature": feature, "quantity": quantity}
            for feature, quantity in sorted(by_feature.items())
        ]
        invoice = Invoice(
            tenant_id=tenant_id,
            number=f"INV-{period_start.strftime('%Y%m')}-{uuid.uuid4().hex[:6].upper()}",
            status="open",
            subtotal=0,
            total=0,
            currency="EGP",
            issued_at=datetime.now(UTC),
            extra={
                "snapshot": lines,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
        session.add(invoice)
        await session.flush()
        return {"invoice_id": str(invoice.id), "lines": lines}
