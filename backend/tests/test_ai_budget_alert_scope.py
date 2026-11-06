"""Budget alert scope — an agent's threshold alert must never eat the
tenant's, and the reverse (logic-12).

The tenant-wide cap and a per-agent cap are two different ceilings that can
cross the SAME threshold in the SAME month. The threshold notification's
dedup key used to be built from tenant + period + threshold with no scope,
so whichever cap crossed first swallowed the other's alert for the whole
period — worst case the agent's alert ate the tenant cap's warning, the one
the owners must hear before the AI stops answering customers.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.model_registry  # noqa: F401  (loads every model so foreign keys resolve alone)
import app.modules.ai.budget as budget_module
from app.modules.ai.budget import reserve_budget
from app.modules.ai.models import Agent, BudgetPolicy
from app.modules.notifications.models import Notification


def _spend(value: Decimal):
    async def _inner(_session, _tenant_id, *, agent_id=None):
        return value

    return _inner


async def _scoped_caps(db: AsyncSession, tenant_id, agent_id) -> None:
    """A tenant-wide cap of 10 and an agent cap of 1, both live this period."""
    db.add(
        BudgetPolicy(
            tenant_id=tenant_id,
            period="monthly",
            hard_cap=Decimal("10"),
            on_exceed="block",
        )
    )
    db.add(
        BudgetPolicy(
            tenant_id=tenant_id,
            agent_id=agent_id,
            period="monthly",
            hard_cap=Decimal("1"),
            on_exceed="block",
        )
    )
    await db.flush()


async def _threshold_alerts(db: AsyncSession, tenant_id) -> list[Notification]:
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


async def test_an_agent_alert_never_swallows_the_tenant_alert(
    db: AsyncSession, tenant_ctx, monkeypatch
):
    """Both caps cross 90% of their own ceiling in one month: two alerts."""
    tenant_id = tenant_ctx.tenant_id
    agent = Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="Scoped",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    await _scoped_caps(db, tenant_id, agent.id)

    async def _spend_by_scope(_session, _tid, *, agent_id=None):
        return Decimal("9.5") if agent_id is None else Decimal("0.95")

    monkeypatch.setattr(budget_module, "_month_spend", _spend_by_scope)
    monkeypatch.setattr(budget_module, "_reserved_spend", _spend(Decimal("0")))

    # Tenant scope: 9.5 of its 10 cap — 95%, threshold 90.
    tenant_reservation = await reserve_budget(db, tenant_id, estimated_cost=Decimal("0.01"))
    # Agent scope: 0.95 of its own 1 cap — the SAME threshold, a DIFFERENT cap.
    agent_reservation = await reserve_budget(
        db, tenant_id, agent_id=agent.id, estimated_cost=Decimal("0.01")
    )
    assert tenant_reservation is not None, "the tenant reserve under its own cap was refused"
    assert agent_reservation is not None, "the agent reserve under its own cap was refused"

    alerts = await _threshold_alerts(db, tenant_id)
    assert len(alerts) == 2, (
        f"one threshold alert swallowed the other — {len(alerts)} alert(s) for "
        "two different caps crossing the same threshold in one period"
    )


async def test_the_same_scope_still_alerts_once_per_period(
    db: AsyncSession, tenant_ctx, monkeypatch
):
    """The scope in the key distinguishes CAPS, not calls: repeated reserves
    under the same cap still produce exactly one alert for the period."""
    tenant_id = tenant_ctx.tenant_id
    agent = Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="Solo",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    await _scoped_caps(db, tenant_id, agent.id)
    monkeypatch.setattr(budget_module, "_month_spend", _spend(Decimal("0.95")))
    monkeypatch.setattr(budget_module, "_reserved_spend", _spend(Decimal("0")))

    for _ in range(2):
        await reserve_budget(db, tenant_id, agent_id=agent.id, estimated_cost=Decimal("0.01"))

    alerts = await _threshold_alerts(db, tenant_id)
    assert len(alerts) == 1, f"dedup failed — {len(alerts)} alerts for one cap in one period"
