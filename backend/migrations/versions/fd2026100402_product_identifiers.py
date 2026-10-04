"""product_identifiers — the catalog scan surface (Commerce Core v1.0 §179).

A product identifier binds a closed-vocabulary code (GTIN/EAN/UPC/barcode,
QR token, external id) to one sellable unit. (tenant_id, type, value) is
unique so the §179 resolver returns exactly one active variant or nothing —
never two candidates. POS (§189) is gated on this table.

RLS follows the a1b2c3d4e5f6 pattern — tenant_isolation policy plus grants
guarded by a sales_app role-exists DO block, so CI (which provisions
sales_app after Alembic) and production stay valid in either deploy order.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "fd2026100402"
down_revision: str | None = "fd2026100401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_GUARD = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "product_identifiers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column(
            "variant_id",
            sa.Uuid(),
            sa.ForeignKey("product_variants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(31), nullable=False),
        sa.Column("value", sa.String(127), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "type",
            "value",
            name="uq_product_identifiers_tenant_type_value",
        ),
    )
    op.create_foreign_key(
        "fk_product_identifiers_workspace_id",
        "product_identifiers",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_product_identifiers_location_id",
        "product_identifiers",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_product_identifiers_tenant_variant",
        "product_identifiers",
        ["tenant_id", "variant_id"],
        unique=False,
    )
    op.execute(
        "CREATE INDEX ix_product_identifiers_tenant_type_value "
        "ON product_identifiers (tenant_id, type, value)"
    )

    op.execute("ALTER TABLE product_identifiers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE product_identifiers FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON product_identifiers")
    op.execute(
        f"""CREATE POLICY tenant_isolation ON product_identifiers
            USING (tenant_id = {_TENANT_GUARD})
            WITH CHECK (tenant_id = {_TENANT_GUARD})"""
    )

    # CI provisions sales_app after Alembic, while production already has it.
    # Guard the grants so both deploy orders remain valid.
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sales_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
              product_identifiers TO sales_app;
          END IF;
        END
        $$"""
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON product_identifiers")
    op.drop_table("product_identifiers")
