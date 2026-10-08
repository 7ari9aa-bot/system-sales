"""Spec §44 — AI trace: "what did the AI actually do, and why?".

The tables already exist (``agent_runs`` + ``model_calls`` + ``tool_calls``), but
nothing assembled them into an answer keyed by a correlation id. This service
does that, in two shapes:

- the **admin view** (:meth:`AITraceService.for_run`) — one run with its model
  and tool children, so an operator can see the model, provider, tokens, cost,
  latency, tools, errors and fallback usage;
- the **correlation view** (:meth:`AITraceService.by_correlation`) — every run
  that belongs to one customer interaction, which is how a handoff is followed;
- the **rollup** (:meth:`AITraceService.summary`) — the 7-day health numbers.

Money is ``Numeric``/``Decimal`` throughout (ADR-001). Values are coerced with
:func:`_money`, never via ``float()``.

**Schema reality check (verified against ``models.py``, not assumed):**
``AgentRun`` has **no** ``correlation_id`` and **no** ``causation_id`` column.
The spec's admin view also asks for ``prompt_version``, ``retries``,
``policy_decisions`` and ``request_id``; the schema stores none of them either.
Rather than invent columns, this service:

- reads correlation/causation from the run's ``input`` JSONB payload if a caller
  wrote them there (``input.correlation_id`` / ``input.causation_id``), else
  reports ``None``;
- reports the other four spec fields as ``None`` / ``[]`` so the admin-view shape
  is stable while remaining honest about what is not recorded.

Adding real columns is a ``models.py`` change, which this task explicitly does
not own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.ai.models import AgentRun, AIEvaluation, ModelCall, ToolCall

# Run statuses that represent a failed interaction from the customer's side.
# ``timeout`` is included: the agent hit a run limit and produced no answer.
FAILED_STATUSES = ("failed", "timeout")


def _money(value: object) -> Decimal:
    """Coerce a MONEY/Numeric value to Decimal without a float round-trip."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _correlation_from_input(run: AgentRun, key: str) -> str | None:
    """Read ``key`` out of the run's JSONB input, if a caller put it there."""
    payload = run.input if isinstance(run.input, dict) else {}
    value = payload.get(key)
    return str(value) if value else None


def _run_summary(run: AgentRun) -> dict:
    """Run-level fields only — the list shape for correlation traces."""
    input_payload = run.input if isinstance(run.input, dict) else {}
    output_payload = run.output if isinstance(run.output, dict) else {}
    agent_version = input_payload.get("agent_version") or output_payload.get("agent_version")
    model = input_payload.get("model") or output_payload.get("model")
    return {
        "run_id": str(run.id),
        "agent_id": str(run.agent_id),
        "agent_version": agent_version,
        "model": model,
        "conversation_id": str(run.conversation_id) if run.conversation_id else None,
        "status": run.status,
        "tokens_in": int(run.tokens_in or 0),
        "tokens_out": int(run.tokens_out or 0),
        "cost": _money(run.cost),
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "correlation_id": _correlation_from_input(run, "correlation_id"),
        "causation_id": _correlation_from_input(run, "causation_id"),
    }


def _latency_ms(run: AgentRun) -> int | None:
    """Wall-clock duration of the run, when both timestamps are present."""
    if run.started_at is None or run.finished_at is None:
        return None
    return int((run.finished_at - run.started_at).total_seconds() * 1000)


class AITraceService:
    @staticmethod
    async def for_run(session: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID) -> dict:
        """The admin view for one run: run + model calls + tool calls.

        ``NotFoundError`` when the run does not belong to this tenant (RLS makes
        a cross-tenant id indistinguishable from a missing one, which is the
        desired behaviour).
        """
        run = (
            await session.execute(
                select(AgentRun).where(
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.id == run_id,
                )
            )
        ).scalar_one_or_none()
        if run is None:
            raise NotFoundError(f"agent run {run_id} not found")

        model_calls = (
            (
                await session.execute(
                    select(ModelCall)
                    .where(ModelCall.tenant_id == tenant_id, ModelCall.run_id == run_id)
                    .order_by(ModelCall.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        tool_calls = (
            (
                await session.execute(
                    select(ToolCall)
                    .where(ToolCall.tenant_id == tenant_id, ToolCall.run_id == run_id)
                    .order_by(ToolCall.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        # "Which model did this run actually use?" — the last successful call is
        # the one that produced the answer; fall back to the first recorded.
        chosen = next((c for c in reversed(model_calls) if c.status == "ok"), None) or (
            model_calls[0] if model_calls else None
        )

        errors = [run.error] if run.error else []
        errors.extend(c.error for c in tool_calls if c.error)

        return {
            **_run_summary(run),
            "model": chosen.model if chosen else None,
            "provider": chosen.provider if chosen else None,
            "alias": chosen.alias if chosen else None,
            "latency_ms": _latency_ms(run),
            "model_latency_ms": sum(int(c.latency_ms or 0) for c in model_calls),
            "fallback": any(c.alias == "fallback" for c in model_calls),
            "tools": [c.name for c in tool_calls],
            "errors": errors,
            "model_calls": [
                {
                    "id": str(c.id),
                    "alias": c.alias,
                    "provider": c.provider,
                    "model": c.model,
                    "tokens_in": int(c.tokens_in or 0),
                    "tokens_out": int(c.tokens_out or 0),
                    "cost": _money(c.cost),
                    "latency_ms": c.latency_ms,
                    "status": c.status,
                }
                for c in model_calls
            ],
            "tool_calls": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "status": c.status,
                    "error": c.error,
                    "duration_ms": c.duration_ms,
                    "result": c.result,
                }
                for c in tool_calls
            ],
            # Spec §44 admin-view fields the schema cannot supply today. Present
            # (not omitted) so consumers get a stable shape; see module docstring.
            "prompt_version": None,
            "retries": None,
            "policy_decisions": [],
            "request_id": None,
        }

    @staticmethod
    async def by_correlation(
        session: AsyncSession, tenant_id: uuid.UUID, correlation_id: str
    ) -> list[dict]:
        """Every run belonging to one customer interaction, oldest first.

        ``AgentRun`` has no correlation column, so correlation is resolved from
        what the schema *does* hold: a run matches when its own ``id`` equals
        ``correlation_id`` (the originating run) or when its ``input`` JSONB
        carries ``correlation_id`` (a handoff/child run). This lets a handoff
        chain be followed without inventing a column.
        """
        conditions = [AgentRun.input["correlation_id"].astext == str(correlation_id)]
        try:
            conditions.append(AgentRun.id == uuid.UUID(str(correlation_id)))
        except ValueError:
            # Not a UUID — only the JSONB correlation key can match.
            pass

        rows = (
            (
                await session.execute(
                    select(AgentRun)
                    .where(
                        AgentRun.tenant_id == tenant_id,
                        or_(*conditions),
                    )
                    .order_by(AgentRun.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return [_run_summary(run) for run in rows]

    @staticmethod
    async def summary(session: AsyncSession, tenant_id: uuid.UUID, *, days: int = 7) -> dict:
        """Rollup for the last ``days`` days: runs, failures, fallback, tokens, cost.

        ``fallback`` counts ``model_calls`` routed to the ``fallback`` alias —
        the alias the gateway uses when a primary provider is unavailable.
        """
        since = datetime.now(UTC) - timedelta(days=days)
        totals = (
            await session.execute(
                select(
                    func.count(AgentRun.id),
                    func.count(AgentRun.id).filter(AgentRun.status.in_(FAILED_STATUSES)),
                    func.coalesce(func.sum(AgentRun.tokens_in), 0),
                    func.coalesce(func.sum(AgentRun.tokens_out), 0),
                    func.coalesce(func.sum(AgentRun.cost), 0),
                ).where(
                    AgentRun.tenant_id == tenant_id,
                    AgentRun.created_at >= since,
                )
            )
        ).one()
        runs, failures, tokens_in, tokens_out, cost = totals

        fallback_count = (
            await session.execute(
                select(func.count(ModelCall.id)).where(
                    ModelCall.tenant_id == tenant_id,
                    ModelCall.created_at >= since,
                    ModelCall.alias == "fallback",
                )
            )
        ).scalar_one()

        return {
            "days": days,
            "since": since.isoformat(),
            "runs": int(runs or 0),
            "failures": int(failures or 0),
            "fallback_count": int(fallback_count or 0),
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
            "total_tokens": int(tokens_in or 0) + int(tokens_out or 0),
            "total_cost": _money(cost),
        }


# ---------------------------------------------------------------------------
# §169 — AI evaluation pipeline
# ---------------------------------------------------------------------------
# An offline evaluation records how an agent/prompt version performs against
# a dataset before it is rolled out. The model exists (AIEvaluation) but was
# never referenced; these functions make it reachable from the router.


async def create_evaluation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    agent_id: uuid.UUID,
    prompt_version: int = 1,
    dataset_ref: str | None = None,
    notes: str | None = None,
) -> AIEvaluation:
    """§169: create an evaluation record for an agent/prompt version."""
    from app.modules.ai.evaluation import AIEvaluationService

    return await AIEvaluationService.submit_evaluation(
        session,
        tenant_id,
        agent_id=agent_id,
        prompt_version=prompt_version,
        dataset_id=dataset_ref,
        status="pending",
        notes=notes,
    )


async def list_evaluations(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[AIEvaluation]:
    """List evaluations for a tenant, optionally filtered by agent."""
    from app.modules.ai.evaluation import AIEvaluationService

    return await AIEvaluationService.list_evaluations(
        session, tenant_id, agent_id=agent_id, limit=limit
    )


async def update_evaluation_status(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    evaluation_id: uuid.UUID,
    *,
    status: str,
    quality_metrics: dict | None = None,
    rollout_status: str | None = None,
    notes: str | None = None,
) -> AIEvaluation:
    """Update an evaluation's status after the evaluation run completes."""
    from app.modules.ai.evaluation import AIEvaluationService

    return await AIEvaluationService.update_evaluation_status(
        session,
        tenant_id,
        evaluation_id,
        status=status,
        quality_metrics=quality_metrics,
        rollout_status=rollout_status,
        notes=notes,
    )
