"""Identity module — pydantic request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    tenant_name: str = Field(min_length=1, max_length=255)
    tenant_slug: str = Field(min_length=3, max_length=63, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


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
