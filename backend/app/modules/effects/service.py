"""Effect Ledger service implementation (V12 Wave C §30)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.effects.models import EFFECT_STATUSES, EffectLedger
from app.modules.effects.schemas import compute_effect_idempotency_key


class EffectService:
    """Service managing deterministic effect intents, lifecycle, and ambiguous reconciliation."""

    @staticmethod
    async def record_intent(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        operation: str,
        arguments: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        task_id: str | None = None,
        decision_id: uuid.UUID | None = None,
        lease_id: uuid.UUID | None = None,
        provider: str | None = None,
    ) -> EffectLedger:
        """Record intent to perform an effect. If idempotency key already exists, return existing."""
        if not operation or not operation.strip():
            raise ValidationError("operation must be a non-empty string")

        args = arguments or {}
        idempotency_key = compute_effect_idempotency_key(
            tenant_id=tenant_id,
            operation=operation,
            arguments=args,
            workflow_id=workflow_id,
            task_id=task_id,
        )

        existing = await session.scalar(
            select(EffectLedger).where(
                EffectLedger.tenant_id == tenant_id,
                EffectLedger.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing

        now = datetime.now(UTC)
        effect = EffectLedger(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            operation=operation.strip(),
            workflow_id=workflow_id.strip() if workflow_id else None,
            task_id=task_id.strip() if task_id else None,
            decision_id=decision_id,
            lease_id=lease_id,
            status="PENDING",
            provider=provider.strip() if provider else None,
            arguments=args,
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        session.add(effect)
        await session.flush()
        return effect

    @staticmethod
    async def get(
        session: AsyncSession, tenant_id: uuid.UUID, effect_id: uuid.UUID
    ) -> EffectLedger:
        """Retrieve an effect by tenant-scoped ID."""
        effect = await session.scalar(
            select(EffectLedger).where(
                EffectLedger.tenant_id == tenant_id,
                EffectLedger.effect_id == effect_id,
            )
        )
        if not effect:
            raise NotFoundError(f"Effect {effect_id} not found")
        return effect

    @staticmethod
    async def get_by_idempotency_key(
        session: AsyncSession, tenant_id: uuid.UUID, idempotency_key: str
    ) -> EffectLedger | None:
        """Lookup an effect by tenant-scoped idempotency key."""
        return await session.scalar(
            select(EffectLedger).where(
                EffectLedger.tenant_id == tenant_id,
                EffectLedger.idempotency_key == idempotency_key,
            )
        )

    @staticmethod
    async def mark_executing(
        session: AsyncSession, tenant_id: uuid.UUID, effect_id: uuid.UUID
    ) -> EffectLedger:
        """Transition effect to EXECUTING and record attempt."""
        effect = await session.scalar(
            select(EffectLedger)
            .where(
                EffectLedger.tenant_id == tenant_id,
                EffectLedger.effect_id == effect_id,
            )
            .with_for_update()
        )
        if not effect:
            raise NotFoundError(f"Effect {effect_id} not found")

        if effect.status == "COMPLETED":
            raise ConflictError(f"Effect {effect_id} is already COMPLETED")

        now = datetime.now(UTC)
        effect.status = "EXECUTING"
        effect.attempts += 1
        effect.last_attempt_at = now
        effect.updated_at = now
        await session.flush()
        return effect

    @staticmethod
    async def mark_completed(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        effect_id: uuid.UUID,
        *,
        result: dict[str, Any] | None = None,
        provider_reference: str | None = None,
    ) -> EffectLedger:
        """Mark effect as successfully completed."""
        effect = await session.scalar(
            select(EffectLedger)
            .where(
                EffectLedger.tenant_id == tenant_id,
                EffectLedger.effect_id == effect_id,
            )
            .with_for_update()
        )
        if not effect:
            raise NotFoundError(f"Effect {effect_id} not found")

        now = datetime.now(UTC)
        effect.status = "COMPLETED"
        if result is not None:
            effect.result = result
        if provider_reference is not None:
            effect.provider_reference = provider_reference
        effect.resolved_at = now
        effect.updated_at = now
        await session.flush()
        return effect

    @staticmethod
    async def mark_failed(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        effect_id: uuid.UUID,
        *,
        error_details: dict[str, Any] | None = None,
    ) -> EffectLedger:
        """Mark effect as terminally failed."""
        effect = await session.scalar(
            select(EffectLedger)
            .where(
                EffectLedger.tenant_id == tenant_id,
                EffectLedger.effect_id == effect_id,
            )
            .with_for_update()
        )
        if not effect:
            raise NotFoundError(f"Effect {effect_id} not found")

        now = datetime.now(UTC)
        effect.status = "FAILED"
        if error_details is not None:
            effect.error_details = error_details
        effect.resolved_at = now
        effect.updated_at = now
        await session.flush()
        return effect

    @staticmethod
    async def mark_ambiguous(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        effect_id: uuid.UUID,
        *,
        error_details: dict[str, Any] | None = None,
    ) -> EffectLedger:
        """Mark effect as AMBIGUOUS (e.g. external provider timeout / unknown state)."""
        effect = await session.scalar(
            select(EffectLedger)
            .where(
                EffectLedger.tenant_id == tenant_id,
                EffectLedger.effect_id == effect_id,
            )
            .with_for_update()
        )
        if not effect:
            raise NotFoundError(f"Effect {effect_id} not found")

        now = datetime.now(UTC)
        effect.status = "AMBIGUOUS"
        if error_details is not None:
            effect.error_details = error_details
        effect.updated_at = now
        await session.flush()
        return effect

    @staticmethod
    async def reconcile_effect(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        effect_id: uuid.UUID,
        *,
        resolution_status: str,
        provider_reference: str | None = None,
        result: dict[str, Any] | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> EffectLedger:
        """Reconcile an AMBIGUOUS effect to COMPLETED or FAILED."""
        if resolution_status not in ("COMPLETED", "FAILED"):
            raise ValidationError("Resolution status must be COMPLETED or FAILED")

        effect = await session.scalar(
            select(EffectLedger)
            .where(
                EffectLedger.tenant_id == tenant_id,
                EffectLedger.effect_id == effect_id,
            )
            .with_for_update()
        )
        if not effect:
            raise NotFoundError(f"Effect {effect_id} not found")

        if effect.status != "AMBIGUOUS":
            raise ConflictError(f"Only AMBIGUOUS effects can be reconciled (current: {effect.status})")

        now = datetime.now(UTC)
        effect.status = resolution_status
        if provider_reference:
            effect.provider_reference = provider_reference
        if result:
            effect.result = result
        if error_details:
            effect.error_details = error_details
        effect.resolved_at = now
        effect.updated_at = now
        await session.flush()
        return effect
