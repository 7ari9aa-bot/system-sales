"""A trial that ended without payment: the owner can sign in and pay, the business API is shut.

`trial_expired` is the state behind "the trial is over, locked until you pay". The pieces that must
hold, each pinned here because getting any one wrong either locks a paying customer out or leaves an
unpaid tenant running for free:

* the policy lets the owner sign in and reach billing, and closes the business API;
* it is NOT operational, so the coarse `is_active` flag follows it;
* it never schedules a deletion (offboarding does, and a lapsed trial is not a goodbye);
* a tenant cannot put itself into it or out of it: only the platform admin moves it;
* paying (-> active) works; an unpaid trial cannot slip into past_due/grace (they assume a bill).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import Tenant
from app.modules.identity.service import (
    ALLOWED_TRANSITIONS,
    PLATFORM_ONLY_LIFECYCLE_TARGETS,
    STATE_POLICIES,
    TENANT_OPERATIONAL_STATES,
    TENANT_REQUESTABLE_LIFECYCLE_TARGETS,
)
from app.modules.identity.services.lifecycle import TenantLifecycleService


def test_the_policy_keeps_sign_in_and_data_but_closes_the_api_and_the_paid_features() -> None:
    policy = STATE_POLICIES["trial_expired"]
    assert policy.allows_login is True  # they must reach the pay page
    assert policy.allows_data_access is True  # and be able to take their data out
    assert policy.allows_api is False
    assert policy.allows_ai is False
    assert policy.allows_channels is False
    assert policy.allows_automation is False


def test_it_is_not_an_operational_state() -> None:
    assert "trial_expired" not in TENANT_OPERATIONAL_STATES
    assert TenantLifecycleService.is_coarse_active("trial_expired") is False


def test_only_a_trial_or_a_fresh_tenant_can_expire_and_paying_moves_it_on() -> None:
    # `active` is a source because new tenants are created active and the trial lives on the
    # subscription; the sweep (tests/test_trial_expiry_sweep.py) keeps a paying customer out.
    sources = {s for s, targets in ALLOWED_TRANSITIONS.items() if "trial_expired" in targets}
    assert sources == {"trial", "active"}
    assert ALLOWED_TRANSITIONS["trial_expired"] == frozenset(
        {"active", "suspended", "offboarding", "deleted"}
    )


def test_an_unpaid_trial_cannot_become_past_due_or_grace() -> None:
    # past_due/grace mean "a bill failed"; nothing was ever billed for a trial.
    assert "past_due" not in ALLOWED_TRANSITIONS["trial_expired"]
    assert "grace" not in ALLOWED_TRANSITIONS["trial_expired"]


def test_a_tenant_cannot_request_the_state_itself() -> None:
    assert "trial_expired" in PLATFORM_ONLY_LIFECYCLE_TARGETS
    assert "trial_expired" not in TENANT_REQUESTABLE_LIFECYCLE_TARGETS


async def _tenant(db: AsyncSession, tenant_id) -> Tenant:
    return (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()


async def _to_trial(db: AsyncSession, tenant_id) -> None:
    tenant = await _tenant(db, tenant_id)
    tenant.lifecycle_state = "trial"
    tenant.is_active = True
    await db.flush()


async def test_expiring_a_trial_closes_the_flag_and_schedules_no_deletion(
    db: AsyncSession, tenant_ctx
) -> None:
    await _to_trial(db, tenant_ctx.tenant_id)

    tenant = await TenantLifecycleService.transition(
        db, tenant_ctx.tenant_id, "trial_expired", reason="trial ended unpaid"
    )

    assert tenant.lifecycle_state == "trial_expired"
    assert tenant.is_active is False
    assert tenant.deletion_scheduled_at is None  # offboarding would set this; we must not
    assert tenant.grace_ends_at is None
    assert tenant.suspended_at is None


async def test_paying_brings_an_expired_trial_back_to_active(db: AsyncSession, tenant_ctx) -> None:
    await _to_trial(db, tenant_ctx.tenant_id)
    await TenantLifecycleService.transition(db, tenant_ctx.tenant_id, "trial_expired")

    tenant = await TenantLifecycleService.transition(db, tenant_ctx.tenant_id, "active")

    assert tenant.lifecycle_state == "active"
    assert tenant.is_active is True
