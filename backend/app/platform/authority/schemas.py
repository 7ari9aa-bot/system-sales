"""AUTHORITY module — Pydantic request and response schemas (V12 Wave B).

Declared response shapes for Capability Grants, Authority Leases, and Autonomy Budgets.
Tenant IDs are strictly scoped via context and never echoed in OUT models.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

PAGE_LIMIT_MAX = 200
PAGE_LIMIT_DEFAULT = 50


class CapabilityGrantCreate(BaseModel):
    decision_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    actor_type: str | None = Field(default="system")
    tool_name: str
    scope: dict[str, Any] = Field(default_factory=dict)
    max_budget: Decimal | None = None
    currency: str = "USD"
    ttl_seconds: int = Field(default=3600, ge=10, le=86400 * 30)


class CapabilityGrantOut(BaseModel):
    grant_id: uuid.UUID
    decision_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    actor_type: str | None = None
    tool_name: str
    scope: dict[str, Any] = Field(default_factory=dict)
    max_budget: Decimal | None = None
    currency: str
    status: str
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CapabilityGrantListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CapabilityGrantOut]


class MintLeaseRequest(BaseModel):
    grant_id: uuid.UUID
    decision_id: uuid.UUID
    command_hash: str = Field(description="Deterministic sha256:... from canonical_json")
    expected_versions: dict[str, int] = Field(
        default_factory=dict,
        description="Resource versions that must match at execution time",
    )
    ttl_seconds: int = Field(default=60, ge=1, le=60, description="Lease TTL; strictly <= 60s")
    budget_amount: Decimal | None = None
    budget_id: uuid.UUID | None = None


class MintLeaseResponse(BaseModel):
    lease_id: uuid.UUID
    lease_token: str = Field(description="Bearer execution token (only revealed once at mint time)")
    grant_id: uuid.UUID
    decision_id: uuid.UUID
    command_hash: str
    expected_versions: dict[str, int]
    state: str
    ttl_seconds: int
    expires_at: datetime
    reserved_budget: Decimal | None = None
    created_at: datetime


class AuthorityLeaseOut(BaseModel):
    lease_id: uuid.UUID
    grant_id: uuid.UUID
    decision_id: uuid.UUID
    command_hash: str
    expected_versions: dict[str, int]
    nonce: str
    state: str
    ttl_seconds: int
    expires_at: datetime
    reserved_budget: Decimal | None = None
    redeemed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AuthorityLeaseListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuthorityLeaseOut]


class AutonomyBudgetCreate(BaseModel):
    actor_id: uuid.UUID | None = None
    parent_budget_id: uuid.UUID | None = None
    name: str
    period: str = Field(default="DAILY")
    currency: str = "USD"
    total_limit: Decimal = Field(gt=0)


class AutonomyBudgetOut(BaseModel):
    budget_id: uuid.UUID
    actor_id: uuid.UUID | None = None
    parent_budget_id: uuid.UUID | None = None
    name: str
    period: str
    currency: str
    total_limit: Decimal
    spent_amount: Decimal
    reserved_amount: Decimal
    available_amount: Decimal
    reset_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExecuteCommandRequest(BaseModel):
    """Payload to execute an approved command via an Authority Lease."""

    lease_token: str = Field(description="Plaintext bearer lease token")
    action: str
    resource: dict[str, Any] = Field(default_factory=dict)
    arguments: dict[str, Any] = Field(default_factory=dict)
    purpose: str
    current_versions: dict[str, int] = Field(
        default_factory=dict,
        description="Current observed versions of affected resources",
    )


class ExecutionResultOut(BaseModel):
    success: bool
    lease_id: uuid.UUID
    decision_id: uuid.UUID
    effect_id: uuid.UUID | None = None
    mutation_result: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime
