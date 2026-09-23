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

import json
import logging
import uuid
from decimal import Decimal

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.core.tenancy import current_scope

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
DEFAULT_CALENDAR_TIMEZONE = "Africa/Cairo"
DEFAULT_SLA_POLICY_NAME = "Default SLA"
DEFAULT_FIRST_RESPONSE_MINUTES = 60
DEFAULT_RESOLUTION_MINUTES = 1440
DEFAULT_PLAN_CODE = "starter"
DEFAULT_TRIAL_DAYS = 14

# §42: the percentage at which the gateway starts warning about AI spend. The
# alert thresholds themselves (50/80/90/100) live in the gateway.
DEFAULT_BUDGET_WARNING_THRESHOLD = 80


async def seed_tenant_defaults(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    include_subscription: bool = True,
) -> dict:
    """Create the default rows a tenant needs to be operational.

    Idempotent: safe to call on an existing tenant, and safe to call twice in
    one transaction. Returns what was created so a caller can log it — the
    point of this function is to remove a silent gap, so it must not introduce
    a silent one.

    Must be called with the tenant GUC bound (the rows are tenant-scoped and
    RLS applies).

    `include_subscription=False` skips ONLY the plan binding. That matters for
    a BACKFILL: binding an existing tenant to a plan activates its entitlement
    allow-list, and `starter` permits only whatsapp + webchat, so a tenant
    already using another channel would silently lose it. A calendar and an SLA
    policy are pure additions with no such side effect, so a backfill can safely
    do those and leave the commercial decision to a human.
    """
    created = {
        "calendar": False,
        "sla_policy": False,
        "subscription": False,
        "budget_policy": False,
        "metric_definitions": False,
    }

    # --- business calendar -------------------------------------------------
    #
    # INSERTED with SQL rather than `operations.models`, for the same reason the
    # AI budget policy below is SQL and the same reason
    # `OrderService._audit_shipping` is: `operations` imports `identity.deps`, so
    # importing its models here held an identity -> operations edge — and with it
    # the edge that keeps the 11-module cyclic component from splitting — alive
    # for two default rows. `INSERT … SELECT … WHERE NOT EXISTS` is the same
    # idempotent guard this function already applied, in one statement, and it
    # closes the check-then-insert race the two-step version had.
    #
    # workspace_id / location_id are bound from current_scope() because that is
    # exactly what WorkspaceScopeMixin's column default reads (§151); leaving
    # them out would seed a tenant-wide row where the ORM wrote a scoped one.
    workspace_id, location_id = current_scope()
    inserted_calendar = await session.execute(
        sa_text(
            "INSERT INTO business_calendars "
            "(id, tenant_id, workspace_id, location_id, name, timezone, hours, "
            "holidays, is_default) "
            "SELECT :id, :tenant_id, :workspace_id, :location_id, :name, "
            ":timezone, CAST(:hours AS jsonb), CAST(:holidays AS jsonb), true "
            "WHERE NOT EXISTS (SELECT 1 FROM business_calendars "
            "  WHERE tenant_id = :tenant_id AND is_default IS TRUE)"
        ),
        {
            "id": str(uuid7()),
            "tenant_id": str(tenant_id),
            "workspace_id": str(workspace_id) if workspace_id else None,
            "location_id": str(location_id) if location_id else None,
            "name": DEFAULT_CALENDAR_NAME,
            "timezone": DEFAULT_CALENDAR_TIMEZONE,
            "hours": json.dumps(DEFAULT_HOURS),
            "holidays": json.dumps([]),
        },
    )
    created["calendar"] = bool(inserted_calendar.rowcount)

    # --- SLA policy --------------------------------------------------------
    inserted_policy = await session.execute(
        sa_text(
            "INSERT INTO sla_policies "
            "(id, tenant_id, workspace_id, location_id, name, "
            "first_response_minutes, resolution_minutes, applies_to_channel, "
            "is_default, status) "
            "SELECT :id, :tenant_id, :workspace_id, :location_id, :name, "
            ":first_response_minutes, :resolution_minutes, NULL, true, 'active' "
            "WHERE NOT EXISTS (SELECT 1 FROM sla_policies "
            "  WHERE tenant_id = :tenant_id AND is_default IS TRUE)"
        ),
        {
            "id": str(uuid7()),
            "tenant_id": str(tenant_id),
            "workspace_id": str(workspace_id) if workspace_id else None,
            "location_id": str(location_id) if location_id else None,
            "name": DEFAULT_SLA_POLICY_NAME,
            "first_response_minutes": DEFAULT_FIRST_RESPONSE_MINUTES,
            "resolution_minutes": DEFAULT_RESOLUTION_MINUTES,
        },
    )
    created["sla_policy"] = bool(inserted_policy.rowcount)

    # --- subscription (which materialises the plan's entitlements) ---------
    #
    # Deliberately tolerant of a missing plan: that is an environment state
    # (provision.py not run), not a bug in registration, and registration must
    # never fail because seeding could not complete. It IS reported in the
    # returned summary rather than swallowed.
    #
    # Asked of BillingService rather than read off `billing.models`: which
    # subscription rows count as "already provisioned" is billing's own status
    # vocabulary, and identity has no business re-implementing it against
    # plans/subscriptions columns it does not own.
    from app.modules.billing.service import BillingService

    already_subscribed = await BillingService.has_any_subscription(session, tenant_id)
    if include_subscription and not already_subscribed:
        if not await BillingService.plan_exists(session, DEFAULT_PLAN_CODE):
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

    # --- canonical metric definitions (§167) --------------------------------
    #
    # The in-code MetricRegistry is the single source of truth; metric_definitions
    # is its tenant-visible audit copy. Without this call the table mirrored
    # NOTHING (seed_definitions had no caller), so every tenant measured itself
    # against a registry it could never see. Pushed here so a tenant's rows exist
    # and equal the registry from the moment it is provisioned. seed_definitions
    # CONVERGES on change, so re-running this on an existing tenant repairs any
    # drifted row and never clobbers an in-sync one.
    #
    # Function-scope import: identity -> platform is a cycle edge already present
    # (deps/models), and pulling metrics in at module scope would couple identity
    # to platform at load time for zero benefit.
    from app.modules.platform.metrics import seed_definitions

    created["metric_definitions"] = (await seed_definitions(session, tenant_id)) > 0

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
