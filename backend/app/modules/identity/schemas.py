"""Identity module — pydantic request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """email + password only is the minimal signup contract; the tenant
    name/slug and display name are derived server-side when omitted."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str | None = Field(default=None, max_length=255)
    tenant_slug: str | None = Field(default=None, max_length=63, pattern=r"^[a-z0-9-]+$")
    full_name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class SwitchTenantRequest(RefreshRequest):
    """§125: tenancy is the request context's, never a URL parameter.

    The target tenant rides the typed body — a query string is logged, cached
    and echoed by every hop between here and the user's finger — and the
    service still verifies membership server-side before minting anything.
    """

    tenant_id: uuid.UUID


class CurrentTenant(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    role_code: str | None = None


class CurrentUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_platform_admin: bool
    tenants: list[CurrentTenant] = []


class InviteRequest(BaseModel):
    email: EmailStr
    role_code: str = "staff"


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role_code: str | None
    status: str
    expires_at: datetime
    token: str  # shown once to the inviting admin


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=16, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


# --- §151 hierarchy (workspaces / locations / location access) -------------


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9-]+$")


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    slug: str
    is_active: bool


class WorkspaceListOut(BaseModel):
    items: list[WorkspaceOut]


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=31)


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=31)
    is_active: bool | None = None


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    code: str | None
    is_active: bool


class LocationListOut(BaseModel):
    items: list[LocationOut]


class LocationAccessGrant(BaseModel):
    """PUT body — role_override is the only mutable grant attribute."""

    role_override: str | None = Field(default=None, max_length=63)


class LocationAccessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    location_id: uuid.UUID
    role_override: str | None
    granted_by: uuid.UUID | None


class LocationAccessListOut(BaseModel):
    items: list[LocationAccessOut]
