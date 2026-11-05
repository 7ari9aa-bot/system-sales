"""Read-only tenant AI-spend projection for cross-tenant admin surfaces.

A READ MODEL, deliberately separate from ``budget.py``: that module owns the
§42 reserve/settle machinery and alert dispatch; THIS module answers one
question for the owner console — "how much has each tenant spent THIS MONTH
against ITS cap, and how hot is it running".

RLS shape (the part that makes a naive implementation silently wrong):
``ai_usage``, ``ai_budget_policies`` and ``agent_runs`` are all
FORCE-tenant-isolated, so a cross-tenant SUM from a platform session returns
nothing without the GUC. Every per-tenant aggregate here runs under ITS OWN
``bind_tenant`` — the established pattern for platform surfaces
(owner.py's ``_tenant_integrations`` does the same).

Cap resolution mirrors the runtime's ``_resolve_cap`` for the TENANT scope:
a tenant-scoped monthly policy wins; an AGENT-scoped policy does not cap the
tenant as a whole and is deliberately ignored here; no policy at all means
the deployment default — never "unlimited" (§42 fail-closed rule).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.console_spending import register_console_spend_provider
from app.core.db import bind_tenant
from app.modules.ai.models import AgentRun, AIUsage, BudgetPolicy


@dataclass(frozen=True, slots=True)
class TenantSpend:
    """One tenant's month-to-date spend against its resolved cap."""

    tenant_id: uuid.UUID
    month_spend: Decimal
    cap: Decimal
    cap_source: str  # "tenant_policy" | "default"
    on_exceed: str  # block | warn | fallback (the policy's own action)
    failed_runs_24h: int
    # Two-tier budget (fe2026110504): the soft tier and the durable stop state.
    soft_cap: Decimal | None = None
    hard_stopped: bool = False

    @property
    def ratio_percent(self) -> int:
        """Spend as a percent of cap — 0 when the cap is zero (nothing owed)."""
        if self.cap <= 0:
            return 0
        return int((self.month_spend / self.cap) * 100)


async def monthly_spend_rows(
    session: AsyncSession, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, TenantSpend]:
    """Spend-vs-cap for the given tenants, keyed by tenant id.

    N+1 by design: each tenant's aggregate MUST run under its own RLS GUC,
    and a loop of cheap indexed aggregates for a console page (≤ 100 tenants,
    a handful of rows each) is the honest price of the isolation the policy
    enforces. The failed-run count is the §42 metering fix's own metric —
    it is the number the hard cap now correctly counts.
    """
    out: dict[uuid.UUID, TenantSpend] = {}
    now = datetime.now(UTC)
    month_start = now.date().replace(day=1)
    since24 = now - timedelta(hours=24)
    for tenant_id in tenant_ids:
        await bind_tenant(session, tenant_id)
        spend = (
            await session.execute(
                select(func.coalesce(func.sum(AIUsage.cost), 0)).where(
                    AIUsage.tenant_id == tenant_id,
                    AIUsage.period_date >= month_start,
                )
            )
        ).scalar_one()
        policies = (
            (
                await session.execute(
                    select(BudgetPolicy).where(
                        BudgetPolicy.tenant_id == tenant_id,
                        BudgetPolicy.period == "monthly",
                        BudgetPolicy.agent_id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if policies:
            cap = Decimal(policies[0].hard_cap)
            on_exceed = policies[0].on_exceed
            cap_source = "tenant_policy"
            soft_cap = Decimal(policies[0].soft_cap) if policies[0].soft_cap is not None else None
            hard_stopped = policies[0].hard_stopped_at is not None
        else:
            from app.modules.ai.budget import _default_cap

            cap = _default_cap()
            on_exceed = "block"
            cap_source = "default"
            soft_cap = None
            hard_stopped = False
        failed_runs = (
            await session.execute(
                select(func.count(AgentRun.id)).where(
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.status == "failed",
                    AgentRun.finished_at >= since24,
                )
            )
        ).scalar_one()
        row = TenantSpend(
            tenant_id=tenant_id,
            month_spend=Decimal(spend or 0),
            cap=cap,
            cap_source=cap_source,
            on_exceed=on_exceed,
            failed_runs_24h=int(failed_runs or 0),
            soft_cap=soft_cap,
            hard_stopped=hard_stopped,
        )
        out[tenant_id] = row
    return out


async def console_spend_rows(
    session: AsyncSession, tenant_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """The registry-facing shape: Decimal-STRING money (ADR-053) per tenant."""
    rows = await monthly_spend_rows(session, tenant_ids)
    return {
        tenant_id: {
            "month_spend": str(row.month_spend),
            "cap": str(row.cap),
            "cap_source": row.cap_source,
            "on_exceed": row.on_exceed,
            "failed_runs_24h": row.failed_runs_24h,
            "soft_cap": str(row.soft_cap) if row.soft_cap is not None else None,
            "hard_stopped": row.hard_stopped,
        }
        for tenant_id, row in rows.items()
    }


# Self-registration: importing the ai module wires the console surface (the
# dependency inversion that keeps platform -> ai out of the module graph).
# Self-registration: importing the ai module wires the console surface (the
# dependency inversion that keeps platform -> ai out of the module graph).
register_console_spend_provider(console_spend_rows)
