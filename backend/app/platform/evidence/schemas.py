"""EVIDENCE module — pydantic response schemas for the HTTP surface.

Every route answers through a declared ``response_model``: an untyped route
contributes ``"schema": {}`` to the published OpenAPI document, which is
OpenAPI for "any JSON anywhere" (see the platform module's schemas header for
the full rationale). The models mirror exactly what the handlers emit — a
response model silently DROPS undeclared keys, so an accurate mirror is the
only safe edit.

List envelopes are the house ``{items, total, limit, offset}`` page shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

#: The page ceiling every paged evidence list enforces (same rule as platform:
#: an unclamped ``limit`` is ``LIMIT -1`` — PostgreSQL for "every row").
PAGE_LIMIT_MAX = 200
PAGE_LIMIT_DEFAULT = 50


class FactOut(BaseModel):
    """One immutable evidence fact (V12 §9)."""

    fact_id: uuid.UUID
    subject_type: str | None = None
    subject_id: uuid.UUID | None = None
    claim: str
    claim_type: str | None = None
    source: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_version: int | None = None
    resource_version: int | None = None
    freshness_sla_seconds: int | None = None
    confidence: float | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    classification: str
    content_hash: str
    trust: str
    created_at: datetime | None = None


class FactListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[FactOut]


class SetOut(BaseModel):
    """One assembled evidence set plus its derived provenance flags."""

    evidence_set_id: uuid.UUID
    fact_ids: list[uuid.UUID]
    fact_count: int
    evidence_set_hash: str
    decision_id: uuid.UUID | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class SetListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SetOut]
