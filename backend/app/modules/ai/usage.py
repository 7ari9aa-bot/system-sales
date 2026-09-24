"""AI usage rollups — daily per-bucket counters in ai_usage.

Atomic upsert (INSERT ... ON CONFLICT DO UPDATE): the previous
SELECT FOR UPDATE + insert pattern could not lock a row that does not exist
yet, so two concurrent first-runs-per-day collided on the unique constraint
and the IntegrityError rolled back the ENTIRE agent run (reply included).
All writes happen inside the caller's transaction (the service never commits).

Which key an upsert may target is decided by the BUCKET, not by the caller's
convenience, and the two buckets do not share a target:

* a real agent id arbitrates on ``uq_ai_usage_tenant_period_agent`` — the natural
  key ``(tenant_id, period_date, agent_id)``, which converges because the bound
  ``agent_id`` is non-NULL.
* ``PLATFORM_BUCKET`` (genuinely agent-less spend: inbound voice transcription,
  booked before any agent is chosen) has NO usable natural key. A plain UNIQUE
  compares NULLs as DISTINCT, so ``(tenant_id, period_date, NULL)`` matches
  nothing that was ever stored, the DO UPDATE branch is unreachable, and each
  write inserts a fresh row — a daily rollup quietly degenerating into one row
  per call. So this bucket carries a stable ROW IDENTITY derived from its key
  (:func:`bucket_row_id`) and arbitrates on the primary key
  ``(id, period_date)``, whose columns are both NOT NULL by definition. That is a
  database-enforced converge with no application-side read-modify-write (which is
  the racy pattern this module already rejected once, above) and no invented agent
  row (``ai_usage.agent_id`` is a real FK, so a synthetic id would not insert, and
  ``ON DELETE SET NULL`` would quietly re-NULL it and reopen the hole anyway).
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import AIUsage

#: Namespace for bucket identities. Named by URL like every other stable id this
#: codebase derives (`app/core/secrets.py`), so the derivation is reproducible
#: from the source alone and cannot be confused with another uuid5 family.
_BUCKET_NAMESPACE: Final = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://salesos.local/ai_usage/bucket"
)


class PlatformBucket(enum.Enum):
    """The agent-less spend bucket — a documented sentinel, never an agent id.

    Call sites receive ``PLATFORM_BUCKET`` (its member) rather than writing
    ``None``: the value says "this AI cost belongs to no agent", which is a
    decision, whereas an omitted ``agent_id`` is indistinguishable from a bug.
    """

    TOKEN = "platform"

    def __repr__(self) -> str:  # pragma: no cover - trace output only
        return "<PLATFORM_BUCKET>"


#: The one value of `PlatformBucket` anything may pass as `record_usage`'s bucket.
PLATFORM_BUCKET: Final = PlatformBucket.TOKEN

#: What a caller may name as its bucket: a persisted agent, or the platform.
AgentBucket = uuid.UUID | PlatformBucket


def bucket_row_id(
    tenant_id: uuid.UUID, period_date: date, agent_id: uuid.UUID | None
) -> uuid.UUID:
    """The rollup row a (tenant, day, bucket) owns — derived, never random.

    Injective over the bucket: the agent-less key uses the literal ``platform``
    token where an agent key uses its uuid text, so no agent id can address the
    platform row, and neither tenant nor day can be swapped for the other. Random
    per-call ids are exactly what breaks an upsert, so determinism here IS the
    convergence property (pinned by tests/test_ai_usage_bucket_key.py).
    """
    bucket = PLATFORM_BUCKET.value if agent_id is None else str(agent_id)
    key = f"{tenant_id}|{period_date.isoformat()}|{bucket}"
    return uuid.uuid5(_BUCKET_NAMESPACE, key)


async def record_usage(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    agent_id: AgentBucket,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost: Decimal = Decimal("0"),
) -> None:
    """Increment today's (tenant, bucket) usage row, creating it if needed.

    ``agent_id`` is required and has no default on purpose: every caller must
    state which bucket it books. Pass a persisted ``agents.id`` for agent work, or
    :data:`PLATFORM_BUCKET` for spend no agent caused.

    ``cost`` is a Decimal because ``ai_usage.cost`` is ``AI_COST =
    Numeric(18,8)``: sub-cent money, widened off ``Numeric(14,2)`` precisely so a
    call costing 0.001 did not round to 0.00 and make the §42 hard cap
    unreachable. A float parameter would put that rounding back one frame above
    the INSERT, so the port takes what the column holds and no caller converts
    on its behalf — the same shape ``BillingService.record_usage`` uses for its
    Decimal quantity.
    """
    if agent_id is None:
        raise TypeError(
            "record_usage: agent_id is required — pass a persisted agent id, or "
            "PLATFORM_BUCKET for genuinely agent-less spend. NULL is not a bucket: "
            "it cannot be arbitrated by a unique key and fragments the rollup."
        )
    # UTC everywhere: the budget month window (gateway._month_spend) buckets
    # by UTC — mixing server-local dates made usage roll into the wrong day.
    period_date = datetime.now(UTC).date()
    is_platform = agent_id is PLATFORM_BUCKET
    # The NULL the FK and the rollup both tolerate — the bucket sentinel is a
    # Python-side value and is deliberately NOT stored as an agent id.
    bound_agent_id = None if is_platform else agent_id

    values = {
        "tenant_id": tenant_id,
        "period_date": period_date,
        "agent_id": bound_agent_id,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": cost,
        "model_calls": 1,
    }
    if is_platform:
        # The natural key cannot arbitrate a NULL agent_id, so the agent-less
        # bucket is addressed by the identity of its own row.
        values["id"] = bucket_row_id(tenant_id, period_date, None)
        arbiter: dict[str, object] = {"index_elements": ["id", "period_date"]}
    else:
        arbiter = {"index_elements": ["tenant_id", "period_date", "agent_id"]}

    stmt = (
        pg_insert(AIUsage)
        .values(**values)
        .on_conflict_do_update(
            **arbiter,
            set_={
                "tokens_in": AIUsage.tokens_in + tokens_in,
                "tokens_out": AIUsage.tokens_out + tokens_out,
                "cost": AIUsage.cost + cost,
                "model_calls": AIUsage.model_calls + 1,
            },
        )
    )
    await session.execute(stmt)
