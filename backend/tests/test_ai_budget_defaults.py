"""§42 AI budget governance — a default cap, and the thresholds that never fired.

Two findings from the audit, one of which was subtler than reported:

1. The report said `reserve_budget` returns None (no limit) when a tenant has no
   policy. That was not quite right — `_resolve_cap` already fell back to a
   constant. The real defect was that the fallback was a **hard-coded module
   constant**, so a deployment could not change the ceiling without a code
   change, and "no policy" was indistinguishable from "the default policy".

2. `BudgetPolicy.warning_threshold` existed on the model and **nothing ever read
   it**, so no alert was raised at ANY percentage. A tenant could reach the hard
   cap — and have the AI stop answering customers — with no warning at all.
   §42 requires alerts at 50/80/90/100%.

These tests pin both.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.model_registry  # noqa: F401  (loads every model so foreign keys resolve alone)
from app.core.errors import RateLimitExceededError
from app.modules.ai.gateway import (
    BUDGET_ALERT_THRESHOLDS,
    MONTHLY_BUDGET_CAP,
    _default_cap,
    _raise_budget_alerts,
    _resolve_cap,
    reserve_budget,
)
from app.modules.notifications.models import Notification


class _Policy:
    """A stand-in for a BudgetPolicy row (no DB needed)."""

    def __init__(self, cap, on_exceed="block", agent_id=None):
        self.hard_cap = Decimal(str(cap))
        self.on_exceed = on_exceed
        self.agent_id = agent_id


# ------------------------------------------------------- the default cap ---


def test_no_policy_still_gets_a_cap() -> None:
    """ "No policy" must never mean "no limit"."""
    cap, on_exceed, _agent_scoped = _resolve_cap([], None)
    assert cap > 0, "a tenant with no budget policy is uncapped"
    assert on_exceed == "block"


def test_the_default_cap_is_positive_and_matches_the_setting() -> None:
    from app.core.config import get_settings

    cap = _default_cap()
    assert cap == Decimal(str(get_settings().ai_monthly_budget_cap_default))
    assert cap > 0


def test_the_default_cap_falls_back_when_the_setting_is_unusable() -> None:
    """A malformed setting must not silently become an unlimited budget."""
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.ai_monthly_budget_cap_default
    try:
        settings.ai_monthly_budget_cap_default = "not-a-number"  # type: ignore[assignment]
        assert _default_cap() == Decimal(str(MONTHLY_BUDGET_CAP))
    finally:
        settings.ai_monthly_budget_cap_default = original


def test_a_tenant_policy_overrides_the_default() -> None:
    cap, on_exceed, agent_scoped = _resolve_cap([_Policy(12, "warn")], None)
    assert cap == Decimal("12")
    assert on_exceed == "warn"
    assert agent_scoped is False


def test_another_agents_policy_is_ignored() -> None:
    cap, _, agent_scoped = _resolve_cap([_Policy(7, agent_id=uuid.uuid4())], uuid.uuid4())
    assert cap == _default_cap(), "an unrelated agent's cap was applied"
    assert agent_scoped is False


def test_an_agent_policy_reports_its_scope_so_the_spend_matches() -> None:
    """The cap scope IS the measurement scope: a per-agent ceiling judged
    against tenant-wide spend blocked an agent whose own spend was a fraction
    of its own ceiling — the B2 bug the third element exists to prevent."""
    agent_id = uuid.uuid4()
    cap, _, agent_scoped = _resolve_cap([_Policy(9, agent_id=agent_id)], agent_id)
    assert cap == Decimal("9")
    assert agent_scoped is True


def test_the_alert_thresholds_are_the_spec_set() -> None:
    assert set(BUDGET_ALERT_THRESHOLDS) == {50, 80, 90, 100}


# ------------------------------------------------- the alerts actually fire --


async def _owner_notifications(db: AsyncSession, tenant_id) -> list[Notification]:
    return list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.kind == "ai_budget_threshold",
                )
            )
        )
        .scalars()
        .all()
    )


async def test_crossing_a_threshold_notifies_the_owner(db: AsyncSession, tenant_ctx):
    """The whole point of §42: tell someone before the cap stops the AI."""
    await _raise_budget_alerts(
        db, tenant_ctx.tenant_id, cap=Decimal("100"), committed=Decimal("85")
    )

    rows = await _owner_notifications(db, tenant_ctx.tenant_id)
    assert len(rows) == 1, "no alert was raised for a tenant at 85% of its cap"
    assert rows[0].payload.get("threshold") == 80


async def test_below_the_first_threshold_is_silent(db: AsyncSession, tenant_ctx):
    await _raise_budget_alerts(
        db, tenant_ctx.tenant_id, cap=Decimal("100"), committed=Decimal("49")
    )
    assert await _owner_notifications(db, tenant_ctx.tenant_id) == []


async def test_a_threshold_alerts_once_per_period(db: AsyncSession, tenant_ctx):
    """A reserve happens on every AI call; the alert must not."""
    for _ in range(4):
        await _raise_budget_alerts(
            db, tenant_ctx.tenant_id, cap=Decimal("100"), committed=Decimal("85")
        )

    rows = await _owner_notifications(db, tenant_ctx.tenant_id)
    assert len(rows) == 1, f"expected one alert per threshold per month, got {len(rows)}"


async def test_crossing_a_higher_threshold_alerts_again(db: AsyncSession, tenant_ctx):
    await _raise_budget_alerts(
        db, tenant_ctx.tenant_id, cap=Decimal("100"), committed=Decimal("55")
    )
    await _raise_budget_alerts(
        db, tenant_ctx.tenant_id, cap=Decimal("100"), committed=Decimal("95")
    )

    thresholds = sorted(
        r.payload.get("threshold") for r in await _owner_notifications(db, tenant_ctx.tenant_id)
    )
    assert thresholds == [50, 90]


async def test_an_unusable_cap_raises_no_alert(db: AsyncSession, tenant_ctx):
    await _raise_budget_alerts(db, tenant_ctx.tenant_id, cap=Decimal("0"), committed=Decimal("10"))
    assert await _owner_notifications(db, tenant_ctx.tenant_id) == []


# --------------------------------------------- the cap is actually enforced --


async def test_a_tenant_with_no_policy_is_still_capped(db: AsyncSession, tenant_ctx, monkeypatch):
    """The default must actually block, not just be reported."""
    # The budget logic lives in `budget`; `gateway` only re-exports its names. Patching the
    # re-export changes nothing `reserve_budget` reads, so the patch must target `budget`.
    import app.modules.ai.budget as gateway

    monkeypatch.setattr(gateway, "_month_spend", _spend(Decimal("1000")))
    monkeypatch.setattr(gateway, "_reserved_spend", _spend(Decimal("0")))

    with pytest.raises(RateLimitExceededError):
        await reserve_budget(db, tenant_ctx.tenant_id, estimated_cost=Decimal("1"))


def _spend(value: Decimal):
    async def _inner(_session, _tenant_id, *, agent_id=None):
        return value

    return _inner


async def test_a_tenant_below_the_default_cap_can_reserve(
    db: AsyncSession, tenant_ctx, monkeypatch
):
    # The budget logic lives in `budget`; `gateway` only re-exports its names. Patching the
    # re-export changes nothing `reserve_budget` reads, so the patch must target `budget`.
    import app.modules.ai.budget as gateway

    monkeypatch.setattr(gateway, "_month_spend", _spend(Decimal("0")))
    monkeypatch.setattr(gateway, "_reserved_spend", _spend(Decimal("0")))

    reservation_id = await reserve_budget(db, tenant_ctx.tenant_id, estimated_cost=Decimal("0.01"))
    assert reservation_id is not None, "a tenant under its cap could not reserve budget"


# ------------------------------------------- the cap scope IS the spend scope --


async def test_an_agent_cap_is_judged_against_that_agents_own_spend(db: AsyncSession, tenant_ctx):
    """B2: an agent-specific ceiling used to be measured against the WHOLE
    tenant's spend — agent A got blocked because agent B spent money. The
    reservation must judge A by A's own ledger."""
    from app.modules.ai.models import Agent, BudgetPolicy
    from app.modules.ai.usage import record_usage

    tenant_id = tenant_ctx.tenant_id
    agent_a = Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="A",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    agent_b = Agent(
        tenant_id=tenant_id,
        kind="sales_intelligence",
        name="B",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    db.add_all([agent_a, agent_b])
    await db.flush()
    db.add(
        BudgetPolicy(
            tenant_id=tenant_id,
            agent_id=agent_a.id,
            period="monthly",
            hard_cap=Decimal("10"),
            on_exceed="block",
        )
    )
    await db.flush()
    # B burned 9.90 this month; A spent 0.10. Tenant-wide (10.00) sits AT the
    # cap, but A's own ledger is 0.10 of its own 10 — and the derived daily cap
    # (monthly/30 = 0.33) must judge A's day, not B's.
    await record_usage(db, tenant_id, agent_id=agent_b.id, cost=Decimal("9.90"))
    await record_usage(db, tenant_id, agent_id=agent_a.id, cost=Decimal("0.10"))

    reservation_id = await reserve_budget(
        db, tenant_id, agent_id=agent_a.id, estimated_cost=Decimal("0.10")
    )
    assert reservation_id is not None, (
        "an agent cap blocked an agent whose own spend was a fraction of its ceiling"
    )


async def test_an_agent_cap_still_blocks_when_that_agent_exceeds_it(db: AsyncSession, tenant_ctx):
    from app.modules.ai.gateway import AIBudgetExhaustedError
    from app.modules.ai.models import Agent, BudgetPolicy
    from app.modules.ai.usage import record_usage

    tenant_id = tenant_ctx.tenant_id
    agent_a = Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="Solo",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    db.add(agent_a)
    await db.flush()
    db.add(
        BudgetPolicy(
            tenant_id=tenant_id,
            agent_id=agent_a.id,
            period="monthly",
            hard_cap=Decimal("5"),
            on_exceed="block",
        )
    )
    await db.flush()
    await record_usage(db, tenant_id, agent_id=agent_a.id, cost=Decimal("4.5"))

    with pytest.raises(AIBudgetExhaustedError):
        await reserve_budget(db, tenant_id, agent_id=agent_a.id, estimated_cost=Decimal("1"))


async def test_a_tenant_cap_still_sees_every_agents_spend(db: AsyncSession, tenant_ctx):
    """The reverse direction: a tenant-level ceiling must count ALL agents —
    scoping the measurement to the caller's agent would hide the others."""
    from app.modules.ai.gateway import AIBudgetExhaustedError
    from app.modules.ai.models import Agent
    from app.modules.ai.usage import record_usage

    tenant_id = tenant_ctx.tenant_id
    agent_a = Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="Quiet",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    agent_b = Agent(
        tenant_id=tenant_id,
        kind="sales_intelligence",
        name="Loud",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    db.add_all([agent_a, agent_b])
    await db.flush()
    # No policy rows: the deployment default cap applies at tenant scope. Spend
    # the default cap through B, then A's reserve must see the tenant total.
    await record_usage(db, tenant_id, agent_id=agent_b.id, cost=_default_cap())

    with pytest.raises(AIBudgetExhaustedError):
        await reserve_budget(db, tenant_id, agent_id=agent_a.id, estimated_cost=Decimal("1"))
