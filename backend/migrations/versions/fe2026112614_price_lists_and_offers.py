"""Named price lists and offers, so section 07's three empty pages have something behind them.

Revision ID: fe2026112614
Revises: fe2026112613

The settings map gives Sales three pages that had nothing to edit: Price lists, Pricing and
Discounts and offers. They were left pending because the product had no price list, no pricing
rule and no offer engine — a page for any of them would have been a switch wired to nothing.

Deliberate modelling decisions:

- ``price_lists`` is a document with a name, a code, a currency, a priority and a date window.
  A shop keeps several live at once (retail, wholesale, a season), so the "which one applies"
  question is answered by the resolver, not by the table.
- ``price_list_items`` is keyed on (list, variant, min_quantity). A list carries its own quantity
  tiers, so no second table is needed, and a variant appears at most once per tier in a list.
- ``discount_rules`` stores what a rule DOES (percent or amount, capped, dated, optionally
  code-gated) and never a computed total. A stored total would be wrong the moment the basket
  changed.
- The CHECK constraints refuse the shapes that cannot mean anything: a percentage over 100, a
  scoped rule with no target, an order-wide rule that names one, a window that ends before it
  starts. The service checks the same things for a readable message; the database is the floor.
- Grants are wrapped in a ``pg_roles`` guard because CI runs migrations BEFORE
  ``scripts/provision.py`` creates ``sales_app``. Production has the role, CI does not, and an
  unguarded GRANT fails there while succeeding here.

No backfill: these are new tables, and a shop that never turns price lists on keeps using its
product prices exactly as before.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026112614"
down_revision: str | None = "fe2026112613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRANT_SALES_APP = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
        {grant};
    END IF;
END
$$;"""


def _grant_sales_app(grant: str) -> str:
    return _GRANT_SALES_APP.format(grant=grant)


def upgrade() -> None:
    op.create_table(
        "price_lists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=127), nullable=False),
        sa.Column("code", sa.String(length=31), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="EGP", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_price_lists_status"),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_price_lists_window",
        ),
    )
    op.create_index("ix_price_lists_tenant_id", "price_lists", ["tenant_id"])
    op.create_unique_constraint("uq_price_lists_tenant_code", "price_lists", ["tenant_id", "code"])

    op.create_table(
        "price_list_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "price_list_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("price_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "variant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("min_quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("min_quantity >= 1", name="ck_price_list_items_min_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_price_list_items_unit_price"),
    )
    op.create_index("ix_price_list_items_tenant_id", "price_list_items", ["tenant_id"])
    op.create_unique_constraint(
        "uq_price_list_items_list_variant_tier",
        "price_list_items",
        ["price_list_id", "variant_id", "min_quantity"],
    )

    op.create_table(
        "discount_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=127), nullable=False),
        sa.Column("code", sa.String(length=31), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Numeric(14, 2), nullable=False),
        sa.Column("scope", sa.String(length=16), server_default="order", nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("min_subtotal", sa.Numeric(14, 2), nullable=True),
        sa.Column("max_discount", sa.Numeric(14, 2), nullable=True),
        sa.Column("requires_code", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('percent', 'amount')", name="ck_discount_rules_kind"),
        sa.CheckConstraint(
            "scope IN ('order', 'category', 'variant')", name="ck_discount_rules_scope"
        ),
        sa.CheckConstraint("value >= 0", name="ck_discount_rules_value"),
        sa.CheckConstraint(
            "kind <> 'percent' OR value <= 100", name="ck_discount_rules_percent_ceiling"
        ),
        sa.CheckConstraint(
            "scope = 'order' OR target_id IS NOT NULL", name="ck_discount_rules_target"
        ),
        sa.CheckConstraint(
            "ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on",
            name="ck_discount_rules_window",
        ),
    )
    op.create_index("ix_discount_rules_tenant_id", "discount_rules", ["tenant_id"])
    op.create_unique_constraint(
        "uq_discount_rules_tenant_code", "discount_rules", ["tenant_id", "code"]
    )

    for table in ("price_lists", "price_list_items", "discount_rules"):
        op.execute(
            _grant_sales_app(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO sales_app")
        )


def downgrade() -> None:
    op.drop_table("discount_rules")
    op.drop_table("price_list_items")
    op.drop_table("price_lists")
