"""Add tax_rates catalog table and tax_rate_applied column to invoices.

Revision ID: fe2026111624
Revises: fe2026111622
Create Date: 2026-11-16 23:45:00.000000

- tax_rates: Global catalog of country-specific tax rates with effective_from /
  effective_until bounds. Ensures tax rates are database-driven and auditable.
- invoices.tax_rate_applied: Numeric(5, 4) stamping the exact tax rate applied
  when the invoice was issued, preserving tax immutability.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "fe2026111624"
down_revision: str | None = "fe2026111622"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create tax_rates table (global catalog, not tenant-scoped)
    op.create_table(
        "tax_rates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("rate", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column(
            "label_ar",
            sa.String(length=63),
            server_default="ضريبة القيمة المضافة",
            nullable=False,
        ),
        sa.Column("label_en", sa.String(length=63), server_default="VAT", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.UniqueConstraint(
            "country_code", "effective_from", name="uq_tax_rates_country_effective_from"
        ),
        sa.CheckConstraint("rate >= 0 AND rate <= 1", name="ck_tax_rates_rate_bounds"),
    )
    op.create_index("ix_tax_rates_country_code", "tax_rates", ["country_code"])

    # 2. Add tax_rate_applied to invoices
    op.add_column(
        "invoices",
        sa.Column("tax_rate_applied", sa.Numeric(precision=5, scale=4), nullable=True),
    )

    # 3. Seed initial tax rates for supported countries
    # Egypt 14% (Law 67 of 2016, effective 2016-09-08)
    op.execute(
        """
        INSERT INTO tax_rates (id, country_code, rate, effective_from, effective_until, label_ar, label_en, is_active)
        VALUES (gen_random_uuid(), 'EG', 0.1400, '2016-09-08', NULL, 'ضريبة القيمة المضافة', 'VAT', true)
        ON CONFLICT (country_code, effective_from) DO NOTHING
        """
    )
    # Saudi Arabia 5% historical (2018-01-01 to 2020-06-30)
    op.execute(
        """
        INSERT INTO tax_rates (id, country_code, rate, effective_from, effective_until, label_ar, label_en, is_active)
        VALUES (gen_random_uuid(), 'SA', 0.0500, '2018-01-01', '2020-06-30', 'ضريبة القيمة المضافة', 'VAT', false)
        ON CONFLICT (country_code, effective_from) DO NOTHING
        """
    )
    # Saudi Arabia 15% current (Royal Order, effective 2020-07-01)
    op.execute(
        """
        INSERT INTO tax_rates (id, country_code, rate, effective_from, effective_until, label_ar, label_en, is_active)
        VALUES (gen_random_uuid(), 'SA', 0.1500, '2020-07-01', NULL, 'ضريبة القيمة المضافة', 'VAT', true)
        ON CONFLICT (country_code, effective_from) DO NOTHING
        """
    )
    # UAE 5% (Federal Decree-Law 8 of 2017, effective 2018-01-01)
    op.execute(
        """
        INSERT INTO tax_rates (id, country_code, rate, effective_from, effective_until, label_ar, label_en, is_active)
        VALUES (gen_random_uuid(), 'AE', 0.0500, '2018-01-01', NULL, 'ضريبة القيمة المضافة', 'VAT', true)
        ON CONFLICT (country_code, effective_from) DO NOTHING
        """
    )
    # Qatar: No rows inserted, as Qatar has no standard VAT regime in 2026


def downgrade() -> None:
    op.drop_column("invoices", "tax_rate_applied")
    op.drop_index("ix_tax_rates_country_code", table_name="tax_rates")
    op.drop_table("tax_rates")
