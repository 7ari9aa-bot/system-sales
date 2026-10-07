"""IDENTITY domain models — the only global (non-tenant-scoped) tables.

Users are platform-global; access to a tenant is granted through tenant_users
with a role. Every other module's tenant-scoped table FKs tenants.id.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    # §47: the ONE currency this tenant trades in. Every money column in the
    # system is NUMERIC(14,2), so this is restricted to a two-decimal currency
    # (see TenantService.set_currency) — an amount stored here is always the
    # amount the customer paid, never a converted one.
    currency: Mapped[str] = mapped_column(String(3), default="EGP", server_default="EGP")
    # §47/M10 remainder: the ONE zone this tenant counts its DAYS in, the same
    # move `currency` made for money. Analytics buckets a calendar day (gap
    # M10), and until now the zone could only come from one deployment-wide
    # setting — a Cairo shop and a Dubai shop shared a "day". NULL is not a
    # missing value, it is an answer: "no opinion, use the deployment zone",
    # which is what every row written before this column existed means. The
    # value is validated against the IANA database at the write boundary
    # (TenantSettingsService.set_timezone); the DB check bounds the SHAPE only,
    # because resolvability needs tzdata, which lives in Python, not here.
    timezone: Mapped[str | None] = mapped_column(String(64))


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # Case-folded uniqueness: identity writes lower(email) everywhere, and
    # the schema enforces it so two case-variant accounts can never exist.
    __table_args__ = (sa.Index("ix_users_email_lower", sa.func.lower(email), unique=True),)

    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Account pre-hijack guard (external audit): an account whose email was
    # never proven is a landmine — an attacker can register a victim's address
    # BEFORE the victim signs up, and an invitation to that address would then
    # bind the victim's future role to the attacker's account. Verified email
    # is what makes an existing account bindable (accept_invitation refuses
    # unverified ones) — proving inbox control is the only thing that
    # distinguishes the legitimate owner from the pre-hijacker. Login is
    # deliberately NOT gated on this: the column is backfilled true for
    # accounts that predate it (migration fd2026100411), and password reset
    # sets it (a completed reset proves inbox control the same way).
    email_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Bumped by password-reset and other account-wide credential changes.
    # Access JWTs carry this value, so a password reset immediately invalidates
    # already-issued access tokens as well as the refresh-token family.
    auth_version: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)


class PasswordResetToken(TimestampMixin, Base):
    """Single-use reset token plus its encrypted, retryable delivery payload.

    The hash is used for validation. The raw token is only retained encrypted
    while delivery is pending; successful/terminal delivery clears it.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    encrypted_token: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        Index("ix_password_reset_user_requested", "user_id", "requested_at"),
        Index(
            "ix_password_reset_delivery_due",
            "next_attempt_at",
            "lease_expires_at",
            postgresql_where=text(
                "sent_at IS NULL AND consumed_at IS NULL AND delivery_failed_at IS NULL"
            ),
        ),
    )


class EmailVerificationToken(TimestampMixin, Base):
    """Single-use email-verification token, shaped like PasswordResetToken.

    Same economics as the reset flow (external audit, account pre-hijack): the
    hash validates the attempt, the raw token is retained encrypted only while
    delivery is pending, and the leased delivery worker (email_delivery.py)
    owns retries. It is a GLOBAL pre-GUC possession table exactly like
    password_reset_tokens — verification runs before any tenant context exists
    — so migration fd2026100411 gives it the same RLS posture: permissive
    SELECT/INSERT/UPDATE (the queue cannot work otherwise), no DELETE policy.
    """

    __tablename__ = "email_verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    encrypted_token: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        Index("ix_email_verification_user_requested", "user_id", "requested_at"),
        Index(
            "ix_email_verification_delivery_due",
            "next_attempt_at",
            "lease_expires_at",
            postgresql_where=text(
                "sent_at IS NULL AND consumed_at IS NULL AND delivery_failed_at IS NULL"
            ),
        ),
    )


class UserMfaSecret(TimestampMixin, Base):
    """§146: one TOTP secret per user — the durable half of MFA.

    Global table like `users` (no tenant_id, no RLS): the secret belongs to
    the user, not to one of their memberships, and the login-time MFA check
    runs before any tenant GUC exists. `enabled_at` NULL means enrollment was
    started but never confirmed — only an ENABLED row challenges logins.
    Backup codes persist as sha256 hashes only; the plaintext is shown once
    at confirm time.
    """

    __tablename__ = "user_mfa_secrets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    # base64 of the base32 secret — envelope encryption lands with the §68/69 work.
    totp_secret_encrypted: Mapped[str] = mapped_column(String(255))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backup_codes_hashes: Mapped[list] = mapped_column(JSONB, server_default="[]")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(63), unique=True)  # owner | manager | staff
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1024))


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
