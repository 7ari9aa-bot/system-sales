"""taxation: the business profile and tax classes.

Revision ID: fe2026112003
Revises: fe2026112002
Create Date: 2026-11-20 09:00:00.000000

The seller identity every fiscal document needs (tax registration number, commercial register,
address) and the tax class a product can carry. The database itself refuses a VAT-registered
business without a registration number and a number that is not exactly nine digits, and a
second default tax class. Tenant-scoped with ENABLE + FORCE + tenant_isolation from day one.
The three Egyptian classes (14% VAT, zero-rated, exempt) are seeded lazily by the service on
first use, so existing and new tenants take the same path and this migration stays reversible.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fe2026112003"
down_revision: str | None = "fe2026112002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
_TABLES = ("business_profiles", "tax_classes")


def _secure(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )
    op.execute(
        f"""DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO sales_app;
          END IF;
        END
        $$"""
    )


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "business_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("trade_name", sa.String(255)),
        sa.Column("vat_status", sa.String(15), nullable=False, server_default="not_registered"),
        sa.Column("tax_registration_number", sa.String(9)),
        sa.Column("commercial_register", sa.String(31)),
        sa.Column("activity_code", sa.String(15)),
        sa.Column("branch_code", sa.String(15), nullable=False, server_default="0"),
        sa.Column("governorate", sa.String(63)),
        sa.Column("city", sa.String(63)),
        sa.Column("street", sa.String(255)),
        sa.Column("building_number", sa.String(31)),
        sa.Column("postal_code", sa.String(15)),
        sa.Column("phone", sa.String(31)),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="EG"),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", name="uq_business_profiles_tenant"),
        sa.CheckConstraint(
            "vat_status IN ('registered', 'not_registered')", name="ck_business_profiles_vat_status"
        ),
        sa.CheckConstraint(
            "vat_status <> 'registered' OR tax_registration_number IS NOT NULL",
            name="ck_business_profiles_registered_needs_number",
        ),
        sa.CheckConstraint(
            "tax_registration_number IS NULL OR tax_registration_number ~ '^[0-9]{9}$'",
            name="ck_business_profiles_trn_nine_digits",
        ),
    )
    op.create_index("ix_business_profiles_tenant_id", "business_profiles", ["tenant_id"])

    op.create_table(
        "tax_classes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("code", sa.String(31), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("rate", sa.Numeric(6, 4), nullable=False),
        sa.Column("eta_tax_type", sa.String(7), nullable=False, server_default="T1"),
        sa.Column("eta_sub_type", sa.String(15), nullable=False, server_default="V009"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        *_stamps(),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tax_classes_tenant_code"),
        sa.CheckConstraint("rate >= 0 AND rate <= 1", name="ck_tax_classes_rate_fraction"),
    )
    op.create_index("ix_tax_classes_tenant_id", "tax_classes", ["tenant_id"])
    op.create_index(
        "uq_tax_classes_one_default",
        "tax_classes",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    for table in _TABLES:
        _secure(table)


def downgrade() -> None:
    op.drop_table("tax_classes")
    op.drop_table("business_profiles")
