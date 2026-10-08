"""§169: AI evaluation service — offline evaluation of agent/prompt versions
before rollout. Records evaluation runs, reports status, gates canary
rollout behind explicit human approval, and automates rollback when
canary metrics degrade.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.ai.models import AIEvaluation

logger = logging.getLogger(__name__)

# §169: canary traffic percentages. A newly approved evaluation starts at 5%
# and ramps up over 4 steps. If canary metrics degrade, the rollback
# function drops traffic to 0% immediately.
CANARY_RAMP_STEPS = [5, 25, 50, 100]
CANARY_ROLLOUT_WINDOW_HOURS = 24  # max time to complete the ramp
CANARY_METRIC_THRESHOLD = 0.85  # min success_rate before ramp continues


class AIEvaluationService:
    """Service for the §169 evaluation pipeline: submit, status, approve,
    ramp canary traffic, monitor, and rollback."""

    @staticmethod
    async def submit_evaluation(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID | None = None,
        agent_version_id: uuid.UUID | None = None,
        dataset_id: str | None = None,
        results: dict | None = None,
        *,
        prompt_version: int = 1,
        status: str | None = None,
        notes: str | None = None,
    ) -> AIEvaluation:
        """Record an evaluation run for an agent/prompt version."""
        effective_agent_id = agent_id or agent_version_id
        if effective_agent_id is None:
            raise ValidationError("agent_id is required for evaluation")
        metrics = results or {}
        eval_status = status or ("passed" if metrics.get("passed") else "failed")
        evaluation = AIEvaluation(
            tenant_id=tenant_id,
            agent_id=effective_agent_id,
            prompt_version=prompt_version,
            dataset_ref=dataset_id,
            status=eval_status,
            quality_metrics=metrics,
            rollout_status="none",
            notes=notes,
        )
        session.add(evaluation)
        await session.flush()
        return evaluation

    @staticmethod
    async def list_evaluations(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        agent_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[AIEvaluation]:
        """List evaluations for a tenant, optionally filtered by agent."""
        stmt = (
            select(AIEvaluation)
            .where(AIEvaluation.tenant_id == tenant_id)
            .order_by(AIEvaluation.created_at.desc())
            .limit(min(limit, 200))
        )
        if agent_id is not None:
            stmt = stmt.where(AIEvaluation.agent_id == agent_id)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)

    @staticmethod
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
        evaluation = (
            await session.execute(
                select(AIEvaluation).where(
                    AIEvaluation.tenant_id == tenant_id,
                    AIEvaluation.id == evaluation_id,
                )
            )
        ).scalar_one_or_none()
        if evaluation is None:
            raise NotFoundError(f"evaluation {evaluation_id} not found")
        evaluation.status = status
        if quality_metrics is not None:
            evaluation.quality_metrics = quality_metrics
        if rollout_status is not None:
            evaluation.rollout_status = rollout_status
        if notes is not None:
            evaluation.notes = notes
        await session.flush()
        return evaluation

    @staticmethod
    async def get_evaluation_status(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        agent_version_id: uuid.UUID,
    ) -> AIEvaluation | None:
        """Return the latest evaluation for an agent version, or None."""
        evaluation = (
            await session.execute(
                select(AIEvaluation)
                .where(
                    AIEvaluation.tenant_id == tenant_id,
                    AIEvaluation.agent_id == agent_version_id,
                )
                .order_by(AIEvaluation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return evaluation

    @staticmethod
    async def approve_rollout(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        agent_version_id: uuid.UUID,
    ) -> AIEvaluation:
        """Mark the latest evaluation as approved for canary rollout.

        §169: gating — only passed evaluations can be approved. The
        canary starts at 5% traffic; the ramp worker increases it
        over CANARY_RAMP_STEPS.
        """
        evaluation = await AIEvaluationService.get_evaluation_status(
            session, tenant_id, agent_version_id
        )
        if evaluation is None:
            raise NotFoundError(f"no evaluation found for agent {agent_version_id}")
        if evaluation.status not in ("passed", "approved"):
            raise ValidationError(
                f"cannot approve evaluation with status '{evaluation.status}' "
                f"— only passed evaluations can be approved for rollout"
            )
        evaluation.status = "approved"
        evaluation.rollout_status = f"canary_{CANARY_RAMP_STEPS[0]}"
        await session.flush()

        # §169: emit an event so the canary traffic router picks this up
        from app.core.events.writer import add_outbox_event

        await add_outbox_event(
            session,
            aggregate_type="ai_evaluation",
            aggregate_id=evaluation.id,
            event_type="ai.canary_started",
            tenant_id=tenant_id,
            payload={
                "agent_id": str(agent_version_id),
                "evaluation_id": str(evaluation.id),
                "traffic_percent": CANARY_RAMP_STEPS[0],
            },
            # Literal: AIEvaluation has no version column (no VersionMixin on
            # the model), so there is no aggregate version source to read.
            aggregate_version=1,
        )
        return evaluation

    @staticmethod
    async def ramp_canary(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        evaluation_id: uuid.UUID,
    ) -> AIEvaluation:
        """§169: ramp canary traffic to the next step.

        Called by the canary monitor worker. Checks canary metrics first;
        if success_rate < CANARY_METRIC_THRESHOLD, rolls back instead.
        """
        evaluation = (
            await session.execute(
                select(AIEvaluation).where(
                    AIEvaluation.tenant_id == tenant_id,
                    AIEvaluation.id == evaluation_id,
                )
            )
        ).scalar_one_or_none()
        if evaluation is None:
            raise NotFoundError(f"evaluation {evaluation_id} not found")

        if evaluation.rollout_status is None or not evaluation.rollout_status.startswith("canary_"):
            raise ConflictError(
                f"evaluation {evaluation_id} is not in canary rollout "
                f"(status={evaluation.rollout_status})"
            )

        # §169: check canary metrics before ramping
        metrics = evaluation.quality_metrics or {}
        success_rate = float(metrics.get("canary_success_rate", 1.0))
        if success_rate < CANARY_METRIC_THRESHOLD:
            logger.warning(
                "ai.canary_metric_degraded eval=%s success_rate=%.2f threshold=%.2f — rolling back",
                evaluation_id,
                success_rate,
                CANARY_METRIC_THRESHOLD,
            )
            return await AIEvaluationService.rollback_canary(
                session, tenant_id, evaluation_id, reason="metric_degradation"
            )

        # Determine current step and ramp to next
        current_pct = int(evaluation.rollout_status.split("_")[1])
        try:
            current_idx = CANARY_RAMP_STEPS.index(current_pct)
        except ValueError as err:
            raise ConflictError(f"unknown canary percentage: {current_pct}") from err

        if current_idx >= len(CANARY_RAMP_STEPS) - 1:
            # Already at 100% — promote to fully rolled out
            evaluation.rollout_status = "rolled_out"
            await session.flush()
            return evaluation

        next_pct = CANARY_RAMP_STEPS[current_idx + 1]
        evaluation.rollout_status = f"canary_{next_pct}"
        await session.flush()

        logger.info(
            "ai.canary_ramped eval=%s from=%d%% to=%d%%",
            evaluation_id,
            current_pct,
            next_pct,
        )
        return evaluation

    @staticmethod
    async def rollback_canary(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        evaluation_id: uuid.UUID,
        *,
        reason: str = "manual",
    ) -> AIEvaluation:
        """§169: immediately drop canary traffic to 0% and mark as rolled back.

        The agent version is reverted to the previous known-good version.
        The canary traffic router stops sending traffic to this version.
        """
        evaluation = (
            await session.execute(
                select(AIEvaluation).where(
                    AIEvaluation.tenant_id == tenant_id,
                    AIEvaluation.id == evaluation_id,
                )
            )
        ).scalar_one_or_none()
        if evaluation is None:
            raise NotFoundError(f"evaluation {evaluation_id} not found")

        evaluation.rollout_status = "rolled_back"
        await session.flush()

        # §169: emit rollback event so the traffic router drops this version
        from app.core.events.writer import add_outbox_event

        await add_outbox_event(
            session,
            aggregate_type="ai_evaluation",
            aggregate_id=evaluation.id,
            event_type="ai.canary_rolled_back",
            tenant_id=tenant_id,
            payload={
                "agent_id": str(evaluation.agent_id),
                "evaluation_id": str(evaluation_id),
                "reason": reason,
            },
            # Literal: AIEvaluation has no version column (no VersionMixin on
            # the model), so there is no aggregate version source to read.
            aggregate_version=1,
        )

        logger.info(
            "ai.canary_rolled_back eval=%s reason=%s",
            evaluation_id,
            reason,
        )
        return evaluation

    @staticmethod
    async def get_canary_traffic_percent(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> int:
        """§169: return the current canary traffic percentage for an agent.

        The AI runtime calls this to decide whether to use the canary
        version or the stable version for a given run.
        """
        evaluation = await AIEvaluationService.get_evaluation_status(session, tenant_id, agent_id)
        if evaluation is None or evaluation.rollout_status is None:
            return 0
        if evaluation.rollout_status.startswith("canary_"):
            return int(evaluation.rollout_status.split("_")[1])
        if evaluation.rollout_status == "rolled_out":
            return 100
        return 0  # rolled_back or none


def _evaluation_out(ev: AIEvaluation) -> dict:
    return {
        "id": str(ev.id),
        "agent_id": str(ev.agent_id),
        "status": ev.status,
        "rollout_status": ev.rollout_status,
        "quality_metrics": ev.quality_metrics,
        "dataset_ref": ev.dataset_ref,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }
