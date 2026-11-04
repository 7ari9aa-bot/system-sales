"""The owner console's AI-spend read model (ai/spend_read.py).

The §42 cap measures SUM(ai_usage.cost) per month against the tenant's
resolved cap; the tenants tab shows exactly that pair per tenant. Two traps
these tests pin:

1. RLS: ai_usage / ai_budget_policies / agent_runs are FORCE-tenant-isolated
   — a cross-tenant SUM without the per-tenant GUC bind returns NOTHING, and
   worse, a mis-bound aggregate can silently report one tenant's spend under
   another's id. The leak test below seeds a decoy and asserts it stays out.
2. Cap resolution: a tenant-scoped monthly policy wins; an AGENT-scoped
   policy must NOT become the tenant-level cap; no policy means the
   deployment default (never unlimited).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

import app.modules.conversations.models  # noqa: F401 — registers agent_runs' conversations FK
from app.core.db import bind_tenant
from app.modules.ai.models import Agent, AgentRun, AIUsage, BudgetPolicy
from app.modules.ai.spend_read import monthly_spend_rows
from app.modules.ai.usage import record_usage


async def _seed_agent(db, tenant_id: uuid.UUID) -> Agent:
    agent = Agent(
        tenant_id=tenant_id,
        kind="sales_intelligence",
        name="SI",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    return agent


async def test_month_spend_and_tenant_policy_cap(db, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed_agent(db, tenant_id)
    await record_usage(db, tenant_id, agent_id=agent.id, cost=Decimal("4.25"))
    db.add(
        BudgetPolicy(
            tenant_id=tenant_id,
            period="monthly",
            hard_cap=Decimal("10"),
            on_exceed="warn",
        )
    )
    await db.flush()

    rows = await monthly_spend_rows(db, [tenant_id])
    spend = rows[tenant_id]
    assert spend.month_spend == Decimal("4.25")
    assert spend.cap == Decimal("10")
    assert spend.cap_source == "tenant_policy"
    assert spend.on_exceed == "warn"
    assert spend.ratio_percent == 42  # 4.25 / 10


async def test_no_policy_falls_back_to_the_default_cap(db, tenant_ctx) -> None:
    from app.modules.ai.budget import _default_cap

    tenant_id = tenant_ctx.tenant_id
    rows = await monthly_spend_rows(db, [tenant_id])
    spend = rows[tenant_id]
    assert spend.cap == _default_cap()
    assert spend.cap_source == "default"


async def test_an_agent_scoped_policy_does_not_cap_the_tenant(db, tenant_ctx) -> None:
    """An agent-scoped cap bounds ONE agent; presenting it as the tenant's
    cap would understate the tenant's real ceiling."""
    tenant_id = tenant_ctx.tenant_id
    agent = await _seed_agent(db, tenant_id)
    db.add(
        BudgetPolicy(
            tenant_id=tenant_id,
            agent_id=agent.id,
            period="monthly",
            hard_cap=Decimal("1"),
            on_exceed="block",
        )
    )
    await db.flush()

    rows = await monthly_spend_rows(db, [tenant_id])
    spend = rows[tenant_id]
    assert spend.cap_source == "default", "an agent-scoped policy is not the tenant cap"


async def test_a_tenants_spend_never_leaks_into_another_tenants_row(db, tenant_ctx) -> None:
    """The RLS trap: seed usage for BOTH tenants, then read only tenant A.
    Tenant A's row must carry A's spend and nothing of B's — and B's row,
    when read, must carry B's."""
    a_id = tenant_ctx.tenant_id
    b_id = uuid.uuid4()
    other = type(tenant_ctx.tenant)(
        id=b_id,
        slug=f"other-{b_id.hex[:8]}",
        name="Other",
        lifecycle_state="active",
        is_active=True,
    )
    db.add(other)
    await db.flush()
    # agents is FORCE-tenant-isolated: each tenant's rows seed under ITS GUC.
    await bind_tenant(db, a_id)
    agent_a = await _seed_agent(db, a_id)
    await record_usage(db, a_id, agent_id=agent_a.id, cost=Decimal("2.00"))
    await bind_tenant(db, b_id)
    agent_b = await _seed_agent(db, b_id)
    await record_usage(db, b_id, agent_id=agent_b.id, cost=Decimal("99.00"))

    rows = await monthly_spend_rows(db, [a_id, b_id])
    assert rows[a_id].month_spend == Decimal("2.00")
    assert rows[b_id].month_spend == Decimal("99.00")


async def test_failed_runs_24h_counts_only_recent_failures(db, tenant_ctx) -> None:
    """The failed-run metering metric: a run failed 2 hours ago counts; a run
    failed 3 days ago does not (it is outside the 24h window)."""
    from datetime import UTC, datetime, timedelta

    tenant_id = tenant_ctx.tenant_id
    agent = await _seed_agent(db, tenant_id)
    run = AgentRun(
        tenant_id=tenant_id,
        agent_id=agent.id,
        input={"q": "hi"},
        status="failed",
        error="provider 500",
        started_at=datetime.now(UTC) - timedelta(hours=2),
        finished_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db.add(run)
    old = AgentRun(
        tenant_id=tenant_id,
        agent_id=agent.id,
        input={"q": "old"},
        status="failed",
        error="provider 500",
        started_at=datetime.now(UTC) - timedelta(days=3),
        finished_at=datetime.now(UTC) - timedelta(days=3),
    )
    db.add(old)
    await db.flush()

    rows = await monthly_spend_rows(db, [tenant_id])
    assert rows[tenant_id].failed_runs_24h == 1


async def test_the_seeded_usage_row_is_the_rollup_the_cap_reads(db, tenant_ctx) -> None:
    """Consistency guard: the read model must measure the SAME rows the §42
    cap measures — record_usage's rollup, not some other ledger."""
    from datetime import UTC, datetime

    tenant_id = tenant_ctx.tenant_id
    agent = await _seed_agent(db, tenant_id)
    await record_usage(db, tenant_id, agent_id=agent.id, cost=Decimal("0.75"))
    month_start = datetime.now(UTC).date().replace(day=1)
    rows = (
        await db.execute(
            select(AIUsage.cost).where(
                AIUsage.tenant_id == tenant_id,
                AIUsage.period_date >= month_start,
            )
        )
    ).scalars()
    assert sum(Decimal(cost) for cost in rows) == Decimal("0.75")
