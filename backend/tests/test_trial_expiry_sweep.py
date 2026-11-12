"""The trial-expiry lock: it must lock the right tenant, and never a customer who paid.

The sweep runs on a timer with nobody watching and flips a tenant to a state that closes the
business API, so the dangerous failures are silent ones in both directions: locking someone who is
paying, or "running" while a FORCE-RLS read returns nothing and locking no one. Each case below is
a real tenant with real subscription rows, run through the real sweep and the real lifecycle
transition, and the positive case proves the sweep does lock (so a green run is not a no-op).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import bind_tenant
from app.modules.billing.models import Plan, Subscription
from app.modules.billing.services.trial_expiry import lock_expired_trials, parse_lock_start
from app.modules.identity.deps import get_tenant_ctx
from app.modules.identity.models import Tenant
from app.modules.identity.services.lifecycle import TenantLifecycleService

CUTOFF = datetime(2026, 12, 1, tzinfo=UTC)
NOW = datetime(2026, 12, 20, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _sessions(app_sessions_on_test_connection):
    """The sweep opens its own sessions; bind them to the test transaction."""


@pytest.fixture
def lock_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "trial_lock_starts_at", CUTOFF.isoformat())


async def _plan(db: AsyncSession) -> Plan:
    plan = (await db.execute(sa.select(Plan).where(Plan.code == "starter"))).scalar_one()
    return plan


async def _tenant(
    db: AsyncSession, *subs: tuple[str, datetime | None, datetime | None]
) -> uuid.UUID:
    """A fresh `active` tenant with the given (status, period_start, period_end) subscriptions."""
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Sweep Tenant")
    db.add(tenant)
    await db.flush()
    await bind_tenant(db, tenant.id)
    plan = await _plan(db)
    for status, start, end in subs:
        db.add(
            Subscription(
                tenant_id=tenant.id,
                plan_id=plan.id,
                status=status,
                current_period_start=start,
                current_period_end=end,
            )
        )
    await db.flush()
    return tenant.id


def _expired_trial() -> tuple[str, datetime, datetime]:
    """A trial that began after the cutoff and ended before NOW."""
    start = CUTOFF + timedelta(days=1)
    return ("trialing", start, start + timedelta(days=14))


async def _state(db: AsyncSession, tenant_id: uuid.UUID) -> tuple[str, bool]:
    row = (
        await db.execute(
            sa.text("SELECT lifecycle_state, is_active FROM tenants WHERE id = :t"),
            {"t": tenant_id},
        )
    ).one()
    return row[0], row[1]


async def test_an_expired_post_cutoff_trial_is_locked(db, lock_on) -> None:
    tenant_id = await _tenant(db, _expired_trial())

    locked = await lock_expired_trials(now=NOW)

    assert locked >= 1  # not a silent no-op: a FORCE-RLS read returning nothing would give 0
    assert await _state(db, tenant_id) == ("trial_expired", False)


async def test_it_does_nothing_while_the_setting_is_empty(db, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "trial_lock_starts_at", "")
    tenant_id = await _tenant(db, _expired_trial())

    assert await lock_expired_trials(now=NOW) == 0
    assert await _state(db, tenant_id) == ("active", True)


@pytest.mark.parametrize("raw", ["not-a-date", "2026-13-45", "   ", "yesterday"])
async def test_an_unparseable_setting_leaves_the_lock_off(db, monkeypatch, raw) -> None:
    monkeypatch.setattr(get_settings(), "trial_lock_starts_at", raw)
    tenant_id = await _tenant(db, _expired_trial())

    assert await lock_expired_trials(now=NOW) == 0
    assert await _state(db, tenant_id) == ("active", True)


def test_a_naive_timestamp_is_read_as_utc() -> None:
    assert parse_lock_start("2026-12-01T00:00:00") == CUTOFF
    assert parse_lock_start("") is None
    assert parse_lock_start(None) is None


async def test_a_trial_that_started_before_the_cutoff_is_never_touched(db, lock_on) -> None:
    start = CUTOFF - timedelta(days=60)
    tenant_id = await _tenant(db, ("trialing", start, start + timedelta(days=14)))

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("active", True)


async def test_a_trial_that_started_exactly_at_the_cutoff_is_locked(db, lock_on) -> None:
    tenant_id = await _tenant(db, ("trialing", CUTOFF, CUTOFF + timedelta(days=14)))

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("trial_expired", False)


async def test_a_trial_still_running_is_not_locked(db, lock_on) -> None:
    start = NOW - timedelta(days=3)
    tenant_id = await _tenant(db, ("trialing", start, start + timedelta(days=14)))

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("active", True)


async def test_a_trial_ending_exactly_now_is_not_locked_yet(db, lock_on) -> None:
    tenant_id = await _tenant(db, ("trialing", NOW - timedelta(days=14), NOW))

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("active", True)


async def test_a_paying_customer_is_never_locked(db, lock_on) -> None:
    start = CUTOFF + timedelta(days=1)
    tenant_id = await _tenant(db, ("active", start, start + timedelta(days=30)))

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("active", True)


async def test_an_expired_trial_next_to_a_paid_plan_is_not_locked(db, lock_on) -> None:
    """The customer started a trial, then paid: the old trial row must not lock them."""
    trial = _expired_trial()
    paid = ("active", trial[2], trial[2] + timedelta(days=30))
    tenant_id = await _tenant(db, trial, paid)

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("active", True)


@pytest.mark.parametrize("status", ["past_due", "canceled", "expired"])
async def test_any_trace_of_a_non_trial_subscription_blocks_the_lock(db, lock_on, status) -> None:
    trial = _expired_trial()
    tenant_id = await _tenant(db, trial, (status, trial[1], trial[2]))

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("active", True)


async def test_a_tenant_with_no_subscription_is_not_locked(db, lock_on) -> None:
    tenant_id = await _tenant(db)

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("active", True)


async def test_a_trial_with_missing_dates_is_not_locked(db, lock_on) -> None:
    tenant_id = await _tenant(db, ("trialing", None, None))

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("active", True)


async def test_a_suspended_tenant_is_left_alone(db, lock_on) -> None:
    tenant_id = await _tenant(db, _expired_trial())
    await db.execute(
        sa.text(
            "UPDATE tenants SET lifecycle_state = 'suspended', is_active = false WHERE id = :t"
        ),
        {"t": tenant_id},
    )

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("suspended", False)


async def test_running_it_twice_changes_nothing_the_second_time(db, lock_on) -> None:
    tenant_id = await _tenant(db, _expired_trial())

    await lock_expired_trials(now=NOW)
    second = await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("trial_expired", False)
    assert second == 0


async def test_one_locked_tenant_does_not_lock_its_neighbour(db, lock_on) -> None:
    expired = await _tenant(db, _expired_trial())
    paying = await _tenant(db, ("active", CUTOFF, CUTOFF + timedelta(days=30)))

    await lock_expired_trials(now=NOW)

    assert (await _state(db, expired))[0] == "trial_expired"
    assert (await _state(db, paying))[0] == "active"


async def test_a_locked_tenant_is_audited_with_a_reason(db, lock_on) -> None:
    tenant_id = await _tenant(db, _expired_trial())

    await lock_expired_trials(now=NOW)

    reason = (
        await db.execute(
            sa.text("SELECT status_reason FROM tenants WHERE id = :t"), {"t": tenant_id}
        )
    ).scalar_one()
    assert reason == "free trial ended without payment"


async def test_paying_unlocks_a_locked_tenant(db, lock_on) -> None:
    tenant_id = await _tenant(db, _expired_trial())
    await lock_expired_trials(now=NOW)
    assert (await _state(db, tenant_id))[0] == "trial_expired"

    await TenantLifecycleService.transition(db, tenant_id, "active")

    assert await _state(db, tenant_id) == ("active", True)


async def test_a_locked_tenant_is_shut_out_of_the_api_but_can_still_reach_billing(
    db, tenant_ctx, lock_on
) -> None:
    """The point of the whole feature, through the real request gate."""
    from starlette.requests import Request

    from app.core.errors import PermissionDeniedError
    from app.modules.identity.deps import AuthedUser

    def request(path: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [],
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 1),
            }
        )

    start = CUTOFF + timedelta(days=1)
    await bind_tenant(db, tenant_ctx.tenant_id)
    plan = await _plan(db)
    db.add(
        Subscription(
            tenant_id=tenant_ctx.tenant_id,
            plan_id=plan.id,
            status="trialing",
            current_period_start=start,
            current_period_end=start + timedelta(days=14),
        )
    )
    await db.flush()
    await lock_expired_trials(now=NOW)
    assert (await _state(db, tenant_ctx.tenant_id))[0] == "trial_expired"

    user = AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner")
    with pytest.raises(PermissionDeniedError):
        await get_tenant_ctx(request("/api/v1/customers"), db, user)
    ctx = await get_tenant_ctx(request("/api/v1/billing/subscription"), db, user)
    assert ctx.tenant_id == tenant_ctx.tenant_id


async def test_a_tenant_that_changed_state_after_being_listed_is_not_locked(
    db, lock_on, monkeypatch
) -> None:
    """The race that matters: a tenant is a candidate, then moves on before its turn.

    The sweep lists candidates, then locks each one in its own transaction. Anything that lands in
    between (a payment moving the tenant, an admin suspending it) must win, so the decision is
    re-made under the row lock. Here the state changes at exactly that gap: after the candidate
    list is read, when the sweep binds the tenant for its own transaction.
    """
    from app.modules.billing.services import trial_expiry

    tenant_id = await _tenant(db, _expired_trial())
    real_bind = trial_expiry.bind_tenant

    async def bind_after_the_tenant_moved(session, tid, **kwargs):
        await session.execute(
            sa.text(
                "UPDATE tenants SET lifecycle_state = 'suspended', is_active = false WHERE id = :t"
            ),
            {"t": tid},
        )
        await real_bind(session, tid, **kwargs)

    monkeypatch.setattr(trial_expiry, "bind_tenant", bind_after_the_tenant_moved)

    await lock_expired_trials(now=NOW)

    assert await _state(db, tenant_id) == ("suspended", False)
