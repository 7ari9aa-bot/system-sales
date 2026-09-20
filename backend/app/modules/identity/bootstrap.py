"""Default rows a new tenant needs to be operational (review N-05).

`register` created a Tenant, a User and the owner membership — and nothing else.
A brand-new tenant therefore had no business calendar, no SLA policy and no
subscription, which is why every new surface reports 0 rows in production: the
features are not broken, they have nothing to read.

* SLA has no policy to apply, so no clock ever starts for a conversation.
* Entitlements are fail-open with no subscription, so plan limits do nothing.
* The AI budget has no policy, so there is no cap.

Seeding at creation makes a tenant operational the moment it exists, instead of
depending on an operator to remember — which is exactly what did not happen.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Sunday-Thursday 09:00-17:00, closed Friday and Saturday: the Egyptian working
# week.
#
# Keys are STRINGS because JSON object keys always are, and `null` is how the
# calendar expresses "closed" (see the BusinessCalendar docstring). Integer keys
# would also be accepted but are not what the API sends.
DEFAULT_HOURS: dict = {
    "0": [["09:00", "17:00"]],  # Monday
    "1": [["09:00", "17:00"]],  # Tuesday
    "2": [["09:00", "17:00"]],  # Wednesday
    "3": [["09:00", "17:00"]],  # Thursday
    "4": None,  # Friday — closed
    "5": None,  # Saturday — closed
    "6": [["09:00", "17:00"]],  # Sunday
}

DEFAULT_CALENDAR_NAME = "Default calendar"
DEFAULT_SLA_POLICY_NAME = "Default SLA"
DEFAULT_FIRST_RESPONSE_MINUTES = 60
DEFAULT_RESOLUTION_MINUTES = 1440
DEFAULT_PLAN_CODE = "starter"
DEFAULT_TRIAL_DAYS = 14

# §42: the percentage at which the gateway starts warning about AI spend. The
# alert thresholds themselves (50/80/90/100) live in the gateway.
DEFAULT_BUDGET_WARNING_THRESHOLD = 80


async def seed_tenant_defaults(session: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Create the default rows a tenant needs to be operational.

    Idempotent: safe to call on an existing tenant, and safe to call twice in
    one transaction. Returns what was created so a caller can log it — the
    point of this function is to remove a silent gap, so it must not introduce
    a silent one.

    Must be called with the tenant GUC bound (the rows are tenant-scoped and
    RLS applies).
    """
    from app.modules.operations.models import BusinessCalendar, SLAPolicy

    created = {
        "calendar": False,
        "sla_policy": False,
        "subscription": False,
        "budget_policy": False,
    }

    # --- business calendar -------------------------------------------------
    existing_calendar = (
        await session.execute(
            select(BusinessCalendar).where(
                BusinessCalendar.tenant_id == tenant_id,
                BusinessCalendar.is_default.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing_calendar is None:
        session.add(
            BusinessCalendar(
                tenant_id=tenant_id,
                name=DEFAULT_CALENDAR_NAME,
                timezone="Africa/Cairo",
                hours=DEFAULT_HOURS,
                holidays=[],
                is_default=True,
            )
        )
        await session.flush()
        created["calendar"] = True

    # --- SLA policy --------------------------------------------------------
    existing_policy = (
        await session.execute(
            select(SLAPolicy).where(
                SLAPolicy.tenant_id == tenant_id,
                SLAPolicy.is_default.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing_policy is None:
        session.add(
            SLAPolicy(
                tenant_id=tenant_id,
                name=DEFAULT_SLA_POLICY_NAME,
                first_response_minutes=DEFAULT_FIRST_RESPONSE_MINUTES,
                resolution_minutes=DEFAULT_RESOLUTION_MINUTES,
                applies_to_channel=None,  # all channels
                is_default=True,
                status="active",
            )
        )
        await session.flush()
        created["sla_policy"] = True

    # --- subscription (which materialises the plan's entitlements) ---------
    #
    # Deliberately tolerant of a missing plan: that is an environment state
    # (provision.py not run), not a bug in registration, and registration must
    # never fail because seeding could not complete. It IS reported in the
    # returned summary rather than swallowed.
    from app.modules.billing.models import Plan, Subscription
    from app.modules.billing.service import BillingService

    existing_subscription = (
        await session.execute(
            select(Subscription).where(Subscription.tenant_id == tenant_id)
        )
    ).scalars().first()
    if existing_subscription is None:
        plan = (
            await session.execute(select(Plan).where(Plan.code == DEFAULT_PLAN_CODE))
        ).scalar_one_or_none()
        if plan is None:
            logger.warning(
                "tenant.seed_skipped_subscription tenant=%s reason=plan_missing code=%s",
                tenant_id,
                DEFAULT_PLAN_CODE,
            )
        else:
            await BillingService.start_trial(
                session, tenant_id, plan_code=DEFAULT_PLAN_CODE, days=DEFAULT_TRIAL_DAYS
            )
            created["subscription"] = True

    # --- AI budget policy (§42) --------------------------------------------
    #
    # Without an explicit policy the gateway falls back to a deployment default,
    # so a tenant is never uncapped — but the cap is then invisible and cannot
    # be edited per tenant. Seeding it makes the ceiling a real, queryable row.
    #
    # Inserted with SQL rather than `ai.models`: `ai` already imports
    # `identity.deps`, so importing its models here would close a NEW
    # identity <-> ai cycle, which tests/test_module_boundaries.py fails on.
    # One row, four columns — not worth a cycle.
    from app.core.config import get_settings

    cap = get_settings().ai_monthly_budget_cap_default
    inserted = await session.execute(
        sa_text(
            "INSERT INTO ai_budget_policies "
            "(id, tenant_id, scope, agent_id, period, hard_cap, warning_threshold, on_exceed) "
            "SELECT :id, :tenant_id, 'tenant', NULL, 'monthly', :cap, :threshold, 'block' "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM ai_budget_policies "
            "  WHERE tenant_id = :tenant_id AND scope = 'tenant' AND period = 'monthly'"
            ")"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            "cap": Decimal(str(cap)),
            "threshold": DEFAULT_BUDGET_WARNING_THRESHOLD,
        },
    )
    created["budget_policy"] = bool(inserted.rowcount)

    logger.info("tenant.seeded tenant=%s created=%s", tenant_id, created)
    return created


__all__ = [
    "DEFAULT_BUDGET_WARNING_THRESHOLD",
    "DEFAULT_FIRST_RESPONSE_MINUTES",
    "DEFAULT_HOURS",
    "DEFAULT_PLAN_CODE",
    "DEFAULT_RESOLUTION_MINUTES",
    "DEFAULT_TRIAL_DAYS",
    "seed_tenant_defaults",
]
