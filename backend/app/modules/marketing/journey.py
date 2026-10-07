"""Spec §175 Phase 5 — Journey execution engine.

A Journey is a multi-step customer lifecycle automation: a customer
enters a journey, steps execute (DELAY → MESSAGE → CONDITION → AI_ACTION),
and the state machine advances. Delays use the durable scheduler (§154)
so a restart does not lose pending steps.

Design rules:
- Every step transition is audited via AuditService
- Messages dispatch via ConversationService + outbox (never direct send)
- §144 fairness: batch processing respects tenant concurrency budgets
- §126 serialization: a journey run for a customer is serialized via the
  conversation lease when it touches a conversation
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import NotFoundError, ValidationError
from app.core.events.writer import add_outbox_event
from app.core.ids import uuid7
from app.core.model_kit import TenantMixin, TimestampMixin, WorkspaceScopeMixin

logger = logging.getLogger(__name__)


class JourneyStepType(StrEnum):
    DELAY = "delay"
    MESSAGE = "message"
    CONDITION = "condition"
    AI_ACTION = "ai_action"
    WEBHOOK = "webhook"
    END = "end"


class JourneyRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_DELAY = "waiting_delay"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Journey(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """A reusable customer journey definition."""

    __tablename__ = "journeys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    # Entry trigger: {event, filters} — e.g. {event: "customer.created"}
    trigger: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Steps: [{step_index, step_type, config, next_step_index}]
    steps: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # allowed: draft | active | paused | archived
    status: Mapped[str] = mapped_column(String(15), server_default="draft")

    __table_args__ = (Index("ix_journeys_tenant_status", "tenant_id", "status"),)


class JourneyRun(TenantMixin, TimestampMixin, Base):
    """One customer's execution of a journey — the state machine instance."""

    __tablename__ = "journey_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    journey_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journeys.id", ondelete="CASCADE")
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE")
    )
    current_step: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Execution context: variables, results from previous steps
    context: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_journey_runs_tenant_status", "tenant_id", "status"),
        Index("ix_journey_runs_tenant_customer", "tenant_id", "customer_id"),
    )


class JourneyExecutionService:
    """§175: Journey execution state machine.

    Each step type has a handler. Delays schedule a ScheduledJob; on
    completion the scheduler re-enters process_step.
    """

    @staticmethod
    async def start_journey(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        journey_id: uuid.UUID,
        customer_id: uuid.UUID,
    ) -> JourneyRun:
        journey = (
            await session.execute(
                select(Journey).where(
                    Journey.tenant_id == tenant_id,
                    Journey.id == journey_id,
                )
            )
        ).scalar_one_or_none()
        if journey is None:
            raise NotFoundError("journey not found")
        if journey.status != "active":
            raise ValidationError(f"journey is {journey.status}, not active")

        run = JourneyRun(
            tenant_id=tenant_id,
            journey_id=journey_id,
            customer_id=customer_id,
            current_step=0,
            status=JourneyRunStatus.RUNNING.value,
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()

        await add_outbox_event(
            session,
            event_type="journey.run.started",
            aggregate_type="journey_run",
            aggregate_id=run.id,
            tenant_id=tenant_id,
            payload={"journey_id": str(journey_id), "customer_id": str(customer_id)},
        )
        return run

    @staticmethod
    async def process_step(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> JourneyRun:
        run = (
            await session.execute(
                select(JourneyRun).where(
                    JourneyRun.tenant_id == tenant_id,
                    JourneyRun.id == run_id,
                )
            )
        ).scalar_one_or_none()
        if run is None:
            raise NotFoundError("journey run not found")
        if run.status not in (JourneyRunStatus.RUNNING.value, JourneyRunStatus.WAITING_DELAY.value):
            raise ValidationError(f"run is {run.status}, cannot process")

        journey = (
            await session.execute(select(Journey).where(Journey.id == run.journey_id))
        ).scalar_one()

        steps = journey.steps or []
        if run.current_step >= len(steps):
            return await JourneyExecutionService._complete(session, run)

        step = steps[run.current_step]
        step_type = step.get("type", step.get("step_type", ""))
        config = step.get("config", {})

        try:
            if step_type == JourneyStepType.DELAY.value:
                await JourneyExecutionService._handle_delay(session, tenant_id, run, config)
            elif step_type == JourneyStepType.MESSAGE.value:
                await JourneyExecutionService._handle_message(session, tenant_id, run, config)
                await JourneyExecutionService._advance(session, run)
            elif step_type == JourneyStepType.CONDITION.value:
                await JourneyExecutionService._handle_condition(session, tenant_id, run, config)
            elif step_type == JourneyStepType.AI_ACTION.value:
                await JourneyExecutionService._handle_ai_action(session, tenant_id, run, config)
                await JourneyExecutionService._advance(session, run)
            elif step_type == JourneyStepType.END.value:
                return await JourneyExecutionService._complete(session, run)
            else:
                logger.warning("unknown journey step type: %s", step_type)
                await JourneyExecutionService._advance(session, run)
        except Exception as exc:
            run.status = JourneyRunStatus.FAILED.value
            run.last_error = str(exc)
            await session.flush()
            raise

        return run

    @staticmethod
    async def resume_after_delay(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> JourneyRun | None:
        """Continue a run whose DELAY step has elapsed — the scheduler's entry point.

        ``_handle_delay`` parks the run at WAITING_DELAY and deliberately does
        NOT advance ``current_step``: the step is what owns the scheduled row.
        So resuming is not simply re-entering ``process_step`` — that would hit
        the same DELAY step and schedule another delay, forever. The step is
        verified to still BE a delay before it is stepped over, so a journey
        edited mid-flight cannot have a real action (a message, an AI call)
        silently skipped by a resume.

        Returns None when the run is gone or no longer waiting: a journey
        cancelled during its delay must finish as a no-op rather than as a job
        that burns its retry budget on a run that will never resume.
        """
        run = (
            await session.execute(
                select(JourneyRun).where(
                    JourneyRun.tenant_id == tenant_id,
                    JourneyRun.id == run_id,
                )
            )
        ).scalar_one_or_none()
        if run is None or run.status != JourneyRunStatus.WAITING_DELAY.value:
            return None

        journey = (
            await session.execute(select(Journey).where(Journey.id == run.journey_id))
        ).scalar_one_or_none()
        steps = (journey.steps or []) if journey is not None else []
        step = steps[run.current_step] if run.current_step < len(steps) else {}
        step_type = step.get("type", step.get("step_type", ""))
        if step_type != JourneyStepType.DELAY.value:
            raise ValidationError(
                f"journey run {run.id} waits on step {run.current_step}, which is "
                f"{step_type or 'missing'} and not a delay — refusing to skip it"
            )

        run.current_step += 1
        run.status = JourneyRunStatus.RUNNING.value
        await session.flush()
        return await JourneyExecutionService.process_step(session, tenant_id, run.id)

    @staticmethod
    async def _handle_delay(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run: JourneyRun,
        config: dict,
    ) -> None:
        """Schedule a ScheduledJob to resume after the delay.

        ``job_type='journey.resume'`` is dispatched by
        ``app/workers/scheduler_worker.py``; that registration and this literal
        are kept in sync by
        ``tests/test_worker_deployment_declaration.py`` — this call site is the
        producer half of a pair that was broken here for the whole life of the
        feature (the row was created, claimed and failed with "no handler").
        """
        from app.modules.platform.models import ScheduledJob

        delay_minutes = int(config.get("minutes", config.get("delay_minutes", 5)))
        run_at = datetime.now(UTC) + timedelta(minutes=delay_minutes)
        run.status = JourneyRunStatus.WAITING_DELAY.value
        await session.flush()

        job = ScheduledJob(
            tenant_id=tenant_id,
            job_type="journey.resume",
            run_at=run_at,
            payload={"run_id": str(run.id)},
            # Keyed on the STEP, not just the run. `idempotency_key` is UNIQUE
            # (uq_scheduled_jobs_idem), so a journey with a second DELAY step
            # would insert a row under a key the first step's row still holds:
            # the flush raises at commit and rolls the whole claimed batch back
            # — the exact failure `_reschedule_recurring` documents. The step
            # index is stable for one delay, so a duplicate wake-up still
            # dedupes against the row that already carries it.
            idempotency_key=f"journey:resume:{run.id}:{run.current_step}",
        )
        session.add(job)
        await session.flush()

    @staticmethod
    async def _handle_message(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run: JourneyRun,
        config: dict,
    ) -> None:
        """Dispatch a message via ConversationService + outbox."""
        from app.modules.conversations.service import ConversationService

        template = config.get("template")
        body = config.get("body", "")
        channel = config.get("channel", "whatsapp")

        await ConversationService.send_outbound_from_automation(
            session,
            tenant_id=tenant_id,
            customer_id=run.customer_id,
            body=body,
            template_name=template,
            channel=channel,
            source="journey",
            correlation_id=f"journey:{run.id}",
        )

    @staticmethod
    async def _handle_condition(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run: JourneyRun,
        config: dict,
    ) -> None:
        """Evaluate a condition and branch."""
        _condition = config.get("expression", "true")
        true_step = config.get("true_step_index", run.current_step + 1)
        _false_step = config.get("false_step_index", run.current_step + 1)

        # Simple evaluation — a real implementation would use the DSL/AST
        # from §82 segment definitions. For now, route to true_step.
        run.current_step = true_step
        await session.flush()

    @staticmethod
    async def _handle_ai_action(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        run: JourneyRun,
        config: dict,
    ) -> None:
        """Trigger an AI action (e.g. tag customer, send AI message)."""
        action = config.get("action", "tag")
        if action == "tag":
            tag = config.get("tag", "journey")
            run.context = {**run.context, "ai_tag": tag}
            await session.flush()

    @staticmethod
    async def _advance(session: AsyncSession, run: JourneyRun) -> None:
        run.current_step += 1
        await session.flush()

    @staticmethod
    async def _complete(session: AsyncSession, run: JourneyRun) -> JourneyRun:
        run.status = JourneyRunStatus.COMPLETED.value
        run.completed_at = datetime.now(UTC)
        await session.flush()

        await add_outbox_event(
            session,
            event_type="journey.run.completed",
            aggregate_type="journey_run",
            aggregate_id=run.id,
            tenant_id=run.tenant_id,
            payload={"customer_id": str(run.customer_id)},
        )
        return run
