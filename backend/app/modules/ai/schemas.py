"""AI module API schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeIngestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source_type: str = "text"  # text | file | url | qa
    source_ref: str | None = None


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    model: str | None = Field(default=None, max_length=127)
    system_prompt: str | None = None
    description: str | None = None


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    model: str | None
    is_active: bool


class ToolCallOut(BaseModel):
    name: str
    status: str
    error: str | None = None
