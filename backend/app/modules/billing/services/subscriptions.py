"""Subscription and usage management service for Billing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, RateLimitExceededError, ValidationError
from app.modules.billing.models import (
    Entitlement,
    Invoice,
    Plan,
    Subscription,
    UsageRecord,
)

from ._common import _DERIVED_USAGE


class BillingService:
    """Subscription lifecycle, plan verification, and usage metering."""

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
    async def has_any_subscription(session: AsyncSession, tenant_id: uuid.UUID) -> bool:
        """Does this tenant have a subscription row in ANY state?"""
        return (
            await session.execute(
                select(Subscription.id).where(Subscription.tenant_id == tenant_id).limit(1)
            )
        ).scalar_one_or_none() is not None

    @staticmethod
    async def plan_exists(session: AsyncSession, plan_code: str) -> bool:
        """Is this a real plan code? Lets a caller probe before ``start_trial``."""
        return (
            await session.execute(select(Plan.id).where(Plan.code == plan_code).limit(1))
        ).scalar_one_or_none() is not None

    @staticmethod
    async def check_entitlement(
        session: AsyncSession, tenant_id: uuid.UUID, feature: str, *, requested: int = 1
    ) -> bool:
        """True when usage within limit; raises RateLimitExceededError otherwise."""
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
            return int(
                (
                    await session.execute(
                        text("SELECT COUNT(*) FROM tenant_users WHERE tenant_id = :tenant_id"),
                        {"tenant_id": tenant_id},
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
        session: AsyncSession, tenant_id: uuid.UUID, *, feature: str, quantity: Decimal
    ) -> None:
        """Append one metering row."""
        session.add(
            UsageRecord(
                tenant_id=tenant_id,
                feature=feature,
                quantity=quantity,
                period_date=datetime.now(UTC).date(),
            )
        )
        await session.flush()

    # ------------------------------------------------------------------
    # Section 19 read models — what the Settings Center's plan pages show
    # ------------------------------------------------------------------

    @staticmethod
    async def plan_for(session: AsyncSession, subscription: Subscription | None) -> Plan | None:
        """The plan row behind a subscription, or None when there is none.

        Read as its own query rather than a relationship: ``Subscription.plan_id`` is a
        plain FK column with no ORM relationship, and a lazy load inside an async session
        would raise on first access.
        """
        if subscription is None:
            return None
        return (
            await session.execute(select(Plan).where(Plan.id == subscription.plan_id))
        ).scalar_one_or_none()

    @staticmethod
    async def usage_summary(session: AsyncSession, tenant_id: uuid.UUID) -> list[dict[str, object]]:
        """Every metered feature the tenant has a limit for, with what it has used.

        The number the shop is judged against is the same one the gate uses:
        ``used_this_period`` (which knows that a seat count is a live row count, not an
        accumulator) compared with the entitlement's ``limit_value``. A feature with no
        entitlement row is not listed: an empty limit would read as "zero allowed", which
        is the opposite of "unrestricted".
        """
        subscription = await BillingService.get_subscription(session, tenant_id)
        if subscription is None:
            return []
        entitlements = (
            (
                await session.execute(
                    select(Entitlement)
                    .where(
                        Entitlement.tenant_id == tenant_id,
                        Entitlement.subscription_id == subscription.id,
                    )
                    .order_by(Entitlement.feature)
                )
            )
            .scalars()
            .all()
        )
        rows: list[dict[str, object]] = []
        listed: set[str] = set()
        for entitlement in entitlements:
            used = await BillingService.used_this_period(session, tenant_id, entitlement.feature)
            listed.add(entitlement.feature)
            rows.append(
                {
                    "feature": entitlement.feature,
                    "used": used,
                    "limit": entitlement.limit_value,
                    "is_unlimited": bool(entitlement.is_unlimited),
                }
            )
        # A feature the tenant has consumed this period but has NO entitlement for is
        # listed too, with no ceiling: the page is a usage report, and hiding real
        # consumption because the plan does not meter it would make the number the shop
        # sees disagree with what it was actually charged for. ``limit=None`` plus
        # ``is_unlimited`` says "no ceiling", which is what an absent entitlement means —
        # it never means "zero allowed".
        period_start = subscription.current_period_start
        metered = (
            (
                await session.execute(
                    select(UsageRecord.feature)
                    .where(
                        UsageRecord.tenant_id == tenant_id,
                        UsageRecord.period_date >= period_start.date(),
                    )
                    .group_by(UsageRecord.feature)
                    .order_by(UsageRecord.feature)
                )
            )
            .scalars()
            .all()
        )
        for feature in metered:
            if feature in listed:
                continue
            rows.append(
                {
                    "feature": feature,
                    "used": await BillingService.used_this_period(session, tenant_id, feature),
                    "limit": None,
                    "is_unlimited": True,
                }
            )
        return rows

    @staticmethod
    async def list_invoices(
        session: AsyncSession, tenant_id: uuid.UUID, *, limit: int = 25, offset: int = 0
    ) -> list[Invoice]:
        """This tenant's invoices, newest first.

        A closed period's snapshot and an ordinary invoice share the table, so both are
        returned: to the shop they are the same document. ``limit`` is clamped by the
        caller's dependency, never trusted from the query string.
        """
        return (
            (
                await session.execute(
                    select(Invoice)
                    .where(Invoice.tenant_id == tenant_id)
                    .order_by(Invoice.created_at.desc(), Invoice.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
