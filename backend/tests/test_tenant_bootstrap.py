"""Tenant provisioning seeds the defaults a tenant needs (review N-05).

`register` used to create only the Tenant, the User and the owner membership.
Every new surface then reported 0 rows in production — not because the features
were broken, but because they had nothing to read: no business calendar for the
SLA clock, no SLA policy to apply, no subscription so entitlements were
fail-open and plan limits did nothing.

These tests pin both halves: the seed runs, and what it seeds is actually usable
(a valid calendar that closes the weekend, a default policy, a subscription that
materialises entitlements).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import BudgetPolicy
from app.modules.billing.models import Entitlement, Subscription
from app.modules.identity.bootstrap import (
    DEFAULT_HOURS,
    DEFAULT_PLAN_CODE,
    seed_tenant_defaults,
)
from app.modules.identity.models import Tenant
from app.modules.identity.service import AuthService
from app.modules.operations.models import BusinessCalendar, SLAPolicy
from app.modules.operations.sla import BusinessClock, validate_calendar


@dataclass
class _Cal:
    timezone: str = "UTC"
    hours: dict = field(default_factory=dict)
    holidays: list = field(default_factory=list)


def _dt(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# ------------------------------------------------- the seed is usable -----


def test_the_default_calendar_is_valid() -> None:
    """A seed that the validator rejects would fail every tenant creation."""
    validate_calendar(DEFAULT_HOURS, [])


def test_the_default_calendar_closes_the_weekend() -> None:
    """Sunday-Thursday working week: Friday and Saturday are closed.

    This is the property the SLA clock depends on, and the one the string-key
    bug in `_windows_for` silently broke.
    """
    clock = BusinessClock(_Cal(timezone="Africa/Cairo", hours=DEFAULT_HOURS))

    # 2026-09-25 is a Friday, 2026-09-26 a Saturday, 2026-09-27 a Sunday.
    assert clock.is_open(_dt(2026, 9, 25, 12, 0)) is False, "Friday must be closed"
    assert clock.is_open(_dt(2026, 9, 26, 12, 0)) is False, "Saturday must be closed"
    assert clock.is_open(_dt(2026, 9, 27, 12, 0)) is True, "Sunday must be open"


def test_the_default_calendar_uses_string_weekday_keys() -> None:
    """JSON object keys are always strings; int keys would not survive the API."""
    assert all(isinstance(key, str) for key in DEFAULT_HOURS)
    assert set(DEFAULT_HOURS) == {str(d) for d in range(7)}


# ------------------------------------------------------ register seeds -----


async def test_register_seeds_calendar_policy_and_subscription(
    db: AsyncSession, tenant_ctx
):
    email = f"owner-{uuid.uuid4().hex[:10]}@test.local"
    user, tenant = await AuthService.register(
        db,
        tenant_name="Seeded Co",
        tenant_slug=f"seeded-{uuid.uuid4().hex[:8]}",
        email=email,
        password="secret-password",
        full_name="Seeded Owner",
    )

    calendar = (
        await db.execute(
            select(BusinessCalendar).where(BusinessCalendar.tenant_id == tenant.id)
        )
    ).scalars().all()
    assert len(calendar) == 1, "a new tenant must have exactly one default calendar"
    assert calendar[0].is_default is True
    assert calendar[0].hours == DEFAULT_HOURS

    policy = (
        await db.execute(select(SLAPolicy).where(SLAPolicy.tenant_id == tenant.id))
    ).scalars().all()
    assert len(policy) == 1, "a new tenant must have a default SLA policy"
    assert policy[0].is_default is True
    assert policy[0].status == "active"

    subscription = (
        await db.execute(
            select(Subscription).where(Subscription.tenant_id == tenant.id)
        )
    ).scalars().all()
    assert len(subscription) == 1, "a new tenant must have a subscription"
    assert user.id is not None

    # §42: without an explicit policy the gateway falls back to a deployment
    # default, so the tenant is never uncapped — but the cap would then be
    # invisible and uneditable per tenant.
    budget = (
        await db.execute(select(BudgetPolicy).where(BudgetPolicy.tenant_id == tenant.id))
    ).scalars().all()
    assert len(budget) == 1, "a new tenant must have an AI budget policy"
    assert budget[0].scope == "tenant"
    assert budget[0].hard_cap > 0, "the seeded cap must not be zero (zero means uncapped)"


async def test_the_seeded_subscription_materialises_entitlements(
    db: AsyncSession, tenant_ctx
):
    """Without entitlements the plan limits cannot do anything (N-01)."""
    _, tenant = await AuthService.register(
        db,
        tenant_name="Entitled Co",
        tenant_slug=f"entitled-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="secret-password",
        full_name="Entitled Owner",
    )

    rows = (
        await db.execute(
            select(Entitlement).where(Entitlement.tenant_id == tenant.id)
        )
    ).scalars().all()

    # The starter plan defines ai_agents + max_users; `channels` is an
    # allowlist and is intentionally not an Entitlement row.
    features = {row.feature for row in rows}
    assert "max_users" in features
    assert "ai_agents" in features


async def test_registering_a_tenant_that_already_has_defaults_is_safe(
    db: AsyncSession, tenant_ctx
):
    """Idempotent: a second call must not create a duplicate default."""
    _, tenant = await AuthService.register(
        db,
        tenant_name="Twice Co",
        tenant_slug=f"twice-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="secret-password",
        full_name="Twice Owner",
    )

    created = await seed_tenant_defaults(db, tenant.id)
    assert created == {
        "calendar": False,
        "sla_policy": False,
        "subscription": False,
        "budget_policy": False,
        "metric_definitions": False,
    }

    calendars = (
        await db.execute(
            select(BusinessCalendar).where(BusinessCalendar.tenant_id == tenant.id)
        )
    ).scalars().all()
    assert len(calendars) == 1


async def test_register_does_not_fail_when_the_plan_is_absent(
    db: AsyncSession, tenant_ctx
):
    """A missing plan is an environment state (provision.py not run), not a
    reason to refuse a signup — and it is reported, not swallowed."""
    from app.modules.billing.models import Plan

    plan = (
        await db.execute(select(Plan).where(Plan.code == DEFAULT_PLAN_CODE))
    ).scalar_one_or_none()
    if plan is None:
        pytest.skip("starter plan not seeded here")
    original_code = plan.code
    plan.code = f"moved-{uuid.uuid4().hex[:8]}"
    await db.flush()
    try:
        _, tenant = await AuthService.register(
            db,
            tenant_name="No Plan Co",
            tenant_slug=f"noplan-{uuid.uuid4().hex[:8]}",
            email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
            password="secret-password",
            full_name="No Plan Owner",
        )
        # Registration succeeded; the calendar and policy are still seeded.
        calendars = (
            await db.execute(
                select(BusinessCalendar).where(BusinessCalendar.tenant_id == tenant.id)
            )
        ).scalars().all()
        assert len(calendars) == 1
        assert (
            await db.execute(
                select(Subscription).where(Subscription.tenant_id == tenant.id)
            )
        ).scalars().all() == []
    finally:
        plan.code = original_code
        await db.flush()


async def test_the_seeded_calendar_belongs_to_the_new_tenant_only(
    db: AsyncSession, tenant_ctx
):
    """The seed must not touch the caller's own tenant."""
    before = (
        await db.execute(
            select(BusinessCalendar).where(
                BusinessCalendar.tenant_id == tenant_ctx.tenant_id
            )
        )
    ).scalars().all()

    _, tenant = await AuthService.register(
        db,
        tenant_name="Isolated Co",
        tenant_slug=f"isolated-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="secret-password",
        full_name="Isolated Owner",
    )
    assert tenant.id != tenant_ctx.tenant_id

    after = (
        await db.execute(
            select(BusinessCalendar).where(
                BusinessCalendar.tenant_id == tenant_ctx.tenant_id
            )
        )
    ).scalars().all()
    assert len(after) == len(before)


async def test_the_new_tenant_starts_active(db: AsyncSession, tenant_ctx):
    """A registered tenant must be able to use the API immediately."""
    _, tenant = await AuthService.register(
        db,
        tenant_name="Active Co",
        tenant_slug=f"active-{uuid.uuid4().hex[:8]}",
        email=f"owner-{uuid.uuid4().hex[:10]}@test.local",
        password="secret-password",
        full_name="Active Owner",
    )

    row = (
        await db.execute(select(Tenant).where(Tenant.id == tenant.id))
    ).scalar_one()
    assert row.lifecycle_state in ("active", "trial")
    assert row.is_active is True
