"""Website builder domain models — presentation truth.

The website module owns pages, sections, versions, publishing, purchases and
the public read model (``website_published_sites``). It never owns business
truth: products / orders / customers stay in their own domains and are
referenced here by id only (e.g. ``ProductGridProps.collection_id``), never
copied.

Conventions (see core/model_kit.py): enum-like values are String columns with
CHECK constraints and are re-enforced in services; every table carrying
``tenant_id`` gets ENABLE + FORCE row level security plus a ``tenant_isolation``
policy from its migration. ``website_published_sites`` deliberately carries NO
``tenant_id`` column — it is the one table the unauthenticated public surface
reads, so the Boot Reconciler's every-tenant-table inspection does not apply
and the public renderer needs no tenant GUC to serve a live site.

Workspace/location scoping (§151) is intentionally absent: a website is a
tenant-wide entity, not a location-level one.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import AppendOnlyCreatedAtMixin, IdMixin, TenantMixin, TimestampMixin

WEBSITE_STATUSES = frozenset({"draft", "published", "suspended", "deleted"})
WEBSITE_VERSION_STATUSES = frozenset({"draft", "published", "archived"})
WEBSITE_PURCHASE_STATUSES = frozenset(
    {"pending_payment", "paid", "activated", "rejected", "cancelled"}
)
# A purchase in one of these states holds its slug claim (and blocks other
# tenants from taking it); a rejected/cancelled purchase frees the slug again.
WEBSITE_PURCHASE_OPEN_STATUSES = frozenset({"pending_payment", "paid"})
# The statuses whose slug stays claimed even after activation.
WEBSITE_PURCHASE_SLUG_HOLDING_STATUSES = frozenset({"pending_payment", "paid", "activated"})


class Website(TenantMixin, TimestampMixin, IdMixin, Base):
    __tablename__ = "websites"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default="draft", nullable=False)
    default_locale: Mapped[str] = mapped_column(String(8), server_default="ar", nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    theme_tokens: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    navigation: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # A pointer, deliberately not an FK: rollback re-points it between versions
    # and the published version row itself never disappears, so referential
    # enforcement would add a cycle (version -> website -> published_version).
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    aggregate_version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)

    __table_args__ = (
        UniqueConstraint("slug", name="uq_websites_slug"),
        CheckConstraint(
            "status IN ('draft','published','suspended','deleted')", name="ck_websites_status"
        ),
        # One website per tenant (v1): only non-deleted rows count, so an
        # offboarded tenant's history never blocks a fresh signup's slug reuse
        # of a DIFFERENT tenant — slug uniqueness itself is global above.
        Index(
            "uq_websites_one_live_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("status <> 'deleted'"),
        ),
    )


class WebsiteVersion(TenantMixin, TimestampMixin, IdMixin, Base):
    __tablename__ = "website_versions"

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default="draft", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','published','archived')", name="ck_website_versions_status"
        ),
        Index("ix_website_versions_website_status", "website_id", "status"),
    )


class WebsitePage(TenantMixin, TimestampMixin, IdMixin, Base):
    __tablename__ = "website_pages"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), nullable=False)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("version_id", "slug", name="uq_website_pages_version_slug"),)


class WebsitePageSection(TenantMixin, AppendOnlyCreatedAtMixin, IdMixin, Base):
    __tablename__ = "website_page_sections"

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_type: Mapped[str] = mapped_column(String(64), nullable=False)
    props: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    # Row-level optimistic-concurrency counter (editors must not clobber each
    # other's in-flight edit of the same section).
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)


class WebsitePurchase(TenantMixin, TimestampMixin, IdMixin, Base):
    """The one-time purchase of a website from a template.

    v1 money story: the tenant submits the purchase, pays off-platform (bank
    transfer / wallet), records the reference here, and a platform admin
    confirms — activation (website from template + first publish) happens in
    the SAME transaction as the confirmation. A real payment provider replaces
    the confirm endpoint later; the state machine already leaves ``paid`` as
    the intermediate state it would drive.
    """

    __tablename__ = "website_purchases"

    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), server_default="pending_payment", nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), server_default="EGP", nullable=False)
    site_name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    payment_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    website_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("websites.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_payment','paid','activated','rejected','cancelled')",
            name="ck_website_purchases_status",
        ),
        # One open purchase per tenant: a tenant either has a pending payment
        # or an active website — never two claims in flight.
        Index(
            "uq_website_purchases_one_open_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("status IN ('pending_payment','paid')"),
        ),
        # A claimed slug is held until the purchase leaves the open/activated
        # set; rejection/cancellation frees it for the next claimant.
        Index(
            "uq_website_purchases_claimed_slug",
            "slug",
            unique=True,
            postgresql_where=text("status IN ('pending_payment','paid','activated')"),
        ),
    )


class WebsitePublishedSite(IdMixin, TimestampMixin, Base):
    """The public read model — the ONLY row the unauthenticated surface reads.

    Deliberately NO ``tenant_id`` column: the Boot Reconciler inspects every
    table that carries one and demands RLS, and this table must be publicly
    readable without any tenant GUC. Everything the public renderer needs
    (projection, theme, navigation, locale, template) is snapshotted here in
    the SAME transaction as the publish, so Postgres stays the only truth and
    the public endpoint performs exactly one unbound SELECT.
    """

    __tablename__ = "website_published_sites"

    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Reserved for the subdomain phase: an explicit custom hostname binding.
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    default_locale: Mapped[str] = mapped_column(String(8), server_default="ar", nullable=False)
    theme_tokens: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    navigation: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    projection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("slug", name="uq_website_published_sites_slug"),
        Index(
            "uq_website_published_sites_hostname",
            "hostname",
            unique=True,
            postgresql_where=text("hostname IS NOT NULL"),
        ),
    )
