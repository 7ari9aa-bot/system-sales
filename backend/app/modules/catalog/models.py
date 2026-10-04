"""CATALOG domain models — products blueprint.

brands/categories/products/product_variants form the catalog core;
product_images and product_prices are append-only (no updated_at).
Enum-like columns are String with allowed values documented inline — never
sa.Enum (avoids PG ENUM migration churn).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
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


class Brand(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "brands"

    name: Mapped[str] = mapped_column(String(255))

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_brands_tenant_name"),)


class Category(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )


class Product(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "products"

    title: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="SET NULL"),
        nullable=True,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    # allowed: draft | active | archived
    status: Mapped[str] = mapped_column(String(15), server_default="draft")
    attributes: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    # §45 full text — DATABASE-DERIVED, never assign. `simple` is pinned because
    # a GENERATED column needs an IMMUTABLE expression and the 1-argument
    # to_tsvector is only STABLE; it is also the only configuration that treats
    # mixed Arabic+Latin titles without stemming one of them. Migration
    # b2e3d4f5a6c7 carries the reasoning. `sku`/variant titles are deliberately
    # NOT here — they are substring lookups, which is trigram work, not tsvector.
    search_ts: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "(setweight(to_tsvector('simple', coalesce(title, '')), 'A') "
            "|| setweight(to_tsvector('simple', coalesce(description, '')), 'B'))",
            persisted=True,
        ),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_products_tenant_slug"),
        Index("ix_products_tenant_status", "tenant_id", "status"),
    )


class ProductVariant(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    __tablename__ = "product_variants"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE")
    )
    sku: Mapped[str | None] = mapped_column(String(63), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    option_values: Mapped[dict] = mapped_column(JSONB, server_default="{}")  # e.g. {"size": "M"}
    price: Mapped[Decimal] = mapped_column(MONEY)
    compare_at_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_product_variants_tenant_sku"),
        Index("ix_product_variants_tenant_product", "tenant_id", "product_id"),
    )


class ProductImage(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Append-only image gallery entries."""

    __tablename__ = "product_images"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE")
    )
    # Nullable: a product-level gallery shot; SET NULL keeps the gallery when
    # a variant is removed (§179 media binding, gap CC3).
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="SET NULL"),
        nullable=True,
    )
    url: Mapped[str] = mapped_column(Text)
    alt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[int] = mapped_column(Integer, server_default="0")


class ProductPrice(TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base):
    """Append-only price history per variant/currency/quantity tier."""

    __tablename__ = "product_prices"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    currency: Mapped[str] = mapped_column(String(3), server_default="EGP")
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    min_quantity: Mapped[int] = mapped_column(Integer, server_default="1")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "variant_id",
            "currency",
            "min_quantity",
            name="uq_product_prices_tenant_variant_currency_min_qty",
        ),
    )


class ProductIdentifier(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """Append-only scan code on one sellable unit (Commerce Core v1.0 §179).

    `type` is the closed vocabulary {gtin, ean, upc, barcode, qr_token,
    external} enforced in CatalogService — never sa.Enum. (tenant, type,
    value) is unique so the resolver returns exactly one variant or nothing.
    Corrections delete and re-add; the rows are facts, not state.
    """

    __tablename__ = "product_identifiers"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(31))
    value: Mapped[str] = mapped_column(String(127))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "type",
            "value",
            name="uq_product_identifiers_tenant_type_value",
        ),
    )


class ProductOption(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """One option axis on a product (§179) — e.g. "size", "color"."""

    __tablename__ = "product_options"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(63))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "product_id", "name", name="uq_product_options_tenant_product_name"
        ),
    )


class ProductOptionValue(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """One selectable value of an option axis — "M" of "size"."""

    __tablename__ = "product_option_values"

    option_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_options.id", ondelete="CASCADE")
    )
    value: Mapped[str] = mapped_column(String(127))

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "option_id", "value", name="uq_product_option_values_tenant_option_value"
        ),
    )


class ProductVariantOptionValue(
    TenantMixin, AppendOnlyCreatedAtMixin, WorkspaceScopeMixin, IdMixin, Base
):
    """The variant link (§179): one value per option per sellable unit.

    UNIQUE (tenant, variant, option) makes size=M and size=L on one variant
    unrepresentable. option_id is denormalized onto the link so that
    constraint is expressible.
    """

    __tablename__ = "product_variant_option_values"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE")
    )
    option_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_options.id", ondelete="CASCADE")
    )
    option_value_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_option_values.id", ondelete="CASCADE")
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "variant_id",
            "option_id",
            name="uq_product_variant_option_values_tenant_variant_option",
        ),
    )
