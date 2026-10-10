"""Wire contracts for the merchant SI chat — spec §SI-chat.

The render-block vocabulary is CLOSED: the renderer rejects unknown types, and
blocks are always server-built from a validated AnalysisResult — never
model-authored JSON. Money values ride as strings (§47/ADR-001); the frontend
formats for display only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.analytics.contracts import Finding


class ThreadContextIn(BaseModel):
    period: str | None = None
    filters: dict[str, str] = Field(default_factory=dict)


class ThreadCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    context: ThreadContextIn | None = None


class ThreadUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    status: Literal["active", "archived"] | None = None


class ThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
    context: dict
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


class TextBlock(BaseModel):
    type: Literal["text"]
    body: str


class KpiBlock(BaseModel):
    type: Literal["kpi"]
    metric: str
    label: str
    value: str
    unit: str
    window: str


class FindingsBlock(BaseModel):
    type: Literal["findings"]
    items: list[Finding]


class NoticeBlock(BaseModel):
    type: Literal["notice"]
    severity: Literal["info", "warning"]
    message: str


class RefsBlock(BaseModel):
    type: Literal["refs"]
    analysis_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None


Blocks = Annotated[
    TextBlock | KpiBlock | FindingsBlock | NoticeBlock | RefsBlock,
    Field(discriminator="type"),
]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    sequence_no: int
    role: str
    status: str
    content: str
    structured_content: list[Blocks] | None
    run_id: uuid.UUID | None
    analysis_id: uuid.UUID | None
    error_code: str | None
    created_at: datetime


class MessageSendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    idempotency_key: str | None = Field(default=None, max_length=64)
