"""Commercial rows for applications: what is sold, what a plan includes, what a workspace installed.

What an application *does* lives in ``manifests.py``, in the release. What it
costs and who bought it lives here, in data — because pricing and entitlements
change without a deploy while behaviour must not.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import TimestampMixin, WorkspaceScopeMixin


class PlanApplicationInclusion(TimestampMixin, Base):
    """An application a plan includes without buying it as an add-on."""

    __tablename__ = "plan_application_inclusions"
    __table_args__ = (UniqueConstraint("plan_id", "application_key", name="uq_plan_app_inclusion"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    application_key: Mapped[str] = mapped_column(String(64))


class SubscriptionItem(TimestampMixin, Base):
    """One line of a subscription: an application bought, optionally for one business only.

    ``workspace_id`` NULL means the line covers every business in the account;
    a value pins the purchase to that business, which is how two shops in one
    account end up with different products.
    """

    __tablename__ = "subscription_items"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "application_key", "workspace_id", name="uq_subscription_item_scope"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    application_key: Mapped[str] = mapped_column(String(64))
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )


class WorkspaceAppInstallation(TimestampMixin, WorkspaceScopeMixin, Base):
    """Whether an application is installed in a business, and how far its setup got.

    Licensed is not installed and installed is not active: a customer who paid for
    purchasing but never added a supplier sits at ``setup_required`` and the screen
    stays closed until the setup flow finishes.
    """

    __tablename__ = "workspace_app_installations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "application_key", name="uq_workspace_app_installation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    application_key: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="not_installed")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    setup_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
