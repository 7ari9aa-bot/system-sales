"""Add country_code to tenants and create plan_prices catalog table.

Revision ID: fe2026111622
Revises: fe2026111621
Create Date: 2026-11-16 21:00:00.000000

- tenants.country_code: Stores the ISO 3166-1 alpha-2 market code for the workspace.
  Defaults to 'EG' for seamless backward compatibility.
- plan_prices: Database-driven, multi-country pricing catalog for plans. Enables
  country-specific pricing in local currency (EGP, SAR, AED, QAR) without code deploys.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111622"
down_revision: str | None = "fe2026111621"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add country_code to tenants table with server default 'EG'
    op.add_column(
        "tenants",
        sa.Column("country_code", sa.String(length=2), server_default="EG", nullable=False),
    )

    # 2. Create plan_prices table (global catalog, not tenant-scoped)
    op.create_table(
        "plan_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("price", sa.Numeric(precision=14, scale=2), server_default="0", nullable=False),
        sa.Column("interval", sa.String(length=15), server_default="month", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("plan_id", "country_code", "interval", name="uq_plan_prices_plan_country_interval"),
    )
    op.create_index("ix_plan_prices_plan_id", "plan_prices", ["plan_id"])
    op.create_index("ix_plan_prices_country_code", "plan_prices", ["country_code"])

    # 3. Backfill initial plan_prices from existing plans for 'EG'
    op.execute(
        """
        INSERT INTO plan_prices (id, plan_id, country_code, currency, price, interval, is_active)
        SELECT gen_random_uuid(), id, 'EG', currency, price, interval, is_active
        FROM plans
        ON CONFLICT (plan_id, country_code, interval) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_plan_prices_country_code", table_name="plan_prices")
    op.drop_index("ix_plan_prices_plan_id", table_name="plan_prices")
    op.drop_table("plan_prices")
    op.drop_column("tenants", "country_code")

