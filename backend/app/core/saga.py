"""Spec §139 — Saga / Process Manager for long-running business processes.

A Saga coordinates a multi-step business process with compensation
semantics. Unlike pure choreography (where each module just reacts to
events), a Saga has explicit state and drives the process forward.

Example: Order → Payment → Inventory Reservation → Fulfillment → Shipment

Each step has:
    execute → forward action
    compensate → undo action (if later step fails)

The Saga state machine is persisted in the DB so a restart resumes from
the last completed step.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Index, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import NotFoundError, ValidationError
from app.core.events.writer import add_outbox_event
from app.core.ids import uuid7
from app.core.model_kit import TenantMixin, TimestampMixin

logger = logging.getLogger(__name__)


class SagaStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SagaStepStatus(StrEnum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    FAILED = "failed"


class Saga(TenantMixin, TimestampMixin, Base):
    """A long-running business process instance with explicit state.

    The saga tracks: which steps completed, which is current, what the
    compensation path is. This is NOT choreography — it is a state machine
    (§139).
    """

    __tablename__ = "sagas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid7
    )
    # The business process type: order_fulfillment, refund, onboarding, etc.
    saga_type: Mapped[str] = mapped_column(String(63))
    # The aggregate this saga orchestrates (e.g. order_id)
    aggregate_type: Mapped[str] = mapped_column(String(63))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(
        String(20), server_default="running"
    )
    # Current step index (0-based)
    current_step: Mapped[int] = mapped_column(Integer, server_default="0")
    # Step results: [{step, status, result, compensated}]
    step_results: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # Saga context: variables passed between steps
    context: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("ix_sagas_tenant_status", "tenant_id", "status"),
        Index("ix_sagas_tenant_aggregate", "tenant_id", "aggregate_type", "aggregate_id"),
    )


class SagaStepHandler:
    """Base class for saga step handlers.

    Each step in a saga has a handler that implements execute() and
    compensate(). The handler receives the saga context and returns a
    result dict that is stored on the saga.
    """

    async def execute(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        saga: Saga,
        context: dict,
    ) -> dict:
        """Forward action — advance the business process."""
        raise NotImplementedError

    async def compensate(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        saga: Saga,
        context: dict,
    ) -> dict:
        """Undo the action — called when a later step fails."""
        raise NotImplementedError


class SagaManager:
    """§139: drives a saga state machine forward.

    Steps are registered by (saga_type, step_index). The manager
    executes the next step, records the result, and either advances
    or triggers compensation.
    """

    _handlers: dict[tuple[str, int], SagaStepHandler] = {}

    @classmethod
    def register(
        cls,
        saga_type: str,
        step_index: int,
        handler: SagaStepHandler,
    ) -> None:
        cls._handlers[(saga_type, step_index)] = handler

    @staticmethod
    async def create_saga(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        saga_type: str,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        context: dict | None = None,
    ) -> Saga:
        saga = Saga(
            tenant_id=tenant_id,
            saga_type=saga_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            status=SagaStatus.RUNNING.value,
            current_step=0,
            context=context or {},
        )
        session.add(saga)
        await session.flush()

        add_outbox_event(
            session,
            stream="saga.events",
            event_type="saga.started",
            aggregate_type="saga",
            aggregate_id=saga.id,
            tenant_id=tenant_id,
            payload={
                "saga_type": saga_type,
                "aggregate_type": aggregate_type,
                "aggregate_id": str(aggregate_id),
            },
        )
        return saga

    @staticmethod
    async def execute_next(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        saga_id: uuid.UUID,
    ) -> Saga:
        """Execute the next pending step. If it fails, trigger compensation."""
        saga = (
            await session.execute(
                select(Saga).where(
                    Saga.tenant_id == tenant_id,
                    Saga.id == saga_id,
                )
            )
        ).scalar_one_or_none()
        if saga is None:
            raise NotFoundError("saga not found")
        if saga.status != SagaStatus.RUNNING.value:
            raise ValidationError(f"saga is {saga.status}, cannot execute")

        handler = SagaManager._handlers.get(
            (saga.saga_type, saga.current_step)
        )
        if handler is None:
            # No more steps — saga is complete
            saga.status = SagaStatus.COMPLETED.value
            saga.completed_at = datetime.now(UTC)
            await session.flush()
            add_outbox_event(
                session,
                stream="saga.events",
                event_type="saga.completed",
                aggregate_type="saga",
                aggregate_id=saga.id,
                tenant_id=tenant_id,
                payload={"saga_type": saga.saga_type},
            )
            return saga

        try:
            result = await handler.execute(
                session, tenant_id, saga, saga.context
            )
            saga.step_results = [
                *saga.step_results,
                {
                    "step": saga.current_step,
                    "status": SagaStepStatus.COMPLETED.value,
                    "result": result,
                },
            ]
            saga.current_step += 1
            saga.context = {**saga.context, **result}
            await session.flush()
        except Exception as exc:
            saga.last_error = str(exc)
            saga.status = SagaStatus.COMPENSATING.value
            saga.step_results = [
                *saga.step_results,
                {
                    "step": saga.current_step,
                    "status": SagaStepStatus.FAILED.value,
                    "error": str(exc),
                },
            ]
            await session.flush()
            # Trigger compensation for all completed steps (reverse order)
            await SagaManager._compensate(session, tenant_id, saga)
            raise

        return saga

    @staticmethod
    async def _compensate(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        saga: Saga,
    ) -> None:
        """Run compensation for all completed steps in reverse order."""
        completed = [
            r for r in saga.step_results
            if r.get("status") == SagaStepStatus.COMPLETED.value
        ]
        for record in reversed(completed):
            step_index = record["step"]
            handler = SagaManager._handlers.get(
                (saga.saga_type, step_index)
            )
            if handler is None:
                continue
            try:
                await handler.compensate(
                    session, tenant_id, saga, saga.context
                )
                record["status"] = SagaStepStatus.COMPENSATED.value
            except Exception as exc:
                logger.error(
                    "saga %s step %d compensation failed: %s",
                    saga.id, step_index, exc,
                )
                record["status"] = SagaStepStatus.FAILED.value
                record["compensation_error"] = str(exc)

        saga.status = SagaStatus.FAILED.value
        saga.completed_at = datetime.now(UTC)
        await session.flush()

        add_outbox_event(
            session,
            stream="saga.events",
            event_type="saga.failed",
            aggregate_type="saga",
            aggregate_id=saga.id,
            tenant_id=tenant_id,
            payload={
                "saga_type": saga.saga_type,
                "error": saga.last_error,
            },
        )
