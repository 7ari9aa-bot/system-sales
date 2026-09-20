"""BILLING domain models — plans, subscriptions, entitlements, usage records,
invoices.

plans is a global (non-tenant) catalog table; every other table is
tenant-scoped (TenantMixin first) so RLS policies and sharding conventions
apply uniformly.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    MONEY,
    AppendOnlyCreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    WorkspaceScopeMixin,
)


class Plan(IdMixin, TimestampMixin, Base):
    """Global plan catalog — not tenant-scoped."""

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(31))
    name: Mapped[str] = mapped_column(String(255))
    price: Mapped[float] = mapped_column(MONEY, default=0, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), server_default="EGP")
    # interval: month | year
    interval: Mapped[str] = mapped_column(String(15), server_default="month")
    features: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = (UniqueConstraint("code", name="uq_plans_code"),)


class Subscription(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT")
    )
    # status: trialing | active | past_due | canceled | expired
    status: Mapped[str] = mapped_column(String(15), server_default="trialing")
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(default=False, server_default="false")

    __table_args__ = (
        Index("ix_subscriptions_tenant_status", "tenant_id", "status"),
    )


class Entitlement(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    __tablename__ = "entitlements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE")
    )
    feature: Mapped[str] = mapped_column(String(63))
    limit_value: Mapped[int | None] = mapped_column()
    is_unlimited: Mapped[bool] = mapped_column(default=False, server_default="false")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "subscription_id",
            "feature",
            name="uq_entitlements_tenant_subscription_feature",
        ),
    )


class UsageRecord(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, Base):
    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # feature: ai_tokens | messages | orders
    feature: Mapped[str] = mapped_column(String(63))
    quantity: Mapped[float] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    period_date: Mapped[date] = mapped_column(Date)
    extra: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        Index(
            "ix_usage_records_tenant_feature_period",
            "tenant_id",
            "feature",
            "period_date",
        ),
    )


class Invoice(TenantMixin, TimestampMixin, WorkspaceScopeMixin, Base):
    """A bill, and — when it carries a period — an immutable billing snapshot.

    Two rows share this table, and the difference is the period:

    * ``period_start IS NULL`` — an ordinary invoice. Its lifecycle columns
      (``status`` draft -> open -> paid -> void, ``issued_at``/``due_at``/
      ``paid_at``, ``provider_ref``) are meant to be written.
    * ``period_start IS NOT NULL`` — the FROZEN snapshot `close_period` wrote for
      that period. Spec §53–54 makes it immutable, and that is enforced by the
      DATABASE (a BEFORE UPDATE OR DELETE trigger created in migration
      ``e7a8b9c0d1e2``), not by convention: a direct SQL client must be refused
      too. The trigger allows the mutation only while the owning tenant is being
      torn down, because the FK cascades from ``tenants``/``subscriptions``
      delete and null these rows as a side effect of offboarding.
    """

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    number: Mapped[str] = mapped_column(String(31))
    # status: draft | open | paid | void | uncollectible
    status: Mapped[str] = mapped_column(String(15), server_default="draft")
    subtotal: Mapped[float] = mapped_column(MONEY, default=0, server_default="0")
    tax: Mapped[float] = mapped_column(MONEY, default=0, server_default="0")
    total: Mapped[float] = mapped_column(MONEY, default=0, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), server_default="EGP")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # provider: stripe | manual
    provider: Mapped[str | None] = mapped_column(String(15))
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    # Spec §53–54: the billing period this row is the FROZEN SNAPSHOT of.
    #
    # These were missing: the period only lived inside `extra` JSONB, where it
    # cannot be constrained or indexed, so nothing stopped a second snapshot
    # being written for a period that was already closed — which is the whole
    # immutability guarantee. Nullable because rows created before period
    # snapshots existed have no period; NULLs are distinct in a UNIQUE
    # constraint, so legacy rows never collide with each other.
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The frozen per-feature breakdown: [{"feature": ..., "quantity": "12.00"}].
    #
    # This column did not exist. The original `BillingSnapshotService` passed
    # `extra=` to this constructor, so it was not merely DEAD code — it was
    # never runnable, and a TypeError was waiting for the first caller. That is
    # the likeliest reason nobody ever called it.
    #
    # Quantities are stored as STRINGS: every Python JSON path decodes a number
    # to an IEEE float, so a Numeric(14,2) total would silently lose precision
    # on the way into JSONB. Strings round-trip exactly.
    extra: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_invoices_tenant_number"),
        # "A period is closed at most once", per tenant. An application-level
        # "already closed?" check is a check-then-insert race; only the database
        # can serialise two concurrent closes.
        #
        # This constraint is NOT what makes a closed invoice immutable — it only
        # stops a SECOND snapshot for the same period. Editing the row that is
        # already frozen is refused by the BEFORE UPDATE OR DELETE trigger in
        # migration `e7a8b9c0d1e2`; both halves are needed, and neither is
        # enforced by application code alone.
        UniqueConstraint(
            "tenant_id",
            "period_start",
            "period_end",
            name="uq_invoices_tenant_period",
        ),
    )
