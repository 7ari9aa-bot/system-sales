"""What a shop charges, and what it takes off.

Three things were missing from the catalogue: a named price list, a rule that prices a whole
list differently from the product's own price, and an offer that takes money off an order. The
only price the system held was ``product_prices`` — an append-only history per variant, currency
and quantity tier. That answers "what does this cost", never "what does this cost for wholesale"
or "what happens on the last week of the season".

Deliberate modelling decisions:

- A price list is a document, not a settings key. It has rows, dates and a status, and a shop can
  keep several live at once. What IS a setting is whether price lists are used at all, which one
  is the default, and whether an offer may be stacked — those are policy, so they live in the
  registry (``pricing.*``).

- ``price_list_items`` is keyed on (list, variant, min_quantity) so a list can carry its own
  quantity tiers without a second table, and a variant appears at most once per tier in a list.

- A discount rule stores WHAT it does (percent or amount, capped) and WHO it applies to
  (order-wide, one category, one variant). It never stores a computed total: the total is worked
  out when the rule is applied, from the order in front of it. Storing the outcome would make the
  rule wrong the moment anything else changed.

- ``min_subtotal`` and ``max_discount`` are money columns, not percentages, because that is what
  the shop owner thinks in. A rule that would exceed ``max_discount`` is clamped, never rejected:
  refusing the sale would be worse than giving a smaller discount than promised.

- Nothing here writes to ``product_prices``. A price list is an override layer the resolver reads;
  the product's own price history stays the source of truth for the product.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.model_kit import (
    MONEY,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    WorkspaceScopeMixin,
)

# A discount is either a share of the line or a flat amount off it.
DISCOUNT_KINDS = ("percent", "amount")
# What a rule applies to. "order" needs no target; the other two do.
DISCOUNT_SCOPES = ("order", "category", "variant")
PRICE_LIST_STATUSES = ("active", "archived")


class PriceList(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """A named set of prices, optionally running between two dates."""

    __tablename__ = "price_lists"

    name: Mapped[str] = mapped_column(String(127))
    code: Mapped[str] = mapped_column(String(31))
    currency: Mapped[str] = mapped_column(String(3), server_default="EGP")
    is_default: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # Higher wins when two lists are live and the shop did not say which to use.
    priority: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default="active", nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_price_lists_tenant_code"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_price_lists_status"),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_price_lists_window",
        ),
    )


class PriceListItem(TenantMixin, TimestampMixin, IdMixin, Base):
    """One price for one variant inside one list, at one quantity tier."""

    __tablename__ = "price_list_items"

    price_list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    min_quantity: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "price_list_id",
            "variant_id",
            "min_quantity",
            name="uq_price_list_items_list_variant_tier",
        ),
        CheckConstraint("min_quantity >= 1", name="ck_price_list_items_min_quantity"),
        CheckConstraint("unit_price >= 0", name="ck_price_list_items_unit_price"),
    )


class DiscountRule(TenantMixin, TimestampMixin, WorkspaceScopeMixin, IdMixin, Base):
    """An offer: what it takes off, what it applies to, and when it is allowed to run."""

    __tablename__ = "discount_rules"

    name: Mapped[str] = mapped_column(String(127))
    code: Mapped[str | None] = mapped_column(String(31), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), server_default="order", nullable=False)
    # The category or variant the rule applies to. NULL for an order-wide rule.
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    min_subtotal: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    max_discount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    requires_code: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(16), server_default="active", nullable=False)
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_discount_rules_tenant_code"),
        CheckConstraint("kind IN ('percent', 'amount')", name="ck_discount_rules_kind"),
        CheckConstraint(
            "scope IN ('order', 'category', 'variant')", name="ck_discount_rules_scope"
        ),
        CheckConstraint("value >= 0", name="ck_discount_rules_value"),
        # A percent over 100 would pay the customer; a scoped rule with no target applies to
        # nothing. Both are refused at the database, not just in the form.
        CheckConstraint(
            "kind <> 'percent' OR value <= 100", name="ck_discount_rules_percent_ceiling"
        ),
        CheckConstraint(
            "scope = 'order' OR target_id IS NOT NULL", name="ck_discount_rules_target"
        ),
        CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name="ck_discount_rules_window",
        ),
    )
