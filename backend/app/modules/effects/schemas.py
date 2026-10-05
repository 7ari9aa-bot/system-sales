"""Schemas for the Effect Ledger module (V12 Wave C)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PAGE_LIMIT_DEFAULT = 50
PAGE_LIMIT_MAX = 200


def compute_effect_idempotency_key(
    tenant_id: str | uuid.UUID,
    operation: str,
    arguments: dict[str, Any] | None = None,
    workflow_id: str | None = None,
    task_id: str | None = None,
) -> str:
    """Deterministic idempotency key: H(tenant + operation + args + workflow + task)."""
    payload = {
        "tenant_id": str(tenant_id),
        "operation": operation.strip(),
        "workflow_id": (workflow_id or "").strip(),
        "task_id": (task_id or "").strip(),
        "arguments": arguments or {},
    }
    # default=str: callers may pass non-JSON natives (UUID, datetime,
    # Decimal) inside arguments — a bare dumps would raise TypeError and
    # take the whole intent down. str() is stable per process, which is all
    # a same-process idempotency key needs.
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class EffectIntentCreate(BaseModel):
    operation: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    workflow_id: str | None = Field(default=None, max_length=128)
    task_id: str | None = Field(default=None, max_length=128)
    decision_id: uuid.UUID | None = None
    lease_id: uuid.UUID | None = None
    provider: str | None = Field(default=None, max_length=64)


class EffectResolve(BaseModel):
    status: str = Field(pattern="^(COMPLETED|FAILED)$")
    provider_reference: str | None = Field(default=None, max_length=255)
    result: dict[str, Any] | None = None
    error_details: dict[str, Any] | None = None


class EffectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    effect_id: uuid.UUID
    tenant_id: uuid.UUID
    idempotency_key: str
    operation: str
    workflow_id: str | None = None
    task_id: str | None = None
    decision_id: uuid.UUID | None = None
    lease_id: uuid.UUID | None = None
    status: str
    provider: str | None = None
    provider_reference: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_details: dict[str, Any] | None = None
    attempts: int
    last_attempt_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class EffectListOut(BaseModel):
    items: list[EffectOut]
    total: int
    limit: int
    offset: int
