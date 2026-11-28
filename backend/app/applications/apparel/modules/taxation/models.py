"""TAXATION models: the business profile and tax classes.

The business profile is the seller block of every fiscal document: without a tax registration
number there is no lawful e-receipt. It is ONE row per tenant (unique on tenant_id), edited in
place with the previous values kept in the audit log, never a pile of versions.
Enum-like columns are String with allowed values documented inline, never sa.Enum.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import IdMixin, TenantMixin, TimestampMixin

# Closed vocabularies (documented here, enforced by the service and the request model).
# The ETA e-receipt wants the seller's activity code and branch code; the rest is identity.
VAT_STATUSES: frozenset[str] = frozenset({"registered", "not_registered"})


class BusinessProfile(TenantMixin, TimestampMixin, IdMixin, Base):
    """The seller block printed on, and reported in, every fiscal document."""

    __tablename__ = "business_profiles"

    legal_name: Mapped[str] = mapped_column(String(255))
    trade_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # registered | not_registered. A shop below the VAT threshold still issues receipts.
    vat_status: Mapped[str] = mapped_column(
        String(15), default="not_registered", server_default="not_registered"
    )
    # Egyptian tax registration number: exactly 9 digits (stored as ASCII digits).
    tax_registration_number: Mapped[str | None] = mapped_column(String(9), nullable=True)
    commercial_register: Mapped[str | None] = mapped_column(String(31), nullable=True)
    activity_code: Mapped[str | None] = mapped_column(String(15), nullable=True)
    branch_code: Mapped[str] = mapped_column(String(15), default="0", server_default="0")
    governorate: Mapped[str | None] = mapped_column(String(63), nullable=True)
    city: Mapped[str | None] = mapped_column(String(63), nullable=True)
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    building_number: Mapped[str | None] = mapped_column(String(31), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(15), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(31), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), default="EG", server_default="EG")

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_business_profiles_tenant"),
        CheckConstraint(
            "vat_status IN ('registered', 'not_registered')", name="ck_business_profiles_vat_status"
        ),
        # A VAT-registered business MUST carry its registration number; the database refuses it.
        CheckConstraint(
            "vat_status <> 'registered' OR tax_registration_number IS NOT NULL",
            name="ck_business_profiles_registered_needs_number",
        ),
        CheckConstraint(
            "tax_registration_number IS NULL OR tax_registration_number ~ '^[0-9]{9}$'",
            name="ck_business_profiles_trn_nine_digits",
        ),
    )


class TaxClass(TenantMixin, TimestampMixin, IdMixin, Base):
    """A named tax treatment a product can carry: standard VAT, zero-rated, exempt.

    The rate is a fraction (0.14 = 14%). ``eta_sub_type`` is the code the e-receipt needs per
    line (V009 general VAT, V001 export...), kept here so the receipt never guesses it.
    """

    __tablename__ = "tax_classes"

    code: Mapped[str] = mapped_column(String(31))
    name: Mapped[str] = mapped_column(String(80))
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 4))
    eta_tax_type: Mapped[str] = mapped_column(String(7), default="T1", server_default="T1")
    eta_sub_type: Mapped[str] = mapped_column(String(15), default="V009", server_default="V009")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_tax_classes_tenant_code"),
        CheckConstraint("rate >= 0 AND rate <= 1", name="ck_tax_classes_rate_fraction"),
        # At most one default class per tenant.
        Index(
            "uq_tax_classes_one_default",
            "tenant_id",
            unique=True,
            postgresql_where="is_default",
        ),
    )
