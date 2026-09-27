"""AUTHORITY domain models — CapabilityGrants, AuthorityLeases, AutonomyBudgets (V12 Wave B).

The core rule:
PROPOSAL ≠ DECISION ≠ CAPABILITY ≠ AUTHORITY ≠ EXECUTION ≠ EFFECT ≠ FINANCIAL RESULT

- CapabilityGrant: The durable grant issued upon decision approval (or direct human/admin policy)
  defining permitted action, scope, and upper budget boundary.
- AuthorityLease: The ephemeral, cryptographically bound, single-use token granting execution
  authority with TTL <= 60s, bound to a canonical command_hash and expected resource versions.
- AutonomyBudget: Sliced parent/child budget hierarchies bounding autonomous agent and
  automated actions.
- BudgetReservation: Holds on budgets while authority leases are in flight.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import TenantMixin

GRANT_STATUSES: frozenset[str] = frozenset({"ACTIVE", "REVOKED", "EXPIRED", "CONSUMED"})
LEASE_STATES: frozenset[str] = frozenset({"MINTED", "ACTIVE", "EXECUTED", "REVOKED", "EXPIRED"})
RESERVATION_STATUSES: frozenset[str] = frozenset({"RESERVED", "COMMITTED", "RELEASED"})
BUDGET_PERIODS: frozenset[str] = frozenset(
    {"DAILY", "WEEKLY", "MONTHLY", "PER_TRANSACTION", "LIFETIME"}
)

#: V12 canonical TTL for authority leases: strictly <= 60 seconds
MAX_LEASE_TTL_SECONDS = 60


class CapabilityGrant(TenantMixin, Base):
    """Authorizes an actor or tool within defined scope and budget boundaries."""

    __tablename__ = "capability_grants"

    grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[str | None] = mapped_column(String(31))
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    max_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(15), server_default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(31), server_default="ACTIVE", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_capability_grants_tenant_tool", "tenant_id", "tool_name"),
        Index("ix_capability_grants_tenant_status", "tenant_id", "status"),
        Index("ix_capability_grants_decision", "decision_id"),
    )


class AuthorityLease(TenantMixin, Base):
    """Ephemeral, single-use execution authority bound to a command_hash and resource versions.

    Invariant 10: Single-use, cryptographically verified, bound to command_hash, TTL <= 60s.
    """

    __tablename__ = "authority_leases"

    lease_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lease_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # "sha256:" + 64 hex chars:
    command_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    expected_versions: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(31), server_default="MINTED", nullable=False)
    ttl_seconds: Mapped[int] = mapped_column(Integer, server_default="60", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reserved_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_authority_leases_tenant_state", "tenant_id", "state"),
        Index("ix_authority_leases_tenant_decision", "tenant_id", "decision_id"),
        Index("ix_authority_leases_token_hash", "lease_token_hash"),
        Index("ix_authority_leases_tenant_nonce", "tenant_id", "nonce", unique=True),
    )


class AutonomyBudget(TenantMixin, Base):
    """Parent-sliced budget tracking for agents and automated processes (V12 §25)."""

    __tablename__ = "autonomy_budgets"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    parent_budget_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(127), nullable=False)
    period: Mapped[str] = mapped_column(String(31), server_default="DAILY", nullable=False)
    currency: Mapped[str] = mapped_column(String(15), server_default="USD", nullable=False)
    total_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    spent_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), server_default="0", nullable=False
    )
    reserved_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), server_default="0", nullable=False
    )
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_autonomy_budgets_tenant", "tenant_id"),
        Index("ix_autonomy_budgets_parent", "parent_budget_id"),
    )


class BudgetReservation(TenantMixin, Base):
    """In-flight reservation against an AutonomyBudget while a lease is active."""

    __tablename__ = "budget_reservations"

    reservation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    budget_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lease_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(31), server_default="RESERVED", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_budget_reservations_tenant_budget", "tenant_id", "budget_id"),
        Index("ix_budget_reservations_lease", "lease_id"),
    )
