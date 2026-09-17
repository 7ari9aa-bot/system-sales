"""AI usage rollups — daily per-agent counters in ai_usage.

Row-locked upsert: SELECT ... FOR UPDATE, then update or insert. All writes
happen inside the caller's transaction (the service never commits).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import AIUsage


async def record_usage(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost: float = 0.0,
) -> AIUsage:
    """Increment today's (tenant, agent) usage row, creating it if needed."""
    period_date = date.today()
    row = (
        await session.execute(
            select(AIUsage)
            .where(
                AIUsage.tenant_id == tenant_id,
                AIUsage.period_date == period_date,
                AIUsage.agent_id == agent_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if row is None:
        row = AIUsage(
            tenant_id=tenant_id,
            period_date=period_date,
            agent_id=agent_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            model_calls=1,
        )
        session.add(row)
    else:
        row.tokens_in += tokens_in
        row.tokens_out += tokens_out
        row.cost = float(row.cost) + cost
        row.model_calls += 1
    await session.flush()
    return row
