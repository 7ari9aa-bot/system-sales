"""Tests for Effect Ledger module (V12 Wave C §30).

Unit tests using mock/fake async session (zero database required):
- Idempotency key determinism and canonical sorting
- Intent recording and idempotency deduplication
- Lifecycle transitions: PENDING -> EXECUTING -> COMPLETED / FAILED / AMBIGUOUS
- Ambiguous effect reconciliation
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.errors import ConflictError
from app.modules.effects.models import EffectLedger
from app.modules.effects.schemas import compute_effect_idempotency_key
from app.modules.effects.service import EffectService

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")


def test_idempotency_key_is_deterministic_and_key_order_independent():
    k1 = compute_effect_idempotency_key(
        TENANT_ID,
        operation="payment.charge",
        arguments={"amount": "100.00", "currency": "SAR", "customer_id": "c-1"},
        workflow_id="wf-1",
        task_id="t-1",
    )
    k2 = compute_effect_idempotency_key(
        TENANT_ID,
        operation="payment.charge",
        arguments={"customer_id": "c-1", "currency": "SAR", "amount": "100.00"},  # shuffled order
        workflow_id="wf-1",
        task_id="t-1",
    )
    assert k1 == k2
    assert len(k1) == 64

    # Changes when any parameter changes
    k3 = compute_effect_idempotency_key(
        OTHER_TENANT,
        operation="payment.charge",
        arguments={"amount": "100.00", "currency": "SAR", "customer_id": "c-1"},
        workflow_id="wf-1",
        task_id="t-1",
    )
    assert k1 != k3


class _MockSession:
    def __init__(self, entities: list[Any] | None = None) -> None:
        self.entities = entities or []
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self.entities.append(obj)

    async def flush(self) -> None:
        pass

    async def scalar(self, stmt: Any) -> Any:
        # Simple lookup helper for test mock
        for e in self.entities:
            if hasattr(e, "effect_id"):
                return e
        return None


@pytest.mark.asyncio
async def test_record_intent_creates_new_effect():
    session = _MockSession()
    effect = await EffectService.record_intent(
        session,  # type: ignore[arg-type]
        TENANT_ID,
        operation="shipping.label.create",
        arguments={"weight_kg": 1.5},
        workflow_id="wf-ship",
        task_id="t-ship-1",
    )
    assert effect.tenant_id == TENANT_ID
    assert effect.operation == "shipping.label.create"
    assert effect.status == "PENDING"
    assert effect.attempts == 0
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_record_intent_returns_existing_on_idempotency_collision():
    existing = EffectLedger(
        tenant_id=TENANT_ID,
        idempotency_key=compute_effect_idempotency_key(
            TENANT_ID, "order.sync", {"order_id": "123"}
        ),
        operation="order.sync",
        status="COMPLETED",
    )
    session = _MockSession([existing])

    effect = await EffectService.record_intent(
        session,  # type: ignore[arg-type]
        TENANT_ID,
        operation="order.sync",
        arguments={"order_id": "123"},
    )
    assert effect is existing
    assert effect.status == "COMPLETED"
    assert len(session.added) == 0


@pytest.mark.asyncio
async def test_effect_lifecycle_transitions():
    effect = EffectLedger(
        effect_id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        idempotency_key="key-1",
        operation="sms.send",
        status="PENDING",
        attempts=0,
    )
    session = _MockSession([effect])

    # 1. Mark executing
    await EffectService.mark_executing(session, TENANT_ID, effect.effect_id)  # type: ignore[arg-type]
    assert effect.status == "EXECUTING"
    assert effect.attempts == 1
    assert effect.last_attempt_at is not None

    # 2. Mark completed
    await EffectService.mark_completed(  # type: ignore[arg-type]
        session,
        TENANT_ID,
        effect.effect_id,
        result={"message_id": "msg_999"},
        provider_reference="prov_ref_abc",
    )
    assert effect.status == "COMPLETED"
    assert effect.result == {"message_id": "msg_999"}
    assert effect.provider_reference == "prov_ref_abc"
    assert effect.resolved_at is not None

    # 3. Trying to execute an already completed effect raises ConflictError
    with pytest.raises(ConflictError):
        await EffectService.mark_executing(session, TENANT_ID, effect.effect_id)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ambiguous_effect_and_reconciliation():
    effect = EffectLedger(
        effect_id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        idempotency_key="key-2",
        operation="payment.charge",
        status="EXECUTING",
        attempts=1,
    )
    session = _MockSession([effect])

    # Mark ambiguous on gateway timeout
    await EffectService.mark_ambiguous(  # type: ignore[arg-type]
        session,
        TENANT_ID,
        effect.effect_id,
        error_details={"code": "gateway_timeout", "reason": "No ACK from processor"},
    )
    assert effect.status == "AMBIGUOUS"
    assert effect.error_details["code"] == "gateway_timeout"

    # Reconcile to COMPLETED
    await EffectService.reconcile_effect(  # type: ignore[arg-type]
        session,
        TENANT_ID,
        effect.effect_id,
        resolution_status="COMPLETED",
        provider_reference="ch_verified_123",
        result={"reconciled": True},
    )
    assert effect.status == "COMPLETED"
    assert effect.provider_reference == "ch_verified_123"
    assert effect.resolved_at is not None

    # Reconciling an already completed effect raises ConflictError
    with pytest.raises(ConflictError):
        await EffectService.reconcile_effect(  # type: ignore[arg-type]
            session,
            TENANT_ID,
            effect.effect_id,
            resolution_status="FAILED",
        )
