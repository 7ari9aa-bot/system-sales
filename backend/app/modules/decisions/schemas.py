"""DECISIONS module — pydantic response schemas for the HTTP surface.

Every route answers through a declared ``response_model`` (see the evidence
module's schemas header for the rationale). List envelopes are the house
``{items, total, limit, offset}`` page shape. ``tenant_id`` is deliberately
absent from every OUT model: it is the request context's, never echoed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

#: The page ceiling every paged decision list enforces (same rule as platform:
#: an unclamped ``limit`` is ``LIMIT -1`` — PostgreSQL for "every row").
PAGE_LIMIT_MAX = 200
PAGE_LIMIT_DEFAULT = 50


class DecisionOut(BaseModel):
    """One decision with its pins and its current machine state."""

    decision_id: uuid.UUID
    actor_id: uuid.UUID | None = None
    actor_type: str | None = None
    agent_id: uuid.UUID | None = None
    agent_version_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    intent: str | None = None
    action: str
    normalized_arguments: dict[str, Any] = Field(default_factory=dict)
    policy_version: int | None = None
    risk_level: str
    approval_state: str
    evidence_set_id: uuid.UUID | None = None
    evidence_set_hash: str | None = None
    dependency_snapshot_hash: str | None = None
    resource_versions: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    expires_at: datetime | None = None
    decision_status: str
    request_id: str | None = None
    trace_id: str | None = None
    conversation_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    content_hash: str
    command_hash: str | None = None


class DecisionListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DecisionOut]


class DependencyOut(BaseModel):
    """One pinned resource version from the decision's dependency snapshot."""

    dependency_id: uuid.UUID
    decision_id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    resource_version: int
    value_digest: str | None = None
    source: str | None = None
    source_version: str | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    freshness_sla_seconds: int | None = None
    classification: str
    content_hash: str
    created_at: datetime | None = None


class DependencyListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DependencyOut]
