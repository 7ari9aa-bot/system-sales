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
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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
