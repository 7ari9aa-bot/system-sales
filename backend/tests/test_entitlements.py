"""Spec §165 — entitlements are enforced centrally, and fail OPEN by default.

The enforcement is wired into four real flows (AI auto-reply, channel creation,
invitations, campaigns). These tests pin the property that makes that safe to
ship: a tenant with no plan limits is unrestricted, so switching enforcement on
cannot break an existing tenant. Only an explicit limit is enforced.

They also pin the two defects that made the seat and channel limits decorative
(review N-01):

* `can()` passed the CAPABILITY name straight through as the entitlement
  FEATURE name. Capabilities are `CanAddUser`; plan features are `max_users`.
  No row ever matched, so every check returned True and a seat limit on a plan
  had no effect at all.
* seat usage was read from `UsageRecord`, and nothing ever writes a usage row
  for seats. Even with a matching name the counter read 0 forever.

Database-backed (a subscription + entitlement row are needed), so they skip
locally and run in CI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.errors import RateLimitExceededError
from app.modules.billing.models import Entitlement, Plan, Subscription
from app.modules.billing.service import (
    _CAPABILITY_FEATURE,
    _DERIVED_USAGE,
    BillingService,
    EntitlementService,
)
from app.modules.identity.models import TenantUser

# fd2026100410 Finding 2: plans is SELECT-only for the runtime role, so the
# fixtures plant plan rows through the admin DSN and this registry tracks
# them for removal — the per-test rollback cannot cover another connection.
_PLANTED_PLAN_IDS: list[str] = []


def _admin_sessionmaker():
    settings = get_settings()
    if not settings.database_url_admin:
        pytest.skip("planting plans requires DATABASE_URL_ADMIN (the admin DSN)")
    eng = create_async_engine(
        settings.database_url_admin,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0},
    )
    return eng, async_sessionmaker(eng, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _cleanup_planted_plans():
    yield
    if not _PLANTED_PLAN_IDS:
        return
    ids, _PLANTED_PLAN_IDS[:] = list(_PLANTED_PLAN_IDS), []
    eng, factory = _admin_sessionmaker()
    try:
        async with factory() as s, s.begin():
            await s.execute(
                sa_text("DELETE FROM plans WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": ids},
            )
    finally:
        await eng.dispose()


async def _subscription(db, tenant_id, *, features: dict | None = None) -> Subscription:
    eng, factory = _admin_sessionmaker()
    plan = Plan(
        code=f"plan-{uuid.uuid4().hex[:8]}",
        name="Test Plan",
        price="0",
        interval="month",
        features=features or {},
    )
    try:
        async with factory() as s, s.begin():
            s.add(plan)
            await s.flush()
    finally:
        await eng.dispose()
    _PLANTED_PLAN_IDS.append(str(plan.id))
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


async def _entitle(db, tenant_id, subscription, feature: str, **kw) -> Entitlement:
    row = Entitlement(
        tenant_id=tenant_id, subscription_id=subscription.id, feature=feature, **kw
    )
    db.add(row)
    await db.flush()
    return row


# ------------------------------------------------------- fail-open default --


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


async def test_unmapped_capability_stays_unrestricted(db, tenant_ctx):
    """`CanSendCampaign` has no plan feature behind it, so it stays open.

    Documented behaviour, and the reason the map has to be explicit rather than
    derived: an unmapped capability is indistinguishable from a mis-typed one.
    """
    assert "CanSendCampaign" not in _CAPABILITY_FEATURE
    await _subscription(db, tenant_ctx.tenant_id)
    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanSendCampaign") is True


def test_the_capability_map_points_at_real_plan_features() -> None:
    """A typo here would silently disable the gate again."""
    assert _CAPABILITY_FEATURE["CanAddUser"] == "max_users"
    assert _CAPABILITY_FEATURE["CanUseAI"] == "ai_agents"
    assert _CAPABILITY_FEATURE["CanCreateChannel"] == "channels"
    # The seeded plans use exactly these feature names.
    assert set(_CAPABILITY_FEATURE.values()) <= {
        "max_users",
        "ai_agents",
        "channels",
        "custom",
    }


def test_derived_usage_covers_the_counted_features() -> None:
    assert _DERIVED_USAGE["max_users"] == "tenant_users"
    assert _DERIVED_USAGE["seats"] == "tenant_users"


# ------------------------------------------------ explicit limits enforced --


async def test_an_explicit_limit_is_enforced(db, tenant_ctx):
    """Uses a MAPPED capability: `CanUseAI` -> the `ai_agents` plan feature."""
    subscription = await _subscription(db, tenant_ctx.tenant_id)
    await _entitle(db, tenant_ctx.tenant_id, subscription, "ai_agents", limit_value=0)

    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanUseAI") is False
    with pytest.raises(RateLimitExceededError):
        await EntitlementService.ensure(db, tenant_ctx.tenant_id, "CanUseAI")


async def test_an_unlimited_entitlement_is_not_limited(db, tenant_ctx):
    subscription = await _subscription(db, tenant_ctx.tenant_id)
    await _entitle(db, tenant_ctx.tenant_id, subscription, "ai_agents", is_unlimited=True)

    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanUseAI") is True


async def test_a_deactivated_tenant_loses_every_capability(db, tenant_ctx):
    """Tenant status is checked before any plan logic."""
    from app.modules.identity.models import Tenant

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    tenant.is_active = False
    await db.flush()

    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanUseAI") is False


# ------------------------------------------------------------- seat limits --


async def test_seat_usage_counts_memberships_not_usage_records(db, tenant_ctx):
    """The counter is the number of rows in tenant_users.

    Reading `UsageRecord` reported 0 forever because nothing writes a usage row
    for seats — a state, not a per-period quantity.
    """
    expected = len(
        (
            await db.execute(
                select(TenantUser).where(TenantUser.tenant_id == tenant_ctx.tenant_id)
            )
        ).scalars().all()
    )
    assert expected >= 1  # the owner from the fixture
    assert await BillingService.used_this_period(
        db, tenant_ctx.tenant_id, "max_users"
    ) == expected


async def test_the_seat_limit_actually_blocks(db, tenant_ctx):
    """One member exists; a plan limit of 1 means the next seat is refused."""
    subscription = await _subscription(db, tenant_ctx.tenant_id)
    await _entitle(db, tenant_ctx.tenant_id, subscription, "max_users", limit_value=1)

    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanAddUser") is False
    with pytest.raises(RateLimitExceededError):
        await EntitlementService.ensure(db, tenant_ctx.tenant_id, "CanAddUser")


async def test_a_seat_limit_above_current_usage_allows_the_next_seat(
    db, tenant_ctx
):
    subscription = await _subscription(db, tenant_ctx.tenant_id)
    await _entitle(db, tenant_ctx.tenant_id, subscription, "max_users", limit_value=5)

    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanAddUser") is True
    await EntitlementService.ensure(db, tenant_ctx.tenant_id, "CanAddUser")


# --------------------------------------------------------- channel allowlist --


async def test_channel_allowlist_permits_listed_channels(db, tenant_ctx):
    await _subscription(
        db, tenant_ctx.tenant_id, features={"channels": ["whatsapp", "webchat"]}
    )

    assert await EntitlementService.channel_allowed(
        db, tenant_ctx.tenant_id, "whatsapp"
    )
    assert await EntitlementService.channel_allowed(db, tenant_ctx.tenant_id, "webchat")


async def test_channel_allowlist_refuses_unlisted_channels(db, tenant_ctx):
    await _subscription(
        db, tenant_ctx.tenant_id, features={"channels": ["whatsapp", "webchat"]}
    )

    assert not await EntitlementService.channel_allowed(
        db, tenant_ctx.tenant_id, "telegram"
    )
    with pytest.raises(RateLimitExceededError):
        await EntitlementService.ensure_channel_allowed(
            db, tenant_ctx.tenant_id, "telegram"
        )


async def test_wildcard_channels_allows_everything(db, tenant_ctx):
    await _subscription(db, tenant_ctx.tenant_id, features={"channels": "*"})

    for channel in ("whatsapp", "telegram", "anything-at-all"):
        assert await EntitlementService.channel_allowed(
            db, tenant_ctx.tenant_id, channel
        ), channel


async def test_no_subscription_leaves_channels_unrestricted(db, tenant_ctx):
    assert await EntitlementService.channel_allowed(db, tenant_ctx.tenant_id, "telegram")


async def test_an_empty_channel_list_blocks_every_channel(db, tenant_ctx):
    """`CanCreateChannel` with no channel named = "may they add any channel"."""
    await _subscription(db, tenant_ctx.tenant_id, features={"channels": []})

    assert not await EntitlementService.can(
        db, tenant_ctx.tenant_id, "CanCreateChannel"
    )
    assert not await EntitlementService.channel_allowed(
        db, tenant_ctx.tenant_id, "whatsapp"
    )


async def test_can_create_channel_is_true_when_the_plan_lists_one(db, tenant_ctx):
    await _subscription(db, tenant_ctx.tenant_id, features={"channels": ["whatsapp"]})
    assert await EntitlementService.can(db, tenant_ctx.tenant_id, "CanCreateChannel")
