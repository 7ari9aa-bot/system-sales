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
from decimal import Decimal

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
    cost: Decimal = Decimal("0"),
) -> None:
    """Increment today's (tenant, agent) usage row, creating it if needed.

    ``cost`` is a Decimal because ``ai_usage.cost`` is ``AI_COST =
    Numeric(18,8)``: sub-cent money, widened off ``Numeric(14,2)`` precisely so a
    call costing 0.001 did not round to 0.00 and make the §42 hard cap
    unreachable. A float parameter would put that rounding back one frame above
    the INSERT, so the port takes what the column holds and no caller converts
    on its behalf — the same shape ``BillingService.record_usage`` uses for its
    Decimal quantity.
    """
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
