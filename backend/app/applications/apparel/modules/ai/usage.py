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
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.apparel.modules.ai.models import AgentRun, AIChatMessage, AIUsage

#: Namespace for bucket identities. Named by URL like every other stable id this
#: codebase derives (`app/core/secrets.py`), so the derivation is reproducible
#: from the source alone and cannot be confused with another uuid5 family.
_BUCKET_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "https://salesos.local/ai_usage/bucket")


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


def bucket_row_id(tenant_id: uuid.UUID, period_date: date, agent_id: uuid.UUID | None) -> uuid.UUID:
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


# --------------------------------------------------------------------------
# A spoken turn's spend
# --------------------------------------------------------------------------
#
# A voice turn used to cost money that no ledger could name. The model call
# behind the answer IS booked — the runner writes its tokens and its
# ``estimate_cost`` into ``ai_usage`` before it returns — but that row is keyed
# by (tenant, day, agent bucket) and says nothing about which call it was, so a
# spoken turn could not be priced, attributed or capped per call. Nothing else
# in the schema carried it either: ``voice_turns`` is the join of a turn's two
# messages, and the carrier's own usage (audio seconds) is never reported to us.
#
# So a completed turn gets ONE ledger row in ``usage_records`` — the existing
# per-event metering table, written through ``BillingService.record_usage`` —
# that names the session and the turn, the provider and model that answered, the
# units the provider actually reported, and the cost. This is deliberately NOT
# an increment of ``ai_usage``: the runner already booked that token cost, and
# booking it a second time would double the tenant's month-to-date spend and
# make the §42 cap bite at half the real budget. A carrier that reports a cost
# the ledger has never seen (audio seconds, when a provider starts reporting
# them) books it through ``record_usage`` — the one path that feeds the cap.

#: The metering feature a spoken turn's ledger row is booked under.
#:
#: Not one of the plan features (``ai_tokens`` / ``messages`` / ``orders``) on
#: purpose: this is a per-CALL ledger entry, and folding it into ``ai_tokens``
#: would charge the same model call twice against a plan's token limit, because
#: the runner already meters it there.
VOICE_TURN_FEATURE: Final = "voice_turn"


@dataclass(frozen=True, slots=True)
class VoiceTurnSpend:
    """What one spoken turn cost, in the units its provider actually reported.

    ``audio_seconds`` is the unit a realtime carrier bills by and ``tokens`` the
    one the model bills by; whichever was reported is what the row is quantified
    in. Today no carrier in this codebase returns a usage record, so the honest
    value is ``None`` — an estimate dressed up as a measurement is exactly the
    invention this class refuses to make.
    """

    provider: str | None = None
    model: str | None = None
    audio_seconds: Decimal | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    #: The cost that is known for this turn, or ``None`` for "not reported".
    #: Never defaulted to 0: a zero is a claim that the call was free.
    cost: Decimal | None = None

    @property
    def uncosted(self) -> bool:
        """True when nobody told us what this turn cost."""
        return self.cost is None

    @property
    def unit(self) -> str:
        """The unit the provider reported, which is the unit the row is in."""
        return "audio_seconds" if self.audio_seconds is not None else "tokens"

    @property
    def quantity(self) -> Decimal:
        """The row's quantity, in :attr:`unit`."""
        if self.audio_seconds is not None:
            return Decimal(self.audio_seconds)
        return Decimal(int(self.tokens_in or 0) + int(self.tokens_out or 0))


def voice_turn_usage_payload(
    spend: VoiceTurnSpend,
    *,
    voice_session_id: uuid.UUID,
    voice_turn_id: uuid.UUID,
    agent_id: uuid.UUID | None = None,
) -> dict[str, object]:
    """The ``usage_records.extra`` of one spoken turn: who, in what unit, at what cost.

    Money travels as a string, the way every other payload in this codebase
    carries a ``Decimal`` (JSON has no exact decimal). ``uncosted`` is the flag
    that says the cost is unknown, and ``cost`` is then JSON null rather than
    ``"0"`` — "nobody told us" and "it was free" are different facts.
    """
    return {
        "voice_session_id": str(voice_session_id),
        "voice_turn_id": str(voice_turn_id),
        "agent_id": str(agent_id) if agent_id is not None else None,
        "provider": spend.provider,
        "model": spend.model,
        "unit": spend.unit,
        "tokens_in": int(spend.tokens_in or 0),
        "tokens_out": int(spend.tokens_out or 0),
        "audio_seconds": None if spend.audio_seconds is None else str(spend.audio_seconds),
        "cost": None if spend.cost is None else str(spend.cost),
        "uncosted": spend.uncosted,
    }


async def spend_of_turn(
    session: AsyncSession, *, tenant_id: uuid.UUID, assistant_message_id: uuid.UUID | None
) -> VoiceTurnSpend:
    """The spend of the model call behind a spoken answer, or an uncosted one.

    The answer row keeps ``run_id`` (``chat.turns.run_chat_turn`` writes it), and
    the run keeps what the provider billed and which model did the answering —
    so the turn's own row is the way back to its cost without threading a second
    contract through the runtime. A turn with no run is not a bug: a memory
    command is answered with no model call at all, and it is recorded as uncosted
    with zero units rather than dropped.
    """
    if assistant_message_id is None:
        return VoiceTurnSpend()
    run_id = (
        await session.execute(
            select(AIChatMessage.run_id).where(
                AIChatMessage.tenant_id == tenant_id,
                AIChatMessage.id == assistant_message_id,
            )
        )
    ).scalar_one_or_none()
    if run_id is None:
        return VoiceTurnSpend()
    run = await session.get(AgentRun, run_id)
    if run is None:
        return VoiceTurnSpend()
    output = run.output or {}
    tokens_in = int(run.tokens_in or 0)
    tokens_out = int(run.tokens_out or 0)
    booked = Decimal(run.cost or 0)
    return VoiceTurnSpend(
        provider=output.get("provider") or None,
        model=output.get("model_name") or None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        # A run that was billed nothing (no tokens, or a zero-cost model) has no
        # cost to report — that is uncosted, not a free turn.
        cost=booked if booked > 0 else None,
    )


async def record_voice_turn_usage(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    voice_session_id: uuid.UUID,
    voice_turn_id: uuid.UUID,
    assistant_message_id: uuid.UUID | None,
    agent_id: uuid.UUID | None = None,
) -> VoiceTurnSpend:
    """Book the spend of one completed spoken turn, exactly once.

    Called by ``transcript_sync.complete_turn`` — the single writer of a turn, and
    the first place where a turn is known to have FINISHED — with the ids it just
    wrote. Exactly once follows from that: ``complete_turn`` only reaches this on
    the call that created the turn row, so a replayed delegation books nothing.

    ONE row is written (``usage_records``, feature :data:`VOICE_TURN_FEATURE`) and
    the ``ai_usage`` rollup is deliberately left alone: the runner already booked
    this turn's token cost there, and a second booking would double-count the §42
    cap — a tenant would see its month-to-date spend double and the cap fire at
    half the real budget. When a carrier starts reporting audio seconds as a cost
    of its own, that cost is the part the ledger has never seen and belongs in
    ``record_usage`` beside this call, not in a second counter.
    """
    spend = await spend_of_turn(
        session, tenant_id=tenant_id, assistant_message_id=assistant_message_id
    )
    # Call-scoped: billing.services imports this package's models, so a module
    # scope import here would be a cycle (the same reason budget.py does it).
    from app.platform.billing.services.subscriptions import BillingService

    await BillingService.record_usage(
        session,
        tenant_id,
        feature=VOICE_TURN_FEATURE,
        quantity=spend.quantity,
        extra=voice_turn_usage_payload(
            spend,
            voice_session_id=voice_session_id,
            voice_turn_id=voice_turn_id,
            agent_id=agent_id,
        ),
    )
    return spend
