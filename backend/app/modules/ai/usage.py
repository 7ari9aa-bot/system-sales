"""AI usage rollups — daily per-agent counters in ai_usage.

Atomic upsert (INSERT ... ON CONFLICT DO UPDATE): the previous
SELECT FOR UPDATE + insert pattern could not lock a row that does not exist
yet, so two concurrent first-runs-per-day collided on the unique constraint
and the IntegrityError rolled back the ENTIRE agent run (reply included).
All writes happen inside the caller's transaction (the service never commits).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
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
) -> None:
    """Increment today's (tenant, agent) usage row, creating it if needed."""
    # UTC everywhere: the budget month window (gateway._month_spend) buckets
    # by UTC — mixing server-local dates made usage roll into the wrong day.
    period_date = datetime.now(UTC).date()
    stmt = (
        pg_insert(AIUsage)
        .values(
            tenant_id=tenant_id,
            period_date=period_date,
            agent_id=agent_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            model_calls=1,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "period_date", "agent_id"],
            set_={
                "tokens_in": AIUsage.tokens_in + tokens_in,
                "tokens_out": AIUsage.tokens_out + tokens_out,
                "cost": AIUsage.cost + cost,
                "model_calls": AIUsage.model_calls + 1,
            },
        )
    )
    await session.execute(stmt)
