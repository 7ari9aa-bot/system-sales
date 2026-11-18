"""Pydantic schemas for the Settings module API."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class SettingDefOut(BaseModel):
    """Metadata describing a single setting definition."""

    key: str
    domain: str
    type: str
    default: Any
    scopes: list[str]
    allowed_values: list[str] | None = None
    min_value: float | None = None
    max_value: float | None = None
    max_length: int | None = None
    permission: str
    audit: bool
    # False = stored and shown, but nothing reads it yet: changing it changes no behaviour.
    enforced: bool
    # Business segments this applies to; empty = every segment.
    segments: list[str] = []
    label_ar: str
    label_en: str
    description_ar: str
    description_en: str


class ResolvedSettingOut(BaseModel):
    """The resolved effective value of a setting with inheritance details."""

    key: str
    value: Any
    scope: str
    scope_id: uuid.UUID | None = None
    is_inherited: bool
    is_default: bool
    definition: SettingDefOut


_SCOPE_PATTERN = "^(tenant|branch|warehouse|pos_profile|register|channel|user)$"


class SetSettingRequest(BaseModel):
    """Payload to create or update an override at a specific scope."""

    value: Any
    scope: str = Field(default="tenant", pattern=_SCOPE_PATTERN)
    scope_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=255)


class BulkSetSettingsRequest(BaseModel):
    """Payload to update multiple settings at once at a specific scope."""

    settings: dict[str, Any]
    scope: str = Field(default="tenant", pattern=_SCOPE_PATTERN)
    scope_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=255)


class ResetSettingRequest(BaseModel):
    """Payload to remove an override and revert to inherited value."""

    scope: str = Field(default="tenant", pattern=_SCOPE_PATTERN)
    scope_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=255)


class TenantSettingOut(BaseModel):
    """Raw override record from the database."""

    id: uuid.UUID
    key: str
    scope: str
    scope_id: uuid.UUID | None = None
    value: Any
    updated_by: uuid.UUID | None = None


class SettingHistoryOut(BaseModel):
    """Audit log entry for a configuration change."""

    id: uuid.UUID
    setting_id: uuid.UUID | None = None
    key: str
    scope: str
    scope_id: uuid.UUID | None = None
    old_value: Any = None
    new_value: Any = None
    action: str
    changed_by: uuid.UUID | None = None
    change_reason: str | None = None
    created_at: str
