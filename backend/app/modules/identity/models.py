"""IDENTITY domain models — the only global (non-tenant-scoped) tables.

Users are platform-global; access to a tenant is granted through tenant_users
with a role. Every other module's tenant-scoped table FKs tenants.id.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.core.model_kit import AppendOnlyCreatedAtMixin, IdMixin, TimestampMixin


class Tenant(TimestampMixin, Base):
    """A tenant (customer account).

    Lifecycle (§48): ``lifecycle_state`` is the detailed state machine
    (provisioning | trial | active | past_due | grace | suspended |
    offboarding | deleted) and ``is_active`` is the coarse operational flag the
    existing queries already rely on. The two MUST never disagree:
    ``is_active`` is True only for the operational states (provisioning, trial,
    active, past_due, grace) and False for suspended / offboarding / deleted.
    TenantLifecycleService.transition is the single writer of both, so a state
    change can never leave the flag stale. Callers that need to ask "is this
    tenant allowed to X" use policy_for(state), not is_active — suspension is
    deliberately NOT "disable everything" (a suspended admin must still export
    their data, which is what makes offboarding possible).
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Detailed §48 lifecycle state — see the class docstring for the invariant
    # that ties it to is_active.
    lifecycle_state: Mapped[str] = mapped_column(String(31), server_default="active")
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Why the tenant is in its current (usually restrictive) state — without it
    # a suspended tenant is indistinguishable from a billing mistake.
    status_reason: Mapped[str | None] = mapped_column(String(255))


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, server_default="false")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(63), unique=True)  # owner | manager | staff
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1024))


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(127), unique=True)  # e.g. orders:read
    resource: Mapped[str] = mapped_column(String(63))
    action: Mapped[str] = mapped_column(String(63))


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        UUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class TenantUser(TimestampMixin, Base):
    __tablename__ = "tenant_users"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL")
    )
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false")


class RefreshToken(TimestampMixin, Base):
    """Server-side refresh token (hashed) enabling rotation + revocation."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)  # sha256 hex
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    ip: Mapped[str | None] = mapped_column(String(64))


class Invitation(TimestampMixin, Base):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL")
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    token: Mapped[str] = mapped_column(String(64), unique=True)
    # allowed: pending | accepted | revoked | expired
    status: Mapped[str] = mapped_column(String(15), server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Workspace(TimestampMixin, IdMixin, Base):
    """Workspace — first level of the tenancy hierarchy (spec §151).

    A tenant may split operations into workspaces; each workspace holds
    locations. Columns below are tenant-scoped; slug is unique per tenant.
    """

    __tablename__ = "workspaces"

    # uuid7 PK default — spec §142: ALL new tables use time-sortable ids
    # (overrides IdMixin's uuid4 default, which only predates that decision).
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(63))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),)


class Location(TimestampMixin, IdMixin, Base):
    """Location — a branch/outlet within a workspace (spec §151).

    code is unique per (tenant, workspace); NULL code rows are unconstrained
    (PG unique ignores NULLs) — they are locations without a business code.
    """

    __tablename__ = "locations"

    # uuid7 PK default — spec §142 (see Workspace).
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    code: Mapped[str | None] = mapped_column(String(31))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "code",
            name="uq_locations_tenant_workspace_code",
        ),
    )


class UserLocationAccess(AppendOnlyCreatedAtMixin, Base):
    """Grants a user access to a location, with optional role override (§151).

    Global table like tenant_users (no tenant_id of its own): tenancy resolves
    through the location row and RLS keys on app.user_id (location_access
    policy), so a member only reaches locations they were granted.
    """

    __tablename__ = "user_location_access"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_override: Mapped[str | None] = mapped_column(String(63))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
