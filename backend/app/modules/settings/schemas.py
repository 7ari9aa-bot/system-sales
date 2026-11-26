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
    # How a change reaches the runtime (§27): immediate, validated, approval_required.
    apply_mode: str = "validated"
    # Data sensitivity (§11, §76): normal, sensitive, secret.
    sensitivity: str = "normal"
    # Entitlement this setting belongs to (§72), if any.
    feature_requirement: str | None = None
    # Whether rollback to a previous revision is supported (§35).
    rollback_supported: bool = True
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
    # The latest history row id for this key+scope, for optimistic-concurrency
    # checks on write (§81). None when no history exists yet.
    latest_history_id: uuid.UUID | None = None
    definition: SettingDefOut


_SCOPE_PATTERN = "^(tenant|workspace|branch|warehouse|pos_profile|register|channel|user)$"


class SetSettingRequest(BaseModel):
    """Payload to create or update an override at a specific scope."""

    value: Any
    scope: str = Field(default="tenant", pattern=_SCOPE_PATTERN)
    scope_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=255)
    # Optimistic concurrency (§81): the history id the caller last saw.
    # If another write landed in between, the server returns 409.
    expected_history_id: uuid.UUID | None = None


class BulkSetSettingsRequest(BaseModel):
    """Payload to update multiple settings at once at a specific scope."""

    settings: dict[str, Any]
    scope: str = Field(default="tenant", pattern=_SCOPE_PATTERN)
    scope_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=255)
    # Optimistic concurrency (§81): per-key history ids the caller last saw.
    # If another write landed in between for any key, the server returns 409.
    expected_history_ids: dict[str, uuid.UUID | None] | None = None


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
    # Where the change came from: api | preset | restore | migration | rollback | change_request
    source: str = "api"
    created_at: str


class ChangeRequestOut(BaseModel):
    """A change request with its lifecycle state (§28)."""

    id: uuid.UUID
    changes: dict[str, Any]
    resets: list[str] = Field(default_factory=list)
    applied_changes: dict[str, Any] | None = None
    status: str
    scope: str
    scope_id: uuid.UUID | None = None
    submitted_by: uuid.UUID | None = None
    reviewed_by: uuid.UUID | None = None
    reason: str | None = None
    review_note: str | None = None
    created_at: str = ""
    updated_at: str = ""


class CreateChangeRequestInput(BaseModel):
    """Payload to create a change request for approval-gated settings.

    ``resets`` names settings the request will clear (remove the override). A clear is an
    operation, not a value, so it is listed here instead of being written as ``{key: None}``
    — which the per-type validator rejects for boolean, number and enum settings.
    """

    changes: dict[str, Any] = Field(default_factory=dict)
    resets: list[str] = Field(default_factory=list)
    scope: str = Field(default="tenant", pattern=_SCOPE_PATTERN)
    scope_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=255)


class ReviewChangeRequestInput(BaseModel):
    """Payload to approve or reject a change request."""

    review_note: str | None = Field(default=None, max_length=255)


class RollbackInput(BaseModel):
    """Payload to roll back a setting to a previous revision."""

    history_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=255)
    # Emergency bypass for APPROVAL_REQUIRED settings (requires settings:emergency_bypass).
    bypass_approval: bool = False


class RestoreSnapshotInput(BaseModel):
    """Payload to restore all tenant settings to a point in time (§164)."""

    snapshot_before: str = Field(
        ...,
        description="ISO 8601 timestamp — settings are restored to their state before this moment",
    )
    reason: str | None = Field(default=None, max_length=255)
    # Emergency bypass for APPROVAL_REQUIRED settings (requires settings:emergency_bypass).
    bypass_approval: bool = False


class MigrationLogOut(BaseModel):
    """One applied config migration for this tenant."""

    id: uuid.UUID
    migration_id: str
    description: str
    applied_by: uuid.UUID | None = None
    created_at: str


class RunMigrationsOut(BaseModel):
    """Result of running pending config migrations."""

    applied: list[str]
    current_version: str


class SettingPreviewEntryOut(BaseModel):
    """What would happen to one key — the answer a dry run exists to give."""

    key: str
    current: Any | None = None
    proposed: Any | None = None
    # change | unchanged | invalid
    action: str
    needs_approval: bool = False
    error: str | None = None


class SettingsPreviewOut(BaseModel):
    """A whole save, checked and not written."""

    scope: str
    scope_id: uuid.UUID | None = None
    keys: list[SettingPreviewEntryOut]
    # changes / unchanged / needs_approval / invalid — the counts the banner reads.
    summary: dict[str, int]
