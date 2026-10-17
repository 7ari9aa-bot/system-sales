"""Spec §165: centralized CanX enforcement — one place, not per-module.

Flow: Auth → Tenant → Permission → Entitlement → Domain rule.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import RateLimitExceededError
from app.modules.billing.models import Plan

from ._common import _CAPABILITY_FEATURE
from .subscriptions import BillingService


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
        # The one fact needed from identity is whether the tenant is switched
        # on. Reading `Tenant` for it means importing another domain's mapped
        # class inside the hot authorization path, so the flag is selected
        # directly — same single-value statement as the seat count.
        is_active = (
            await session.execute(
                text("SELECT is_active FROM tenants WHERE id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        ).scalar_one_or_none()
        if not is_active:
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
                # Unmapped capability -> unrestricted.
                return True
            if feature == "channels":
                # An allowlist, not a numeric limit.
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
        if not await EntitlementService.can(session, tenant_id, capability):
            raise RateLimitExceededError(
                f"plan does not allow: {capability}",
                details={"capability": capability},
            )
